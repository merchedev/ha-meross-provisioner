from __future__ import annotations

import json

import pytest

from meross_provisioner.config import load_config
from meross_provisioner.errors import ConfigurationError


def test_load_config_defaults_are_safe_and_non_secret(tmp_path) -> None:
    config = load_config(tmp_path / "missing-options.json")

    assert config.workflow.wifi_interface == "wlan0"
    assert config.workflow.access_point_addon_slug == ""
    assert config.ingress_peer_ip == "172.30.32.2"
    assert str(config.journal_path) == "/data/transaction.json"


def test_load_config_reads_platform_options(tmp_path) -> None:
    path = tmp_path / "options.json"
    path.write_text(
        json.dumps(
            {
                "wifi_interface": " wlan1 ",
                "access_point_addon_slug": " local_ap ",
                "ingress_peer_ip": " 172.30.32.2 ",
            }
        ),
        encoding="utf-8",
    )

    config = load_config(path)

    assert config.workflow.wifi_interface == "wlan1"
    assert config.workflow.access_point_addon_slug == "local_ap"
    assert config.ingress_peer_ip == "172.30.32.2"


def test_load_config_rejects_invalid_ingress_peer(tmp_path) -> None:
    path = tmp_path / "options.json"
    path.write_text('{"ingress_peer_ip":"not-an-ip"}', encoding="utf-8")

    with pytest.raises(ConfigurationError, match="must be an IP address"):
        load_config(path)
