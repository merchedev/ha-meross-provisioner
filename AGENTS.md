# Instructions for AI coding agents

These instructions apply to the whole repository.

## Project goals and boundaries

- This project provisions owner-operated Meross devices onto a user-selected Wi-Fi network from Home Assistant. It must not require a Meross account or contact Meross cloud services.
- Keep device provisioning, Home Assistant/Supervisor integration, and device control as separate concerns. Do not reimplement device-control integrations that Home Assistant already provides.
- Treat protocol behavior as model- and firmware-dependent. Record observations and supported versions; do not turn an unverified guess into a compatibility claim.
- Never broaden the target from the explicitly selected device setup AP to arbitrary hosts or networks.

## Work practices

- Read the relevant documentation and tests before changing code.
- Keep changes focused. Do not reformat or rewrite unrelated files.
- Prefer small, composable functions and existing abstractions over duplicated logic.
- Add comments for non-obvious protocol, lifecycle, security, or compatibility decisions—not for self-explanatory code.
- Add or update tests for behavior changes, and update user-facing documentation whenever setup, permissions, compatibility, or recovery behavior changes.
- For every app version change, update `meross_provisioner/CHANGELOG.md`; Home Assistant reads the app-folder changelog for update dialogs. Keep translated option help and `DOCS.md` in sync with `config.yaml`.
- For every app version change, update `meross_provisioner/CHANGELOG.md`; Home Assistant reads the app-folder changelog for update dialogs. Keep translated option help and `DOCS.md` in sync with `config.yaml`.
- Do not delegate work to subagents unless the user explicitly requests delegation.
- Do not commit, push, publish releases, or change remote repository settings unless the user explicitly asks.

## Network and device safety

- Never run provisioning against a physical device unless the user has explicitly started that operation and confirmed the temporary access-point interruption.
- Treat real Wi-Fi credentials, device keys, HomeKit setup codes, tokens, and raw setup payloads as secrets. Never copy real values from a device or user into logs, commits, fixtures, or errors; tests may use clearly synthetic dummy values only.
- Do not persist the target Wi-Fi password. The device's local setup transport is not encrypted; explain this limitation and only send credentials to the explicitly selected Meross setup AP.
- Any operation that pauses the user's access point must have a bounded timeout, a cancellation path, and a `finally`/recovery path that attempts to restore the original service.
- Do not delete or overwrite an existing NetworkManager profile unless the operation has positively established that it is the temporary profile created by this app. If that cannot be established, fail safely and explain the limitation.
- Keep Supervisor permissions to the minimum supported role. Any permission needed to manage another app or the host network must be justified in the documentation and surfaced to the user.

## Validation

Before considering a change complete, run:

```sh
python -m pytest
ruff check .
ruff format --check .
mypy meross_provisioner/src
```

Hardware-dependent behavior must be marked as unverified until tested on real Home Assistant OS hardware. Tests in CI must use mocks or a local simulator and must not depend on a Meross account or live device.
