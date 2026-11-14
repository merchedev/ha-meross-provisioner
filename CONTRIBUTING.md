# Contributing

Thanks for helping make Meross onboarding safer and easier to understand.

## Before opening a change

1. Read [`AGENTS.md`](AGENTS.md), the [architecture](docs/architecture.md), and the relevant hardware/protocol notes.
2. Open an issue or discussion for changes that affect the setup workflow, supported devices, host networking, or required Supervisor permissions.
3. Never attach Wi-Fi passwords, Meross account credentials, device keys, HomeKit setup codes, Supervisor tokens, or unredacted packet captures.

## Code and tests

- Keep protocol logic independent of Home Assistant and the Supervisor.
- Keep host operations behind a platform adapter so alternative platforms can be added without duplicating the workflow.
- Prefer type hints, small functions, explicit errors, and tests over comments that repeat the code.
- Add a regression test for every bug fix. Hardware-free tests must be the default; live-device tests are opt-in and documented.
- Update compatibility documentation when a model, firmware, OS, adapter, or AP app is tested.
- When changing the app version, add a user-facing entry to `meross_provisioner/CHANGELOG.md` and keep the app translations and `DOCS.md` in sync.
- When changing the app version, add a user-facing entry to `meross_provisioner/CHANGELOG.md` and keep the app translations and `DOCS.md` in sync.

Run the checks listed in [`AGENTS.md`](AGENTS.md) before submitting a pull request. Pull requests should describe the hardware and software versions used for any physical test.

## Hardware testing

Only test devices you own or have permission to configure. A provisioning test changes the device's Wi-Fi and interrupts the selected AP app. Back up the AP app settings first, keep Ethernet connected, and have the recovery procedure available. Never run hardware tests in automated CI.
