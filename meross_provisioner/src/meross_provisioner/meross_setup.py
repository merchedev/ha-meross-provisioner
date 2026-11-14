"""HTTP transport to a Meross device in its local setup mode."""

from __future__ import annotations

import ipaddress
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


class MerossSetupClient:
    """Small client for the documented setup-mode `/config` endpoint."""

    def __init__(
        self,
        session: ClientSession,
        gateway: str,
        *,
        timeout_seconds: float = 6.0,
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

    async def _request(
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
        try:
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
        except (ClientError, TimeoutError) as err:
            raise DeviceProtocolError(
                "Home Assistant could not reach the Meross setup AP."
            ) from err

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

    async def get_device_info(self) -> DeviceInfo:
        """Read the model and firmware before any write operation."""
        payload = await self._request(method="GET", namespace="Appliance.System.All")
        return parse_device_info(payload)

    async def get_wifi_list(self) -> list[DeviceWifiNetwork]:
        """Read the security metadata the device reports for nearby Wi-Fi."""
        payload = await self._request(
            method="GET", namespace="Appliance.Config.WifiList"
        )
        return parse_wifi_list(payload)

    async def set_wifi(self, network: DeviceWifiNetwork, password: str) -> None:
        """Send only the selected Wi-Fi profile; do not configure an MQTT key."""
        await self._request(
            method="SET",
            namespace="Appliance.Config.Wifi",
            payload=build_wifi_payload(network, password),
        )
