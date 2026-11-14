# Hardware and platform support

Compatibility is a property of the complete combination: device model/revision/firmware, host OS, Wi-Fi driver, AP app, and network topology. A successful compile is not evidence of hardware compatibility.

## Current support status

| Platform / hardware | Status | Requirements and limitations |
| --- | --- | --- |
| Raspberry Pi 5, Home Assistant OS, Ethernet + internal Wi-Fi | **First successful Wi-Fi-only provisioning; still experimental** | MSS210 US firmware 4.2.9, November 2026. Ethernet stayed connected. The app used host D-Bus/NetworkManager to temporarily claim `wlan0` after the AP app stopped. The AP app restored its SSID/DHCP settings. |
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
6. The target SSID uses supported 2.4 GHz Wi-Fi security. It is either visible to the device or is the configured AP itself, whose SSID, channel, visibility, and interface MAC can be read before that AP is stopped. If the channel or MAC is unavailable, a minimal SSID/password profile may be attempted, but full metadata is preferred. Hidden target APs are not supported.
7. The Meross setup network and the Ethernet LAN do not create an ambiguous route to the Meross setup gateway (commonly `10.10.10.1`).
8. The Ingress proxy source address matches `ingress_peer_ip` in app options (default `172.30.32.2`).

If any condition cannot be established, the app should refuse to provision and explain what to check. It must not try privileged shell commands as a fallback.

## Verified test records

### MSS210 US, firmware 4.2.9 (2026-11-14)

- Platform: Raspberry Pi 5, Home Assistant OS, Ethernet management, internal Wi-Fi running a compatible access-point app on `wlan0`.
- AP: 2.4 GHz channel 1, WPA2, SSID restored automatically after provisioning.
- Device: MSS210 US, firmware 4.2.9, Wi-Fi-only setup. No Meross account, `Appliance.Config.Key`, or MQTT binding was configured.
- Result: Provisioner stopped the AP, scanned and selected the setup AP, joined it, read the device identity/Wi-Fi list, sent `Appliance.Config.Wifi`, and restored the AP. After the reboot the device associated to the target AP and completed the WPA 4-way handshake.
- Local control: the device was added to Home Assistant with the Meross LAN HACS integration over HTTP using its DHCP reservation. No Meross cloud account was used.
- LED: the device kept blinking green even though local HTTP control worked; this is consistent with the “connected but unbound” state. The Meross LAN DND/LED entity could disable the LED, at the cost of losing the visual status.
- Not verified: local MQTT binding, MSS425FC, MSL430, other firmware revisions, and long-term stability.

## Device support

The project begins with a protocol discovery step, not a blanket device claim. Each tested entry should record:

- Full model code and region suffix, without publishing serial numbers or QR codes.
- Hardware and firmware version returned by the device.
- Setup transport used (SoftAP, BLE, or other).
- Whether Wi-Fi-only setup works without a Meross account/cloud contact.
- Whether Home Assistant's native HomeKit Device integration discovers it afterwards, if applicable.
- Test date and HAOS/Supervisor/AP app versions.

MSS210 US firmware 4.2.9 now has a verified Wi-Fi-only provisioning record. MSS425FC and MSL430 remain initial test targets only. The current code must not label a model as tested until a physical test report has been added.
