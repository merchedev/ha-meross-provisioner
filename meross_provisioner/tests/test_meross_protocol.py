from __future__ import annotations

import base64

import pytest

from meross_provisioner.errors import DeviceProtocolError
from meross_provisioner.meross_protocol import (
    build_packet,
    build_wifi_payload,
    decode_ssid,
    encode_wifi_text,
    is_supported_model,
    parse_device_info,
    parse_response,
    parse_wifi_list,
)
from meross_provisioner.models import DeviceWifiNetwork


def test_build_packet_contains_required_setup_headers() -> None:
    packet = build_packet(
        method="GET",
        namespace="Appliance.System.All",
        source_url="http://10.10.10.1/config",
    )

    header = packet["header"]
    assert header["from"] == "http://10.10.10.1/config"
    assert header["method"] == "GET"
    assert header["namespace"] == "Appliance.System.All"
    assert len(header["messageId"]) == 32
    assert set(packet) == {"header", "payload"}


def test_parse_response_returns_payload_for_expected_namespace() -> None:
    payload = {"all": {"system": {}}}
    response = {
        "header": {"method": "GETACK", "namespace": "Appliance.System.All"},
        "payload": payload,
    }

    assert (
        parse_response(response, expected_namespace="Appliance.System.All") == payload
    )


def test_parse_response_does_not_expose_device_error_detail() -> None:
    response = {
        "header": {"method": "ERROR", "namespace": "Appliance.Config.Wifi"},
        "payload": {},
        "error": {"code": 5001, "detail": "private data must not be echoed"},
    }

    with pytest.raises(DeviceProtocolError, match="code 5001") as error:
        parse_response(response, expected_namespace="Appliance.Config.Wifi")
    assert "private data" not in str(error.value)


def test_encode_and_decode_wifi_ssid_round_trip() -> None:
    ssid = "HA-AP-cocina"

    assert decode_ssid(encode_wifi_text(ssid)) == ssid


def test_decode_ssid_rejects_invalid_base64_and_binary_text() -> None:
    with pytest.raises(DeviceProtocolError):
        decode_ssid("not base64!")
    with pytest.raises(DeviceProtocolError):
        decode_ssid(base64.b64encode(b"\xff").decode("ascii"))


def test_decode_ssid_accepts_plain_text_and_strips_nul_padding() -> None:
    assert decode_ssid("HA-AP", allow_plain_text=True) == "HA-AP"
    padded = base64.b64encode(b"HA-AP\x00\x00").decode("ascii")
    assert decode_ssid(padded) == "HA-AP"


def test_wifi_list_skips_hidden_networks_without_aborting() -> None:
    payload = {
        "wifiList": [
            {
                "ssid": "",
                "bssid": "11:22:33:44:55:66",
                "channel": 1,
                "signal": 40,
                "cipher": 0,
                "encryption": 0,
            },
            {
                "ssid": encode_wifi_text("HA-AP"),
                "bssid": "aa:bb:cc:dd:ee:ff",
                "channel": 6,
                "signal": 72,
                "cipher": 3,
                "encryption": 6,
            },
        ]
    }

    assert [network.ssid for network in parse_wifi_list(payload)] == ["HA-AP"]


def test_wifi_list_accepts_plain_text_ssids_from_some_firmware() -> None:
    payload = {
        "wifiList": [
            {
                "ssid": "HA-AP",
                "bssid": "aa:bb:cc:dd:ee:ff",
                "channel": 6,
                "signal": 72,
                "cipher": 3,
                "encryption": 6,
            }
        ]
    }

    assert [network.ssid for network in parse_wifi_list(payload)] == ["HA-AP"]


def test_parse_device_identity() -> None:
    payload = {
        "all": {
            "system": {
                "hardware": {
                    "type": "mss210",
                    "subType": "eu",
                    "uuid": "uuid-placeholder",
                    "macAddress": "AA:BB:CC:DD:EE:FF",
                },
                "firmware": {"version": "1.0.0"},
            }
        }
    }

    info = parse_device_info(payload)
    assert info.model == "mss210"
    assert info.subtype == "eu"
    assert info.firmware == "1.0.0"
    assert info.mac_address == "AA:BB:CC:DD:EE:FF"


def test_wifi_list_preserves_device_reported_metadata() -> None:
    payload = {
        "wifiList": [
            {
                "ssid": encode_wifi_text("HA-AP"),
                "bssid": "aa:bb:cc:dd:ee:ff",
                "channel": 6,
                "signal": 72,
                "cipher": 3,
                "encryption": 6,
            }
        ]
    }

    assert parse_wifi_list(payload) == [
        DeviceWifiNetwork(
            ssid="HA-AP",
            bssid="aa:bb:cc:dd:ee:ff",
            channel=6,
            signal=72,
            cipher=3,
            encryption=6,
        )
    ]


def test_wifi_payload_contains_only_wifi_configuration() -> None:
    network = DeviceWifiNetwork(
        ssid="HA-AP",
        bssid="aa:bb:cc:dd:ee:ff",
        channel=6,
        signal=72,
        cipher=3,
        encryption=6,
    )

    payload = build_wifi_payload(network, "a-private-test-passphrase")
    assert set(payload) == {"wifi"}
    assert payload["wifi"]["ssid"] == encode_wifi_text("HA-AP")
    assert payload["wifi"]["password"] == encode_wifi_text("a-private-test-passphrase")
    assert payload["wifi"]["channel"] == 6


@pytest.mark.parametrize("model", ["mss210", "mss210hk", "mss425fc", "msl430"])
def test_initial_model_families_are_recognized(model: str) -> None:
    assert is_supported_model(model)


def test_unverified_model_is_not_supported_by_the_prototype() -> None:
    assert not is_supported_model("unknown_device")
