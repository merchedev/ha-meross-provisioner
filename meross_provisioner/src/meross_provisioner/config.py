"""Load non-secret Home Assistant app options."""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigurationError
from .workflow import WorkflowConfig

DEFAULT_OPTIONS_PATH = Path("/data/options.json")


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Runtime configuration for the ingress app."""

    workflow: WorkflowConfig
    bind_host: str = "0.0.0.0"
    bind_port: int = 8099
    ingress_peer_ip: str = "172.30.32.2"
    journal_path: Path = Path("/data/transaction.json")


def load_config(path: Path = DEFAULT_OPTIONS_PATH) -> AppConfig:
    """Read add-on options without persisting the target Wi-Fi password."""
    if not path.exists():
        options: dict[str, Any] = {}
    else:
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as err:
            raise ConfigurationError("The app options file is unreadable.") from err
        if not isinstance(loaded, dict):
            raise ConfigurationError("The app options must be a JSON object.")
        options = loaded

    wifi_interface = options.get("wifi_interface", "wlan0")
    ap_slug = options.get("access_point_addon_slug", "")
    ingress_peer_ip = options.get("ingress_peer_ip", "172.30.32.2")
    if not all(
        isinstance(value, str) for value in (wifi_interface, ap_slug, ingress_peer_ip)
    ):
        raise ConfigurationError(
            "App interface, AP slug, and Ingress IP must be strings."
        )
    ingress_peer_ip = ingress_peer_ip.strip()
    try:
        ipaddress.ip_address(ingress_peer_ip)
    except ValueError as err:
        raise ConfigurationError(
            "The Supervisor Ingress peer must be an IP address."
        ) from err
    return AppConfig(
        workflow=WorkflowConfig(
            wifi_interface=wifi_interface.strip(),
            access_point_addon_slug=ap_slug.strip(),
        ),
        ingress_peer_ip=ingress_peer_ip,
    )
