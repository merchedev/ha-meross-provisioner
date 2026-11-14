"""Crash-recovery journal containing no credentials or raw protocol data."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_ALLOWED_FIELDS = {
    "interface",
    "access_point_addon_slug",
    "phase",
    "ap_was_running",
    "remove_temporary_profile",
    "temporary_connection_uuid",
    "suspended_profile_uuids",
    "created_at",
}
_REQUIRED_FIELDS = {
    "interface",
    "access_point_addon_slug",
    "phase",
    "ap_was_running",
    "remove_temporary_profile",
}


class TransactionJournal:
    """Persist just enough metadata to attempt AP restoration after a crash."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def read(self) -> dict[str, Any] | None:
        if not self._path.exists():
            return None
        try:
            value = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict):
            return None
        if (
            not _REQUIRED_FIELDS.issubset(value)
            or set(value) - _ALLOWED_FIELDS
            or not isinstance(value.get("interface"), str)
            or not isinstance(value.get("access_point_addon_slug"), str)
            or not isinstance(value.get("phase"), str)
            or not isinstance(value.get("ap_was_running"), bool)
            or not isinstance(value.get("remove_temporary_profile"), bool)
            or (
                "temporary_connection_uuid" in value
                and value["temporary_connection_uuid"] is not None
                and not isinstance(value["temporary_connection_uuid"], str)
            )
            or (
                "suspended_profile_uuids" in value
                and not isinstance(value["suspended_profile_uuids"], str)
            )
        ):
            return None
        return value

    def write(self, value: dict[str, Any]) -> None:
        """Write only the fixed, non-secret recovery schema."""
        if set(value) - _ALLOWED_FIELDS or not _REQUIRED_FIELDS.issubset(value):
            raise ValueError("Transaction journal contains unsupported fields.")
        if (
            not isinstance(value["interface"], str)
            or not isinstance(value["access_point_addon_slug"], str)
            or not isinstance(value["phase"], str)
            or not isinstance(value["ap_was_running"], bool)
            or not isinstance(value["remove_temporary_profile"], bool)
            or (
                "temporary_connection_uuid" in value
                and value["temporary_connection_uuid"] is not None
                and not isinstance(value["temporary_connection_uuid"], str)
            )
            or (
                "suspended_profile_uuids" in value
                and not isinstance(value["suspended_profile_uuids"], str)
            )
        ):
            raise ValueError("Transaction journal fields have invalid types.")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self._path)

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
