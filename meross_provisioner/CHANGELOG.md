# Changelog

## 0.1.9

- Wait for NetworkManager to bring the Wi-Fi device up after stopping the AP.
- Rescan with retries and report nearby networks when no Meross setup AP is found.

## 0.1.8

- Automatically suspend autoconnect for saved Wi-Fi profiles that could claim the AP interface.
- Restore their autoconnect state after provisioning, cancellation, timeout, or crash recovery.
- Remove the need to edit NetworkManager profiles manually.
- Wait for NetworkManager to bring the Wi-Fi device up and retry scans after stopping the AP.
- Report nearby network names when no Meross setup AP is found.

## 0.1.7

- Only block saved Wi-Fi profiles that could autoconnect to the selected AP interface.
- Show the names of blocking profiles in preflight without exposing credentials.
- Format release headings so Home Assistant shows only updates newer than the installed version.

## 0.1.6

- Use NetworkManager over host D-Bus when the AP app marks its Wi-Fi device unmanaged.
- Scan and connect with a UUID-scoped temporary profile; preserve other profiles.
- Improve preflight diagnostics for interfaces NetworkManager cannot see.

## 0.1.5

- Use NetworkManager over host D-Bus for interfaces marked unmanaged by the AP app.
- Create and remove only a uniquely identified temporary Wi-Fi connection.
- Add NetworkManager preflight and parser tests.

## 0.1.4

- Include the failing Supervisor endpoint in safe preflight errors.
- Report the wireless interfaces visible to the Supervisor before scanning.

## 0.1.3

- Start through S6 `with-contenv` so the Supervisor token reaches the app.
- Set the Python source path explicitly and verify the web module imports during image build.
- Add translated configuration help and a Home Assistant documentation tab.

## 0.1.2

- Export the application source path in the startup script.
- Fail the image build if the Python package cannot be imported.
- Bump the app version so Home Assistant rebuilds the image.

## 0.1.1

- Pin the app image to Home Assistant's Python base image.
- Remove the deprecated per-architecture `build.yaml` and build with `python -m pip`.
- Add an amd64 Docker image build to CI and bump the app version.

## 0.1.0

- Add a Home Assistant Ingress app skeleton with Supervisor preflight and recovery.
- Add local Meross SoftAP protocol helpers for device identity, Wi-Fi scan, and Wi-Fi-only setup.
- Add a bounded scan/provision workflow, explicit AP interruption confirmation, and a non-secret recovery journal.
- Add mocked tests, CI checks, security guidance, agent instructions, and initial platform documentation.
- No physical-device or Raspberry Pi 5 / Home Assistant OS validation has been completed.
