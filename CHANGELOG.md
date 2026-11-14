# Changelog

## 0.1.1 — use a Python-enabled Home Assistant base image

- Pin the app image to Home Assistant's Python base image.
- Remove the deprecated per-architecture `build.yaml` and build with `python -m pip`.
- Add an amd64 Docker image build to CI and bump the app version.

## 0.1.0 — initial experimental prototype

- Add a Home Assistant Ingress app skeleton with Supervisor preflight and recovery.
- Add local Meross SoftAP protocol helpers for device identity, Wi-Fi scan, and Wi-Fi-only setup.
- Add a bounded scan/provision workflow, explicit AP interruption confirmation, and a non-secret recovery journal.
- Add mocked tests, CI checks, security guidance, agent instructions, and initial platform documentation.
- No physical-device or Raspberry Pi 5 / Home Assistant OS validation has been completed.
