"""Ingress web application and its small, authenticated JSON API."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
from pathlib import Path
from typing import Any

import aiohttp
from aiohttp import web
from aiohttp.typedefs import Handler, Middleware

from .config import AppConfig, load_config
from .errors import ProvisionerError, SessionError
from .jobs import JobManager
from .journal import TransactionJournal
from .meross_setup import MerossSetupClient
from .network_manager import NetworkManagerClient
from .supervisor import SupervisorClient
from .workflow import ProvisioningWorkflow

_LOGGER = logging.getLogger(__name__)
_STATIC_DIR = Path(__file__).with_name("static")

CONFIG_KEY: web.AppKey[AppConfig] = web.AppKey("config", AppConfig)
SUPERVISOR_KEY: web.AppKey[SupervisorClient] = web.AppKey(
    "supervisor", SupervisorClient
)
WORKFLOW_KEY: web.AppKey[ProvisioningWorkflow | None] = web.AppKey(
    "workflow", ProvisioningWorkflow
)
JOURNAL_KEY: web.AppKey[TransactionJournal] = web.AppKey("journal", TransactionJournal)
JOBS_KEY: web.AppKey[JobManager] = web.AppKey("jobs", JobManager)
DEVICE_SESSION_KEY: web.AppKey[aiohttp.ClientSession | None] = web.AppKey(
    "device_session", aiohttp.ClientSession
)
NETWORK_MANAGER_KEY: web.AppKey[NetworkManagerClient | None] = web.AppKey(
    "network_manager", NetworkManagerClient
)
RECOVERY_MESSAGE_KEY: web.AppKey[str | None] = web.AppKey("recovery_message", str)


def create_app(
    *,
    config: AppConfig | None = None,
    supervisor: SupervisorClient | None = None,
    workflow: ProvisioningWorkflow | None = None,
    journal: TransactionJournal | None = None,
    ingress_peer_ip: str | None = None,
    network_manager: NetworkManagerClient | None = None,
) -> web.Application:
    """Create the app; dependencies can be injected by hardware-free tests."""
    app_config = config or load_config()
    supervisor_client = supervisor or SupervisorClient(
        os.environ.get("SUPERVISOR_TOKEN")
    )
    state_journal = journal or TransactionJournal(app_config.journal_path)
    app = web.Application(
        client_max_size=16 * 1024,
        middlewares=[
            _require_ingress_peer(ingress_peer_ip or app_config.ingress_peer_ip)
        ],
    )
    app[CONFIG_KEY] = app_config
    app[SUPERVISOR_KEY] = supervisor_client
    app[WORKFLOW_KEY] = workflow
    app[JOURNAL_KEY] = state_journal
    app[JOBS_KEY] = JobManager()
    app[DEVICE_SESSION_KEY] = None
    app[NETWORK_MANAGER_KEY] = network_manager
    app[RECOVERY_MESSAGE_KEY] = None

    app.router.add_get("/", _index)
    app.router.add_get("/api/preflight", _preflight)
    app.router.add_get("/api/addons", _addons)
    app.router.add_get("/api/session", _session_status)
    app.router.add_post("/api/scan", _scan)
    app.router.add_post("/api/provision", _provision)
    app.router.add_get("/api/jobs/{job_id}", _job_status)
    app.router.add_post("/api/cancel", _cancel)
    app.on_startup.append(_recover_on_startup)
    app.on_cleanup.append(_cleanup)
    return app


def _require_ingress_peer(expected_peer: str) -> Middleware:
    """Accept requests only from the Supervisor's Ingress proxy."""
    try:
        expected = ipaddress.ip_address(expected_peer)
    except ValueError as err:
        raise ValueError("Ingress peer must be an IP address.") from err

    @web.middleware
    async def middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
        try:
            remote = ipaddress.ip_address(request.remote or "")
        except ValueError:
            raise web.HTTPForbidden(text="Use Home Assistant Ingress.") from None
        if remote != expected:
            raise web.HTTPForbidden(text="Use Home Assistant Ingress.")
        return await handler(request)

    return middleware


async def _index(_: web.Request) -> web.StreamResponse:
    return web.FileResponse(_STATIC_DIR / "index.html")


async def _preflight(request: web.Request) -> web.Response:
    workflow = _get_workflow(request.app)
    try:
        report = await workflow.preflight()
        return web.json_response(
            {
                "preflight": report.to_dict(),
                "recovery_message": request.app[RECOVERY_MESSAGE_KEY],
            }
        )
    except ProvisionerError as err:
        return _error_response(err)


async def _addons(request: web.Request) -> web.Response:
    workflow = _get_workflow(request.app)
    try:
        return web.json_response({"addons": await workflow.list_addons()})
    except ProvisionerError as err:
        return _error_response(err)


async def _session_status(request: web.Request) -> web.Response:
    workflow = _get_workflow(request.app)
    journal = request.app[JOURNAL_KEY]
    value = journal.read()
    return web.json_response(
        {
            "session_active": workflow.session_active,
            "recovery_required": value is not None,
            "recovery_phase": value.get("phase") if value else None,
        }
    )


async def _scan(request: web.Request) -> web.Response:
    workflow = _get_workflow(request.app)
    body = await _json_body(request)
    try:
        session_id, access_points = await workflow.scan(
            confirm_ap_interruption=body.get("confirm_ap_interruption") is True,
            confirm_dedicated_interface=body.get("confirm_dedicated_interface") is True,
        )
        return web.json_response(
            {
                "session_id": session_id,
                "access_points": [
                    {
                        "ssid": item.ssid,
                        "mac": item.mac,
                        "frequency": item.frequency,
                        "signal": item.signal,
                        "mode": item.mode,
                        "looks_like_meross": item.looks_like_meross_setup_ap,
                    }
                    for item in access_points
                ],
            }
        )
    except ProvisionerError as err:
        return _error_response(err)


async def _provision(request: web.Request) -> web.Response:
    workflow = _get_workflow(request.app)
    jobs = request.app[JOBS_KEY]
    body = await _json_body(request)
    required = (
        "session_id",
        "device_ssid",
        "device_bssid",
        "target_ssid",
        "target_password",
    )
    if any(not isinstance(body.get(key), str) for key in required):
        return web.json_response(
            {"error": "The provisioning request is incomplete."}, status=400
        )

    job = jobs.start(
        workflow.provision(
            session_id=body["session_id"],
            device_ssid=body["device_ssid"],
            device_bssid=body["device_bssid"],
            target_ssid=body["target_ssid"],
            target_password=body["target_password"],
        )
    )
    return web.json_response({"job_id": job.job_id}, status=202)


async def _job_status(request: web.Request) -> web.Response:
    jobs = request.app[JOBS_KEY]
    job = jobs.get(request.match_info["job_id"])
    if job is None:
        return web.json_response({"error": "Job not found or expired."}, status=404)
    return web.json_response(job.public_dict())


async def _cancel(request: web.Request) -> web.Response:
    workflow = _get_workflow(request.app)
    body = await _json_body(request)
    session_id = body.get("session_id")
    if not isinstance(session_id, str):
        return web.json_response({"error": "A session ID is required."}, status=400)
    try:
        await workflow.cancel(session_id)
        return web.json_response({"cancelled": True})
    except ProvisionerError as err:
        return _error_response(err)


async def _json_body(request: web.Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except (json.JSONDecodeError, web.HTTPException):
        raise web.HTTPBadRequest(
            text=json.dumps({"error": "Expected a JSON request."}),
            content_type="application/json",
        ) from None
    if not isinstance(value, dict):
        raise web.HTTPBadRequest(
            text=json.dumps({"error": "Expected a JSON object."}),
            content_type="application/json",
        )
    return value


def _error_response(error: ProvisionerError) -> web.Response:
    status = 409 if isinstance(error, SessionError) else 400
    return web.json_response({"error": str(error)}, status=status)


def _get_workflow(app: web.Application) -> ProvisioningWorkflow:
    workflow = app[WORKFLOW_KEY]
    if workflow is None:
        raise web.HTTPServiceUnavailable(text="The app is still initializing.")
    return workflow


async def _recover_on_startup(app: web.Application) -> None:
    workflow = app[WORKFLOW_KEY]
    if workflow is None:
        device_session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15),
            headers={"Content-Type": "application/json"},
            # The embedded setup server does not reliably support keep-alive.
            connector=aiohttp.TCPConnector(force_close=True),
        )
        app[DEVICE_SESSION_KEY] = device_session
        supervisor = app[SUPERVISOR_KEY]
        network_manager = app[NETWORK_MANAGER_KEY] or NetworkManagerClient()
        app[NETWORK_MANAGER_KEY] = network_manager
        config = app[CONFIG_KEY]
        workflow = ProvisioningWorkflow(
            supervisor=supervisor,
            network_manager=network_manager,
            device_factory=lambda gateway: MerossSetupClient(device_session, gateway),
            journal=app[JOURNAL_KEY],
            config=config.workflow,
        )
        app[WORKFLOW_KEY] = workflow

    for attempt in range(3):
        try:
            app[RECOVERY_MESSAGE_KEY] = await workflow.recover_interrupted_transaction()
            return
        except Exception as err:
            if attempt == 2:
                app[RECOVERY_MESSAGE_KEY] = (
                    "Automatic recovery is still required. Check the configured "
                    "AP app and start it from Home Assistant."
                )
                _LOGGER.error("Startup recovery failed (%s).", type(err).__name__)
                return
            await asyncio.sleep(2)


async def _cleanup(app: web.Application) -> None:
    jobs = app[JOBS_KEY]
    workflow = app[WORKFLOW_KEY]
    supervisor = app[SUPERVISOR_KEY]
    try:
        await jobs.close()
    finally:
        try:
            if workflow is not None:
                await workflow.close()
        finally:
            await supervisor.close()
            device_session = app[DEVICE_SESSION_KEY]
            if device_session is not None and not device_session.closed:
                await device_session.close()


def main() -> None:
    """Run the Ingress server."""
    config = load_config()
    app = create_app(config=config)
    web.run_app(app, host=config.bind_host, port=config.bind_port, access_log=None)
