from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

from meross_provisioner import __version__

APP_DIR = Path(__file__).parents[1]
REPOSITORY_ROOT = Path(__file__).parents[2]


def test_app_manifests_are_consistent_and_least_privileged() -> None:
    app = yaml.safe_load((APP_DIR / "config.yaml").read_text(encoding="utf-8"))
    dockerfile = (APP_DIR / "Dockerfile").read_text(encoding="utf-8")

    assert app["slug"] == "meross_provisioner"
    assert app["version"] == "0.1.10"
    project = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert project["project"]["version"] == app["version"] == __version__
    assert set(app["arch"]) == {"aarch64", "amd64"}
    assert app["ingress"] is True
    assert app["hassio_api"] is True
    assert app["hassio_role"] == "manager"
    assert app["host_dbus"] is True
    assert "privileged" not in app
    assert app.get("host_network", False) is False
    assert dockerfile.startswith(
        "FROM ghcr.io/home-assistant/base-python:3.14-alpine3.24"
    )
    assert "apk add --no-cache networkmanager-cli" in dockerfile
    assert "python -m pip install" in dockerfile
    assert 'RUN python -c "import meross_provisioner.web"' in dockerfile
    assert not (APP_DIR / "build.yaml").exists()

    run_script = (APP_DIR / "run.sh").read_text(encoding="utf-8")
    assert run_script.startswith("#!/command/with-contenv bash")
    assert 'export PYTHONPATH="/app/src${PYTHONPATH:+:$PYTHONPATH}"' in run_script
    assert (APP_DIR / "CHANGELOG.md").is_file()
    assert (APP_DIR / "DOCS.md").is_file()
    assert (APP_DIR / "README.md").is_file()
    changelog = (APP_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
    release_headings = [
        line for line in changelog.splitlines() if line.startswith("## ")
    ]
    assert release_headings[0] == f"## {app['version']}"
    assert all(re.fullmatch(r"## \d+\.\d+\.\d+", line) for line in release_headings)
    installed_version = release_headings[1].removeprefix("## ")
    release_notes = re.search(
        rf"^#* {re.escape(app['version'])}\n"
        rf"(?:^(?!#* {re.escape(installed_version)}).*\n)*",
        changelog,
        re.MULTILINE,
    )
    assert release_notes is not None
    assert f"## {installed_version}" not in release_notes.group(0)
    for language in ("en", "es"):
        translations = yaml.safe_load(
            (APP_DIR / "translations" / f"{language}.yaml").read_text(encoding="utf-8")
        )
        assert set(translations["configuration"]) == set(app["schema"])


def test_repository_metadata_matches_the_online_addon_repository() -> None:
    repository = yaml.safe_load(
        (REPOSITORY_ROOT / "repository.yaml").read_text(encoding="utf-8")
    )

    assert repository["name"] == "Meross Provisioner"
    assert repository["url"] == "https://github.com/merchedev/ha-meross-provisioner"
    assert repository["maintainer"] == "merchedev"
    app = yaml.safe_load((APP_DIR / "config.yaml").read_text(encoding="utf-8"))
    assert app["url"] == repository["url"]
