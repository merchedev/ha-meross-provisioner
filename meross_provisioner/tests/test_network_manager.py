from __future__ import annotations

import pytest

from meross_provisioner.errors import NetworkManagerError
from meross_provisioner.network_manager import (
    NetworkManagerClient,
    _split_nmcli_fields,
)


def test_nmcli_parser_unescapes_colons_in_ssid_and_bssid() -> None:
    fields = _split_nmcli_fields(
        r"Meross\:setup:aa\:bb\:cc\:dd\:ee\:ff:2412 MHz:73:Infra"
    )

    assert fields == ["Meross:setup", "aa:bb:cc:dd:ee:ff", "2412 MHz", "73", "Infra"]


@pytest.mark.asyncio
async def test_scan_maps_nmcli_output_to_access_points() -> None:
    client = NetworkManagerClient()

    async def fake_run(*args: str, **kwargs: object) -> str:
        return r"Meross_SETUP:aa\:bb\:cc\:dd\:ee\:ff:2412 MHz:77:Infra"

    client._run = fake_run
    access_points = await client.scan_access_points("wlan0")

    assert len(access_points) == 1
    assert access_points[0].ssid == "Meross_SETUP"
    assert access_points[0].mac == "aa:bb:cc:dd:ee:ff"
    assert access_points[0].frequency == 2412
    assert access_points[0].mode == "infrastructure"


@pytest.mark.asyncio
async def test_saved_wifi_profile_detection_does_not_return_profile_names() -> None:
    client = NetworkManagerClient()

    async def fake_run(*args: str, **kwargs: object) -> str:
        return "802-3-ethernet\n802-11-wireless"

    client._run = fake_run

    assert await client.has_saved_wifi_profiles()


@pytest.mark.asyncio
async def test_open_connection_is_uuid_scoped_and_bssid_locked() -> None:
    client = NetworkManagerClient()
    captured: list[str] = []

    async def fake_run(*args: str, **kwargs: object) -> str:
        captured.extend(args)
        return ""

    client._run = fake_run
    connection_uuid = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

    await client.create_open_connection(
        "wlan0", "Meross_SETUP", "aa:bb:cc:dd:ee:ff", connection_uuid
    )

    assert connection_uuid in captured
    assert "aa:bb:cc:dd:ee:ff" in captured
    assert "connection.autoconnect" in captured
    assert "none" in captured
    assert "password" not in captured


@pytest.mark.asyncio
async def test_open_connection_rejects_invalid_bssid_before_running_nmcli() -> None:
    client = NetworkManagerClient()
    called = False

    async def fake_run(*args: str, **kwargs: object) -> str:
        nonlocal called
        called = True
        return ""

    client._run = fake_run
    with pytest.raises(NetworkManagerError, match="invalid BSSID"):
        await client.create_open_connection(
            "wlan0",
            "Meross_SETUP",
            "not-a-bssid",
            "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
        )
    assert not called
