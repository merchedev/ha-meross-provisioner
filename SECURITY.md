# Security policy

## Scope

This prototype changes a host Wi-Fi interface and temporarily stops/starts a Home Assistant app. It sends a target network's credentials to a Meross device in setup mode over local HTTP. The setup transport is not encrypted.

## Reporting a vulnerability

Please do not publish credentials, packet captures, or a working exploit in an issue. Until a dedicated security contact is configured, report security-sensitive findings privately to the repository owner through GitHub's private vulnerability reporting feature, if enabled. If it is unavailable, open a minimal issue asking for a private contact without including technical details.

## Security requirements

- No Meross cloud login or cloud endpoint is used.
- The target Wi-Fi password is accepted only for the active provisioning request, is not persisted, and must never appear in logs, error responses, job status, or test fixtures.
- Only a user-selected setup AP can receive configuration messages.
- Meross setup-mode AP identity is not cryptographically authenticated. Keep one owned device in setup mode at a time and verify the selected AP physically.
- The access point app is stopped only after an explicit confirmation in the Home Assistant UI.
- A transaction has timeouts, cancellation, and best-effort recovery. It must not silently leave the AP app stopped.
- The Supervisor `manager` role is required by the current platform adapter. The app must disclose this and must not request Docker API or unrestricted host access.
- To configure a device for the managed AP while that AP is stopped, the app reads the configured AP app's SSID, channel, hidden-SSID flag, and interface MAC. The AP app's passphrase and other option values are never retained, logged, displayed, or sent to the device; only the non-secret fields needed for the target profile are kept in the in-memory scan session.
- The app uses host D-Bus to ask NetworkManager to manage the dedicated Wi-Fi interface temporarily and to suspend/restore `connection.autoconnect` on profiles that could claim the radio. It does not request `host_network` or `NET_ADMIN`.
- Suspended profile UUIDs are journaled for recovery; profile contents and credentials are never copied. Existing profiles are never deleted.
- The web server accepts traffic only from the Supervisor Ingress proxy at `172.30.32.2`; do not expose or map the app's internal port.

## Known risks

- Meross setup mode uses local HTTP and Base64-encoded credentials. A nearby observer able to join/monitor the setup AP could recover the target Wi-Fi password.
- Supervisor manager permissions can affect host networking and other apps. Install only after reviewing the source and understanding the temporary AP outage.
- Recovery behavior is not hardware-verified yet. Treat the app as experimental until the exact Pi, HAOS, and AP add-on combination has passed the documented test plan.
