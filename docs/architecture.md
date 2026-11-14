# Architecture

## Scope

Meross Provisioner configures the Wi-Fi profile of a Meross device while that device is in its own setup mode. It does not implement normal device control, account sign-in, firmware updates, or cloud access.

The initial deployment is a Home Assistant OS app with an Ingress UI. The transport/protocol and provisioning workflow are kept independent from the Supervisor adapter so other Linux-based deployments can be added without copying protocol code.

## Components

### Domain and protocol (`src/meross_provisioner`)

- `meross_protocol.py` builds and validates setup-mode messages and decodes device identity/Wi-Fi scan responses.
- `models.py` contains typed, platform-independent values.
- `workflow.py` coordinates discovery, user confirmation, provisioning, and recovery through small adapter protocols.
- No module in this layer knows about Home Assistant, Docker, NetworkManager, or the Supervisor.

### Home Assistant platform adapter

- `supervisor.py` uses the documented Supervisor REST API for interface discovery, Wi-Fi scans, temporary station configuration, and app lifecycle operations.
- The ingress web app exposes preflight, scan, provision, job status, and cancel operations.
- The selected AP app is configured by slug. Its state is recorded before stopping it and it is restarted only if it was running when the workflow began.

### User interface

The UI is served through Home Assistant Ingress. It requires an explicit confirmation before stopping the AP app. The target SSID and password are submitted only with the provisioning request; the password is not saved in app options, browser storage, the transaction journal, or logs.

The web service accepts requests only from the Supervisor's internal Ingress proxy (`172.30.32.2`) and does not expose a host port. Keep this restriction when adding deployment adapters.

## Provisioning lifecycle

1. **Preflight:** verify Supervisor access, the configured wireless interface, the selected AP app, and a connected wired interface that keeps Home Assistant reachable.
2. **Confirm and pause:** the user confirms the outage; save a non-secret recovery journal, then stop the AP app.
3. **Discover:** ask the Supervisor to scan for nearby networks and show the result in the UI. A short-lived session keeps the AP app stopped while the user selects one Meross setup network.
4. **Connect:** temporarily configure the selected wireless interface as a client of that setup network. Keep the wired interface as the preferred route.
5. **Inspect:** query device identity and the network list. Do not write Wi-Fi settings if the target network is not found or the device is unsupported.
6. **Configure:** send only the target Wi-Fi configuration. Do not send Meross cloud/MQTT account keys.
7. **Restore:** remove only the temporary wireless profile created for this transaction, then restart the AP app. Report both the device result and any recovery warning.

The transaction must always have a timeout, a cancel operation, and a startup recovery path. The journal must never contain passwords, device keys, or raw request bodies.

## Network profile safety

The legacy Supervisor network API updates an interface's active NetworkManager profile; it does not provide a transaction-scoped profile handle. Its `enabled: false` behavior can delete the stored profile. Therefore, a platform adapter must not assume it can safely undo arbitrary user networking state.

For the initial HAOS/AP-app target, hardware testing must establish that the selected Wi-Fi interface is dedicated to the AP app and has no separate persistent station profile that needs preservation. If that cannot be established through the available API or explicit user confirmation, fail closed. Do not silently delete an existing Wi-Fi profile.

The AP app may manage the interface outside NetworkManager. The exact stop/restart behavior must be verified for each supported AP app and release. Unknown AP app implementations are not automatically supported just because their slug can be configured.

## Future platform adapters

Potential adapters include:

- Home Assistant Supervised, if it exposes the required Supervisor and host-network APIs.
- A Linux host using a narrowly scoped NetworkManager/D-Bus backend.
- BLE setup transport for devices that expose a compatible Meross BLE commissioning service.

Each adapter must declare what it can do, run its own preflight, and provide the same recovery guarantees. The core workflow must not acquire platform-specific shell commands or credentials.
