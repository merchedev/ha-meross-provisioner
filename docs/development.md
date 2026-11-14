# Development and testing

## Local environment

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Run checks:

```sh
python -m pytest
ruff check .
ruff format --check .
mypy meross_provisioner/src
```

## Test boundaries

- Protocol tests use synthetic, redacted JSON responses. They must not contain credentials from a real device.
- Workflow tests use fake Supervisor and device adapters. They verify AP stop/restore, timeout, cancellation, error recovery, and that secrets never enter the journal.
- CI must not scan a real network, contact `10.10.10.1`, or stop any service.
- Hardware testing is manual and opt-in. Record exact model/firmware, Pi/adapter, HAOS/Supervisor, AP app versions, and results, but redact MAC addresses if the owner prefers.

## Adding a platform

Implement the small platform protocols consumed by `workflow.py`. A platform adapter is responsible for preflight, interface switching, and safe cleanup. It must not contain Meross payload construction. Add adapter tests and update [platform support](platform-support.md) before claiming support.

## Adding a device transport

Implement a transport behind the device protocol interface. Add synthetic protocol fixtures and model/firmware-specific tests. BLE support must be optional and must fail with a clear message when the host has no compatible Bluetooth adapter/service.

## Local Home Assistant app build

The app directory contains its own Dockerfile and manifest. Home Assistant builds the app image from that directory for the selected architecture. The Python package is also installable from the repository root for fast unit testing.
