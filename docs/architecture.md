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

- `supervisor.py` uses the documented Supervisor REST API for Ethernet checks and AP-app lifecycle operations.
- `network_manager.py` uses `nmcli` over host D-Bus because the Hass.io Access Point app marks its Wi-Fi interface unmanaged, so it is absent from the Supervisor's interface list. Temporary profiles use app-generated UUIDs and only those profiles are deleted.
- The ingress web app exposes preflight, scan, provision, job status, and cancel operations.
- The selected AP app is configured by slug. Its state is recorded before stopping it and it is restarted only if it was running when the workflow began.
- Before stopping the AP app, the workflow reads its SSID, channel, hidden-SSID flag, and the Wi-Fi interface MAC. Only those non-secret fields are kept in the in-memory scan session; the AP app's passphrase is ignored.

### User interface

The UI is served through Home Assistant Ingress. It requires an explicit confirmation before stopping the AP app. The target SSID and password are submitted only with the provisioning request; the password is not saved in app options, browser storage, the transaction journal, or logs.

The web service accepts requests only from the Supervisor's internal Ingress proxy (`172.30.32.2`) and does not expose a host port. Keep this restriction when adding deployment adapters.

## Provisioning lifecycle

1. **Preflight:** verify Supervisor access, that NetworkManager sees the configured wireless device, the selected AP app, and a connected wired interface that keeps Home Assistant reachable. Profiles that could autoconnect are reported as warnings, not blockers.
2. **Confirm and pause:** the user confirms the outage; save a non-secret recovery journal, read the managed AP's non-secret SSID/channel/visibility and interface MAC, then stop the AP app.
3. **Discover:** temporarily suspend autoconnect on profiles that could claim the radio, mark the Wi-Fi device managed by NetworkManager, scan nearby networks with `nmcli`, and show the result in the UI. A short-lived session keeps the AP app stopped while the user selects one Meross setup network.
4. **Connect:** create a non-autoconnecting open Wi-Fi profile pinned to the selected AP's BSSID and identified by a generated UUID. Keep the wired interface as the preferred route.
5. **Inspect:** query device identity and the network list. Do not write Wi-Fi settings if the target network is not found and is not the managed AP, or the device is unsupported. If the target is the managed AP, it is normally absent from the device scan because that AP is stopped; use the saved SSID/channel/MAC metadata and the WPA2 security values instead. If the channel or MAC is unavailable, send a minimal SSID/password profile and mark the result accordingly. Reject hidden target APs.
6. **Configure:** send only the target Wi-Fi configuration. Do not send Meross cloud/MQTT account keys.
7. **Restore:** mark the Wi-Fi device unmanaged, remove only the temporary profile with the journaled UUID, restore autoconnect on the suspended profiles, then restart the AP app. Report both the device result and any recovery warning.

The transaction must always have a timeout, a cancel operation, and a startup recovery path. The journal must never contain passwords, device keys, or raw request bodies.

The first hardware run (MSS210 US, firmware 4.2.9) followed this lifecycle end to end. The target was the same AP that Provisioner stopped, so the device could not see it during provisioning; the workflow used the AP app's saved SSID/channel/MAC metadata and restored the AP immediately after the device acknowledged the write. Local control was then added with the Meross LAN HACS integration over HTTP. Device control, cloud binding, and local MQTT binding remain outside this project.

## Network profile safety

The AP app marks its device unmanaged while hostapd controls it. Provisioner temporarily asks NetworkManager to manage the device and suspends autoconnect on saved profiles that could claim the radio. It creates a new profile with a generated UUID, deletes only that profile during cleanup, and restores autoconnect on the suspended profiles. Existing profiles are never deleted and their other settings are not changed.

The exact interaction with the AP app must be verified for each supported app and release. It must stop cleanly, release hostapd's control, and restore its saved SSID/DHCP settings when restarted. Unknown AP apps are not automatically supported merely because their slug can be configured.

## Future platform adapters

Potential adapters include:

- Home Assistant Supervised, if it exposes the required Supervisor and host-network APIs.
- A Linux host using the NetworkManager/D-Bus adapter where the app has host bus access.
- BLE setup transport for devices that expose a compatible Meross BLE commissioning service.

Each adapter must declare what it can do, run its own preflight, and provide the same recovery guarantees. The core workflow must not acquire platform-specific shell commands or credentials.
