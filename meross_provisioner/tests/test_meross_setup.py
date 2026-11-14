from __future__ import annotations

from typing import Any

import aiohttp
import pytest

from meross_provisioner.errors import DeviceProtocolError
from meross_provisioner.meross_setup import MerossSetupClient
from meross_provisioner.models import DeviceWifiNetwork


class FakeResponse:
    def __init__(self, body: dict[str, Any], status: int = 200) -> None:
        self.status = status
        self._body = body

    async def json(self, content_type: str | None = None) -> dict[str, Any]:
        return self._body

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class FakeSession:
    def __init__(self, results: list[FakeResponse | BaseException]) -> None:
        self._results = list(results)
        self.calls = 0

    def post(self, *args: object, **kwargs: object) -> FakeResponse:
        self.calls += 1
        result = self._results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class ConnectionFailure(aiohttp.ClientError):
    def __init__(self) -> None:
        super().__init__("connection failed")
        self.os_error = OSError(113, "No route to host")


def _device_info_response() -> dict[str, Any]:
    return {
        "header": {
            "method": "GETACK",
            "namespace": "Appliance.System.All",
        },
        "payload": {
            "all": {
                "system": {
                    "hardware": {
                        "type": "MSS210",
                        "subType": "eu",
                        "uuid": "test-uuid",
                        "macAddress": "aa:bb:cc:dd:ee:ff",
                    },
                    "firmware": {"version": "1.0.0"},
                }
            }
        },
    }


@pytest.mark.asyncio
async def test_get_device_info_retries_until_setup_http_is_ready() -> None:
    session = FakeSession(
        [
            aiohttp.ClientConnectionError("not ready"),
            aiohttp.ServerDisconnectedError("not ready"),
            FakeResponse(_device_info_response()),
        ]
    )
    client = MerossSetupClient(session, "10.10.10.1", retry_delays=(0, 0))

    info = await client.get_device_info()

    assert info.model == "MSS210"
    assert session.calls == 3


@pytest.mark.asyncio
async def test_unreachable_error_reports_safe_transport_detail() -> None:
    session = FakeSession([ConnectionFailure()])
    client = MerossSetupClient(session, "10.10.10.1", retry_delays=())

    with pytest.raises(
        DeviceProtocolError,
        match="while reading device information.*ConnectionFailure, errno 113",
    ):
        await client.get_device_info()


@pytest.mark.asyncio
async def test_set_wifi_is_not_retried() -> None:
    session = FakeSession([aiohttp.ClientConnectionError("not ready")])
    client = MerossSetupClient(session, "10.10.10.1", retry_delays=(0, 0, 0))

    with pytest.raises(DeviceProtocolError, match="ClientConnectionError"):
        await client.set_wifi(
            DeviceWifiNetwork(
                ssid="HA-AP",
                bssid="aa:bb:cc:dd:ee:ff",
                channel=6,
                signal=-40,
                cipher=3,
                encryption=6,
            ),
            "test-password",
        )

    assert session.calls == 1
