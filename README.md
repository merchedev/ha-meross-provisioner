# Meross Provisioner for Home Assistant

**Status: experimental prototype. Hardware provisioning has not yet been verified on a Raspberry Pi 5 / Home Assistant OS.**

Meross Provisioner is a Home Assistant app that aims to place a Meross device on a chosen Wi-Fi network without the Meross mobile app or Meross cloud. It uses a local connection to a device in setup mode, then asks Home Assistant's Supervisor to restore the configured access-point app.

The initial target is a wired Home Assistant OS installation with a dedicated Wi-Fi interface running a compatible access-point app. A provisioning attempt temporarily interrupts that AP. The wired connection keeps the Home Assistant UI available.

> This is an independent community project and is not affiliated with Meross. It does not control devices. After provisioning, use Home Assistant's HomeKit Device integration or a suitable local Meross integration. Non-HomeKit devices may need an additional local device key/integration setup; that is not implemented here.

## Important limitations

- The Wi-Fi credentials are sent to the Meross setup AP over local HTTP. Base64 encoding is **not encryption**. Use a unique IoT network password and only provision while physically present.
- The app itself makes no Meross cloud requests and does not send `Appliance.Config.Key`. That does not prove the device firmware will never contact vendor servers after joining Wi-Fi; verify the exact firmware and apply router/AP egress rules if cloud isolation is required.
- The Supervisor app needs the `manager` API role to scan/change host networking and stop/start another app. This is powerful access; review the security notes before installing.
- The ingress peer defaults to `172.30.32.2`. Change `ingress_peer_ip` in app options only if your Home Assistant Supervisor uses a different internal address.
- The current code is a prototype. Do not use it on a system whose Wi-Fi interface has a persistent network profile you need to keep. The initial implementation deliberately fails closed when it cannot establish safe cleanup conditions.
- The selected interface must be dedicated to the AP app. If the Supervisor reports a Wi-Fi profile on it, preflight refuses to continue; the API cannot safely snapshot that profile's secret and restore it.
- The Pi 5's built-in radio is expected to be usable as a station after the AP app stops, but the interaction between Home Assistant OS, NetworkManager, and a particular AP app must be tested. No AP+station concurrency is assumed.
- The project has not yet been tested with MSS210, MSS425FC, or MSL430 hardware. See the compatibility matrix.

## Repository contents

- `AGENTS.md` — coding-agent rules and safety requirements.
- `meross_provisioner/` — Home Assistant app, ingress UI, protocol and platform code.
- `docs/` — architecture, protocol notes, hardware support, security, and setup guides.
- `meross_provisioner/tests/` — hardware-free tests using fakes and protocol fixtures.

## Development

Requirements: Python 3.11+ and Git.

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest
ruff check .
ruff format --check .
mypy meross_provisioner/src
```

See [Development and testing](docs/development.md) before changing the code.

## Installing locally for development

This repository is structured as a Home Assistant add-on repository. On a Home Assistant OS test installation, add `https://github.com/merchedev/ha-meross-provisioner` to the Add-on Store, install **Meross Provisioner**, configure the Wi-Fi interface and AP app slug, and start the app. The Git SSH remote is used for publishing; the Add-on Store URL is HTTPS. Online installation requires the GitHub repository to be public. For an initial local test, install the repository as a local add-on repository following [the local development guide](docs/haos-rpi5.md).

Do not point a production Home Assistant installation at this experimental prototype. First follow the preflight and recovery instructions in the hardware guide.

## Documentation

- [Architecture](docs/architecture.md)
- [Meross setup protocol](docs/meross-protocol.md)
- [Hardware and platform support](docs/platform-support.md)
- [Home Assistant OS / Raspberry Pi 5 guide](docs/haos-rpi5.md)
- [Security](SECURITY.md)
- [Development and testing](docs/development.md)

## License

MIT. See [LICENSE](LICENSE). Meross is a trademark of its respective owner.
