# Hardware and platform support

Compatibility is a property of the complete combination: device model/revision/firmware, host OS, Wi-Fi driver, AP app, and network topology. A successful compile is not evidence of hardware compatibility.

## Current support status

| Platform / hardware | Status | Requirements and limitations |
| --- | --- | --- |
| Raspberry Pi 5, Home Assistant OS, Ethernet + internal Wi-Fi | **Target; not hardware-verified** | Ethernet must remain connected. The app uses host D-Bus/NetworkManager to temporarily claim `wlan0` after the AP app stops. The exact AP app must restore its SSID/DHCP settings when restarted. |
| Other Home Assistant OS hardware | **Not tested** | Needs a NetworkManager-visible wireless device, host D-Bus access, a working station mode, and a supported AP app lifecycle. |
| Home Assistant Supervised | **Planned / not tested** | Requires Supervisor API access, host D-Bus, and NetworkManager behavior equivalent to the HAOS backend. |
| Home Assistant Container / Core | **Not supported by the first adapter** | No Supervisor app API or host D-Bus integration. A separate, narrowly scoped Linux backend is required. |
| Simultaneous AP + station on one radio | **Not required** | The initial workflow stops the AP app first. If the AP must remain online, the adapter/driver must support concurrent mode and channel constraints; otherwise use another Wi-Fi adapter. |

## Host hardware checks

The platform adapter should check these conditions before changing anything:

1. The selected interface exists and is reported as wireless.
2. A wired management interface is connected, or the user has explicitly configured another independent management path.
3. The AP app slug exists and is currently running.
4. The AP app owns the selected Wi-Fi interface and can be stopped/restarted by the Supervisor.
5. Provisioner can identify profiles that could autoconnect to the AP interface. It temporarily disables their autoconnect, restores it afterwards, creates its own UUID-identified temporary profile, and never deletes other profiles.
6. The target SSID is visible to the device and uses supported 2.4 GHz Wi-Fi security.
7. The Meross setup network and the Ethernet LAN do not create an ambiguous route to the Meross setup gateway (commonly `10.10.10.1`).
8. The Ingress proxy source address matches `ingress_peer_ip` in app options (default `172.30.32.2`).

If any condition cannot be established, the app should refuse to provision and explain what to check. It must not try privileged shell commands as a fallback.

## Device support

The project begins with a protocol discovery step, not a blanket device claim. Each tested entry should record:

- Full model code and region suffix, without publishing serial numbers or QR codes.
- Hardware and firmware version returned by the device.
- Setup transport used (SoftAP, BLE, or other).
- Whether Wi-Fi-only setup works without a Meross account/cloud contact.
- Whether Home Assistant's native HomeKit Device integration discovers it afterwards, if applicable.
- Test date and HAOS/Supervisor/AP app versions.

MSS210, MSS425FC, and MSL430 are initial test targets only. The current code must not label a model as tested until a physical test report has been added.
