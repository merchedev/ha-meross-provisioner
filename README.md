# Meross Provisioner for Home Assistant

**Status: experimental prototype. Wi-Fi-only provisioning is verified on MSS210 US firmware 4.2.9, MSS425E, MSS425FC, and MSL430 over Home Assistant OS and a Raspberry Pi 5 (November 2026). Firmware versions for the MSS425E/MSS425FC/MSL430 were not recorded; other firmware remains unverified.**

Meross Provisioner is a Home Assistant app that aims to place a Meross device on a chosen Wi-Fi network without the Meross mobile app or Meross cloud. It uses a local connection to a device in setup mode, then asks Home Assistant's Supervisor to restore the configured access-point app.

The initial target is a wired Home Assistant OS installation with a dedicated Wi-Fi interface running a compatible access-point app. A provisioning attempt temporarily interrupts that AP. The wired connection keeps the Home Assistant UI available. The target can be that same AP: Provisioner reads its saved SSID/channel metadata before the outage, sends the configuration, and restores it afterwards.

Provisioner only configures Wi-Fi. After the device joins the network, use Home Assistant's **HomeKit Device** integration when supported, or the [Meross LAN](https://github.com/krahabb/meross_lan) HACS integration for local HTTP control. The official **Meross** integration uses the cloud and is not required for local control. Leave the Meross LAN device key empty; if adding the device fails, restart the AP app first and wait for the device to reconnect. See [After provisioning](docs/post-provisioning.md) for the full sequence, LED behavior, and the optional local MQTT binding path.

> This is an independent community project and is not affiliated with Meross. It does not control devices. After provisioning, use Home Assistant's HomeKit Device integration when supported, or the [Meross LAN](https://github.com/krahabb/meross_lan) HACS integration over local HTTP. In the verified setup, the Meross LAN device key had to be left empty. See [After provisioning](docs/post-provisioning.md).

## Important limitations

- The Wi-Fi credentials are sent to the Meross setup AP over local HTTP. Base64 encoding is **not encryption**. Use a unique IoT network password and only provision while physically present.
- The app itself makes no Meross cloud requests and does not send `Appliance.Config.Key`. That does not prove the device firmware will never contact vendor servers after joining Wi-Fi; verify the exact firmware and apply router/AP egress rules if cloud isolation is required.
- The app needs the Supervisor `manager` role to stop/start the AP app and host D-Bus access for NetworkManager control. These are powerful permissions; review the security notes before installing.
- The ingress peer defaults to `172.30.32.2`. Change `ingress_peer_ip` in app options only if your Home Assistant Supervisor uses a different internal address.
- The current code is a prototype. Do not use it where the AP app cannot safely release and restore the Wi-Fi interface. Provisioner journals recovery metadata and restores any autoconnect setting it temporarily changes.
- The selected interface must be dedicated to the AP app. Profiles that could autoconnect to it have their autoconnect temporarily disabled and restored when provisioning ends.
- The Pi 5's built-in radio worked as a station after the AP app stopped in the verified runs. The same interaction must still be validated for other AP apps and drivers; no AP+station concurrency is assumed.
- Wi-Fi-only provisioning has been verified on MSS210 US firmware 4.2.9, MSS425E, MSS425FC, and MSL430. Firmware versions for the last three were not recorded. See the compatibility matrix.

## Repository contents

- `AGENTS.md` — coding-agent rules and safety requirements.
- `meross_provisioner/` — Home Assistant app, ingress UI, protocol and platform code.
- `meross_provisioner/CHANGELOG.md` — version notes shown in Home Assistant's update dialog.
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

## Future work

- Record firmware versions for the verified MSS425E, MSS425FC, and MSL430 units.
- Hardware-test additional models and firmware revisions.
- Add optional post-provisioning reachability/DHCP verification in the UI.
- Evaluate a supported local MQTT binding path for users who want normal LED behavior and full cloud isolation.
- Investigate BLE commissioning for models that do not expose a usable setup AP.
- Validate other access-point apps, drivers, and HAOS versions.

## Documentation

- [After provisioning](docs/post-provisioning.md)
- [Troubleshooting and FAQ](docs/troubleshooting.md)
- [Architecture](docs/architecture.md)
- [Meross setup protocol](docs/meross-protocol.md)
- [Hardware and platform support](docs/platform-support.md)
- [Home Assistant OS / Raspberry Pi 5 guide](docs/haos-rpi5.md)
- [Home Assistant app changelog](meross_provisioner/CHANGELOG.md)
- [Security](SECURITY.md)
- [Development and testing](docs/development.md)

## License

MIT. See [LICENSE](LICENSE). Meross is a trademark of its respective owner.
