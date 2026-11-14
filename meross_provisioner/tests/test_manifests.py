from __future__ import annotations

from pathlib import Path

import yaml

APP_DIR = Path(__file__).parents[1]
REPOSITORY_ROOT = Path(__file__).parents[2]


def test_app_manifests_are_consistent_and_least_privileged() -> None:
    app = yaml.safe_load((APP_DIR / "config.yaml").read_text(encoding="utf-8"))
    build = yaml.safe_load((APP_DIR / "build.yaml").read_text(encoding="utf-8"))

    assert app["slug"] == "meross_provisioner"
    assert app["version"] == "0.1.0"
    assert set(app["arch"]) == {"aarch64", "amd64"}
    assert app["ingress"] is True
    assert app["hassio_api"] is True
    assert app["hassio_role"] == "manager"
    assert "privileged" not in app
    assert app.get("host_network", False) is False
    assert set(build["build_from"]) == set(app["arch"])


def test_repository_metadata_matches_the_online_addon_repository() -> None:
    repository = yaml.safe_load(
        (REPOSITORY_ROOT / "repository.yaml").read_text(encoding="utf-8")
    )

    assert repository["name"] == "Meross Provisioner"
    assert repository["url"] == "https://github.com/merchedev/ha-meross-provisioner"
    assert repository["maintainer"] == "merchedev"
    app = yaml.safe_load((APP_DIR / "config.yaml").read_text(encoding="utf-8"))
    assert app["url"] == repository["url"]
