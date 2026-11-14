from __future__ import annotations

from pathlib import Path

import yaml

APP_DIR = Path(__file__).parents[1]
REPOSITORY_ROOT = Path(__file__).parents[2]


def test_app_manifests_are_consistent_and_least_privileged() -> None:
    app = yaml.safe_load((APP_DIR / "config.yaml").read_text(encoding="utf-8"))
    dockerfile = (APP_DIR / "Dockerfile").read_text(encoding="utf-8")

    assert app["slug"] == "meross_provisioner"
    assert app["version"] == "0.1.1"
    assert set(app["arch"]) == {"aarch64", "amd64"}
    assert app["ingress"] is True
    assert app["hassio_api"] is True
    assert app["hassio_role"] == "manager"
    assert "privileged" not in app
    assert app.get("host_network", False) is False
    assert dockerfile.startswith(
        "FROM ghcr.io/home-assistant/base-python:3.14-alpine3.24"
    )
    assert "python -m pip install" in dockerfile
    assert not (APP_DIR / "build.yaml").exists()


def test_repository_metadata_matches_the_online_addon_repository() -> None:
    repository = yaml.safe_load(
        (REPOSITORY_ROOT / "repository.yaml").read_text(encoding="utf-8")
    )

    assert repository["name"] == "Meross Provisioner"
    assert repository["url"] == "https://github.com/merchedev/ha-meross-provisioner"
    assert repository["maintainer"] == "merchedev"
    app = yaml.safe_load((APP_DIR / "config.yaml").read_text(encoding="utf-8"))
    assert app["url"] == repository["url"]
