"""Pure helpers for the Meross local setup-mode protocol."""

from __future__ import annotations

import base64
import binascii
import secrets
import time
from collections.abc import Mapping
from typing import Any

from .errors import DeviceProtocolError
from .models import DeviceInfo, DeviceWifiNetwork

CONFIG_ENDPOINT = "/config"
SUPPORTED_MODEL_PREFIXES = ("mss210", "mss425", "msl430")


def build_packet(
    *,
    method: str,
    namespace: str,
    payload: Mapping[str, Any] | None = None,
    source_url: str = "http://10.10.10.1/config",
) -> dict[str, Any]:
    """Build a setup-mode request with the protocol's required header fields."""
    return {
        "header": {
            "from": source_url,
            "messageId": secrets.token_hex(16),
            "timestamp": int(time.time()),
            "sign": "",
            "method": method,
            "namespace": namespace,
            "payloadVersion": 1,
        },
        "payload": dict(payload or {}),
    }


def parse_response(response: Any, *, expected_namespace: str) -> dict[str, Any]:
    """Validate a Meross response and return its payload."""
    if not isinstance(response, dict):
        raise DeviceProtocolError("The device returned a non-object response.")

    header = response.get("header")
    if isinstance(header, dict) and header.get("method") == "ERROR":
        error = response.get("error")
        code = error.get("code") if isinstance(error, dict) else "unknown"
        raise DeviceProtocolError(f"The device rejected the request (code {code}).")
    payload = response.get("payload")
    if not isinstance(header, dict) or not isinstance(payload, dict):
        if "error" in response:
            error = response.get("error")
            code = error.get("code") if isinstance(error, dict) else "unknown"
            raise DeviceProtocolError(f"The device rejected the request (code {code}).")
        raise DeviceProtocolError("The device response is missing header or payload.")

    method = header.get("method")
    namespace = header.get("namespace")
    if namespace != expected_namespace:
        raise DeviceProtocolError("The device response namespace did not match.")
    if method not in {"GETACK", "SETACK", "PUSH"}:
        raise DeviceProtocolError("The device returned an unexpected response method.")
    return payload


def decode_ssid(value: Any) -> str:
    """Decode a Base64 SSID while rejecting malformed or non-UTF-8 values."""
    if not isinstance(value, str):
        raise DeviceProtocolError("The device returned an invalid SSID value.")
    try:
        decoded = base64.b64decode(value, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as err:
        raise DeviceProtocolError("The device returned an unreadable SSID.") from err
    if not decoded or "\x00" in decoded:
        raise DeviceProtocolError("The device returned an empty or invalid SSID.")
    return decoded


def encode_wifi_text(value: str) -> str:
    """Base64-encode a UTF-8 Wi-Fi field as required by observed setup firmware."""
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def parse_device_info(payload: Mapping[str, Any]) -> DeviceInfo:
    """Extract device identity from an `Appliance.System.All` payload."""
    all_data = payload.get("all")
    if not isinstance(all_data, dict):
        raise DeviceProtocolError("The device response does not contain system data.")
    system = all_data.get("system")
    if not isinstance(system, dict):
        raise DeviceProtocolError("The device response does not contain system data.")
    hardware = system.get("hardware")
    firmware = system.get("firmware")
    if not isinstance(hardware, dict) or not isinstance(firmware, dict):
        raise DeviceProtocolError("The device did not report model and firmware data.")

    model = hardware.get("type")
    if not isinstance(model, str) or not model.strip():
        raise DeviceProtocolError("The device did not report a model identifier.")

    return DeviceInfo(
        model=model.strip(),
        subtype=str(hardware.get("subType", "")),
        firmware=str(firmware.get("version", "unknown")),
        uuid=str(hardware.get("uuid", "")),
        mac_address=str(hardware.get("macAddress", "")),
    )


def parse_wifi_list(payload: Mapping[str, Any]) -> list[DeviceWifiNetwork]:
    """Parse the device's Wi-Fi scan, preserving protocol security metadata."""
    wifi_list = payload.get("wifiList")
    if not isinstance(wifi_list, list):
        raise DeviceProtocolError("The device did not return a Wi-Fi scan list.")

    networks: list[DeviceWifiNetwork] = []
    for entry in wifi_list:
        if not isinstance(entry, dict):
            continue
        try:
            ssid = decode_ssid(entry.get("ssid"))
            bssid = str(entry["bssid"])
            channel = int(entry["channel"])
            signal = int(entry.get("signal", 0))
            cipher = int(entry["cipher"])
            encryption = int(entry["encryption"])
        except (KeyError, TypeError, ValueError) as err:
            raise DeviceProtocolError(
                "The device returned incomplete Wi-Fi security metadata."
            ) from err
        networks.append(
            DeviceWifiNetwork(
                ssid=ssid,
                bssid=bssid,
                channel=channel,
                signal=signal,
                cipher=cipher,
                encryption=encryption,
            )
        )
    return networks


def build_wifi_payload(
    network: DeviceWifiNetwork, password: str
) -> dict[str, dict[str, str | int]]:
    """Build the Wi-Fi-only SET payload; no cloud/MQTT key is included."""
    return {
        "wifi": {
            "ssid": encode_wifi_text(network.ssid),
            "password": encode_wifi_text(password),
            "bssid": network.bssid,
            "channel": network.channel,
            "cipher": network.cipher,
            "encryption": network.encryption,
        }
    }


def is_supported_model(model: str) -> bool:
    """Return whether the current prototype has an explicit test target family."""
    candidate = model.casefold()
    return any(candidate.startswith(prefix) for prefix in SUPPORTED_MODEL_PREFIXES)
