"""In-memory background jobs for operations that outlast an HTTP request."""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .errors import ProvisionerError

_LOGGER = logging.getLogger(__name__)
_JOB_RETENTION = timedelta(minutes=15)


@dataclass(slots=True)
class Job:
    """A short-lived operation; inputs and credentials are never retained."""

    job_id: str
    status: str = "running"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    result: dict[str, Any] | None = None
    error: str | None = None
    task: asyncio.Task[None] | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "result": self.result,
            "error": self.error,
        }


class JobManager:
    """Run provisioning in the background and expose safe status only."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def start(self, operation: Awaitable[Any]) -> Job:
        self._prune()
        job = Job(job_id=secrets.token_urlsafe(18))
        self._jobs[job.job_id] = job
        job.task = asyncio.create_task(self._run(job, operation), name="meross-job")
        return job

    def get(self, job_id: str) -> Job | None:
        self._prune()
        return self._jobs.get(job_id)

    async def close(self) -> None:
        tasks = [job.task for job in self._jobs.values() if job.task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run(self, job: Job, operation: Awaitable[Any]) -> None:
        try:
            result = await operation
            job.result = result.to_dict() if hasattr(result, "to_dict") else result
            job.status = "succeeded"
        except ProvisionerError as err:
            job.error = str(err)
            job.status = "failed"
        except asyncio.CancelledError:
            job.error = "The operation was interrupted; recovery was attempted."
            job.status = "failed"
            raise
        except Exception:
            _LOGGER.exception("Unexpected failure in a provisioning job")
            job.error = "Unexpected internal error. Check redacted app logs."
            job.status = "failed"

    def _prune(self) -> None:
        cutoff = datetime.now(UTC) - _JOB_RETENTION
        for job_id, job in tuple(self._jobs.items()):
            if job.created_at < cutoff and job.status != "running":
                del self._jobs[job_id]
