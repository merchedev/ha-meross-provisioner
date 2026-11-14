"""HTTP transport to a Meross device in its local setup mode."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .errors import DeviceProtocolError
from .meross_protocol import (
    build_packet,
    build_wifi_payload,
    parse_device_info,
    parse_response,
    parse_wifi_list,
)
from .models import DeviceInfo, DeviceWifiNetwork

_LOGGER = logging.getLogger(__name__)


class MerossSetupClient:
    """Small client for the documented setup-mode `/config` endpoint."""

    def __init__(
        self,
        session: ClientSession,
        gateway: str,
        *,
        timeout_seconds: float = 8.0,
        retry_delays: tuple[float, ...] = (1.0, 2.0, 3.0),
    ) -> None:
        try:
            address = ipaddress.ip_address(gateway)
        except ValueError as err:
            raise DeviceProtocolError(
                "The Meross setup gateway is not an IP address."
            ) from err
        if address.version != 4 or not address.is_private:
            raise DeviceProtocolError(
                "The Meross setup gateway must be a private IPv4 address."
            )
        self._session = session
        self._host = str(address)
        self._timeout = ClientTimeout(total=timeout_seconds)
        self._retry_delays = retry_delays

    async def _request(
        self,
        *,
        method: str,
        namespace: str,
        payload: dict[str, Any] | None = None,
        operation: str = "during setup",
        retry_delays: tuple[float, ...] = (),
    ) -> dict[str, Any]:
        """Send one request, retrying only when the transport is not ready."""
        attempts = len(retry_delays) + 1
        body: dict[str, Any] | None = None
        for attempt in range(attempts):
            try:
                body = await self._post(
                    method=method, namespace=namespace, payload=payload
                )
                break
            except (ClientError, TimeoutError) as err:
                if attempt + 1 >= attempts:
                    detail = _describe_connection_error(err)
                    _LOGGER.warning(
                        "Meross setup request failed %s (%s)", operation, detail
                    )
                    raise DeviceProtocolError(
                        "Home Assistant could not reach the Meross setup AP "
                        f"{operation} ({detail})."
                    ) from err
                await asyncio.sleep(retry_delays[attempt])
        if body is None:
            raise DeviceProtocolError(
                f"Home Assistant could not reach the Meross setup AP {operation}."
            )

        result = parse_response(body, expected_namespace=namespace)
        response_header = body.get("header")
        expected_method = "GETACK" if method == "GET" else "SETACK"
        if (
            not isinstance(response_header, dict)
            or response_header.get("method") != expected_method
        ):
            raise DeviceProtocolError(
                "The device did not acknowledge the setup request."
            )
        return result

    async def _post(
        self,
        *,
        method: str,
        namespace: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        packet = build_packet(
            method=method,
            namespace=namespace,
            payload=payload,
            source_url=f"http://{self._host}/config",
        )
        async with self._session.post(
            f"http://{self._host}/config",
            json=packet,
            headers={"Content-Type": "application/json"},
            timeout=self._timeout,
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                raise DeviceProtocolError(
                    f"The device setup endpoint returned HTTP {response.status}."
                )
            try:
                body = await response.json(content_type=None)
            except (TypeError, ValueError) as err:
                raise DeviceProtocolError(
                    "The device returned invalid JSON during setup."
                ) from err
        if not isinstance(body, dict):
            raise DeviceProtocolError(
                "The device returned a non-object response during setup."
            )
        return body

    async def get_device_info(self) -> DeviceInfo:
        """Read the model and firmware before any write operation."""
        payload = await self._request(
            method="GET",
            namespace="Appliance.System.All",
            operation="while reading device information",
            retry_delays=self._retry_delays,
        )
        return parse_device_info(payload)

    async def get_wifi_list(self) -> list[DeviceWifiNetwork]:
        """Read the security metadata the device reports for nearby Wi-Fi."""
        payload = await self._request(
            method="GET",
            namespace="Appliance.Config.WifiList",
            operation="while reading the device Wi-Fi list",
            retry_delays=self._retry_delays,
        )
        return parse_wifi_list(payload)

    async def set_wifi(self, network: DeviceWifiNetwork, password: str) -> None:
        """Send only the selected Wi-Fi profile; do not configure an MQTT key."""
        await self._request(
            method="SET",
            namespace="Appliance.Config.Wifi",
            payload=build_wifi_payload(network, password),
            operation="while sending the Wi-Fi configuration",
        )


def _describe_connection_error(error: BaseException) -> str:
    """Return a safe error class and errno without including packet contents."""
    detail = type(error).__name__
    os_error = getattr(error, "os_error", None)
    if isinstance(os_error, OSError) and os_error.errno is not None:
        detail += f", errno {os_error.errno}"
    return detail
