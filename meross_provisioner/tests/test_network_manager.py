from __future__ import annotations

import pytest

from meross_provisioner.errors import NetworkManagerError
from meross_provisioner.models import WifiProfile
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
    client = NetworkManagerClient(scan_delay=0)

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
@pytest.mark.parametrize(
    ("profiles", "profile_data", "expected"),
    [
        (
            "home-wifi:11111111-1111-4111-8111-111111111111:802-11-wireless",
            {
                "11111111-1111-4111-8111-111111111111": {
                    "connection.interface-name": "wlan0",
                    "connection.autoconnect": "yes",
                }
            },
            [
                WifiProfile(
                    name="home-wifi",
                    connection_uuid="11111111-1111-4111-8111-111111111111",
                )
            ],
        ),
        (
            "other-wifi:22222222-2222-4222-8222-222222222222:802-11-wireless",
            {
                "22222222-2222-4222-8222-222222222222": {
                    "connection.interface-name": "wlan1",
                    "connection.autoconnect": "yes",
                }
            },
            [],
        ),
        (
            "manual-wifi:33333333-3333-4333-8333-333333333333:802-11-wireless",
            {
                "33333333-3333-4333-8333-333333333333": {
                    "connection.interface-name": "wlan0",
                    "connection.autoconnect": "no",
                }
            },
            [],
        ),
        (
            "unbound-wifi:44444444-4444-4444-8444-444444444444:802-11-wireless",
            {
                "44444444-4444-4444-8444-444444444444": {
                    "connection.interface-name": "",
                    "connection.autoconnect": "yes",
                }
            },
            [
                WifiProfile(
                    name="unbound-wifi",
                    connection_uuid="44444444-4444-4444-8444-444444444444",
                )
            ],
        ),
    ],
)
async def test_only_autoconnecting_profiles_for_the_target_interface_block(
    profiles: str,
    profile_data: dict[str, dict[str, str]],
    expected: list[WifiProfile],
) -> None:
    client = NetworkManagerClient()

    async def fake_run(*args: str, **kwargs: object) -> str:
        if args[:2] == ("--terse", "--escape"):
            return profiles
        setting = args[1]
        profile_uuid = args[-1]
        return profile_data[profile_uuid][setting]

    client._run = fake_run

    assert (await client.find_autoconnecting_wifi_profiles("wlan0")) == expected


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


@pytest.mark.asyncio
async def test_managed_up_brings_wifi_link_back_after_hostapd() -> None:
    client = NetworkManagerClient()
    calls: list[tuple[str, ...]] = []

    async def fake_run(*args: str, **kwargs: object) -> str:
        calls.append(args)
        return ""

    client._run = fake_run
    await client.enable_wifi_radio()
    await client.set_managed("wlan0", True)
    await client.set_managed("wlan0", False)

    assert calls[0] == ("radio", "wifi", "on")
    assert calls[1] == ("device", "set", "wlan0", "managed", "yes")
    assert calls[2] == ("device", "set", "wlan0", "managed", "no")


@pytest.mark.asyncio
async def test_autoconnect_changes_are_scoped_to_known_uuids() -> None:
    client = NetworkManagerClient()
    calls: list[tuple[str, ...]] = []

    async def fake_run(*args: str, **kwargs: object) -> str:
        calls.append(args)
        return ""

    client._run = fake_run
    first = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    second = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"

    await client.set_profiles_autoconnect([first, second], False)
    await client.set_profiles_autoconnect([first], True)

    assert calls[0][-1] == "no"
    assert calls[1][-1] == "no"
    assert calls[2] == (
        "connection",
        "modify",
        "uuid",
        first,
        "connection.autoconnect",
        "yes",
    )
