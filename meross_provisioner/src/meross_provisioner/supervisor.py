"""Minimal client for the Home Assistant Supervisor API."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import aiohttp

from .errors import ConfigurationError, SupervisorError


class SupervisorClient:
    """Use the Supervisor token injected into a Home Assistant app."""

    def __init__(
        self,
        token: str | None,
        *,
        session: aiohttp.ClientSession | None = None,
        base_url: str = "http://supervisor",
    ) -> None:
        if not token:
            raise ConfigurationError(
                "SUPERVISOR_TOKEN is unavailable. Run this app under "
                "Home Assistant Supervisor."
            )
        self._token = token
        self._session = session
        self._owns_session = session is None
        self._base_url = base_url.rstrip("/")

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=aiohttp.ClientTimeout(total=20),
            )
        return self._session

    async def close(self) -> None:
        """Close the HTTP session if this client created it."""
        if self._owns_session and self._session is not None:
            await self._session.close()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, Any] | None = None,
        timeout_seconds: float = 20,
    ) -> dict[str, Any]:
        session = await self._get_session()
        try:
            async with session.request(
                method,
                f"{self._base_url}{path}",
                json=dict(body) if body is not None else None,
                timeout=aiohttp.ClientTimeout(total=timeout_seconds),
            ) as response:
                try:
                    result = await response.json(content_type=None)
                except (TypeError, ValueError) as err:
                    raise SupervisorError(
                        "The Supervisor returned an invalid response."
                    ) from err
        except (aiohttp.ClientError, TimeoutError) as err:
            raise SupervisorError(
                "Home Assistant could not contact the Supervisor API."
            ) from err

        if not isinstance(result, dict) or response.status >= 400:
            raise SupervisorError(
                f"The Supervisor API request {method} {path} failed "
                f"(HTTP {response.status})."
            )
        if result.get("result") != "ok":
            # Do not forward arbitrary API messages; they may contain config values.
            raise SupervisorError(f"The Supervisor rejected {method} {path}.")
        data = result.get("data", {})
        if not isinstance(data, dict):
            raise SupervisorError("The Supervisor returned an unexpected data object.")
        return data

    async def get_network_info(self) -> dict[str, Any]:
        return await self._request("GET", "/network/info")

    async def get_addons(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/addons")
        addons = data.get("addons")
        if not isinstance(addons, list):
            raise SupervisorError("The Supervisor returned no app list.")
        return [item for item in addons if isinstance(item, dict)]

    async def get_addon_info(self, slug: str) -> dict[str, Any]:
        encoded_slug = quote(slug, safe="")
        return await self._request("GET", f"/addons/{encoded_slug}/info")

    async def stop_addon(self, slug: str) -> None:
        encoded_slug = quote(slug, safe="")
        await self._request("POST", f"/addons/{encoded_slug}/stop")

    async def start_addon(self, slug: str) -> None:
        encoded_slug = quote(slug, safe="")
        await self._request("POST", f"/addons/{encoded_slug}/start", timeout_seconds=75)

    async def restart_addon(self, slug: str) -> None:
        encoded_slug = quote(slug, safe="")
        await self._request(
            "POST", f"/addons/{encoded_slug}/restart", timeout_seconds=75
        )
