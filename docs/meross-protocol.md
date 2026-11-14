# Meross setup protocol notes

These notes describe only the local setup-mode flow needed by this project. They are based on public community documentation and open-source tools, not on a claim that every Meross firmware behaves identically.

## SoftAP flow

Many Meross Wi-Fi devices enter a temporary, usually open, access-point mode after a hardware reset/commissioning action. The setup client joins that AP and sends JSON messages to the device's local `/config` HTTP endpoint, commonly `http://10.10.10.1/config`.

The documented protocol uses a packet with `header` and `payload` objects. The header carries fields such as `method`, `namespace`, `messageId`, `timestamp`, `payloadVersion`, and `sign`. In setup mode, some observed firmware does not validate the signature, but all required header fields should still be present. Firmware differences must be tested.

The main operations used by this project are:

| Namespace | Method | Purpose |
| --- | --- | --- |
| `Appliance.System.All` | `GET` | Read model, firmware, UUID, and MAC address before writing configuration. |
| `Appliance.Config.WifiList` | `GET` | Read Wi-Fi networks visible to the Meross device, including BSSID/channel/security metadata. |
| `Appliance.Config.Wifi` | `SET` | Set the selected Wi-Fi network. The device normally reboots after accepting it. |

The embedded setup HTTP server can become reachable a few seconds after DHCP completes. The client therefore retries only the read (`GET`) requests with a bounded delay and closes each HTTP connection after the response. A failed `SET` is not retried automatically, because the device may have accepted it before the connection failed.

The scan response is firmware-dependent: hidden networks can appear with an empty SSID, some builds report SSIDs as plain text or NUL-padded fields, and older firmware uses hyphen-separated BSSIDs. The parser skips entries that cannot be provisioned, accepts both SSID encodings, and sends the BSSID back in the separator format the device reported.

When the target is the access point managed by Provisioner, that AP is stopped while the device is being configured, so it cannot appear in the device's scan. In that case the workflow uses the AP app's saved SSID/channel, the Wi-Fi interface MAC as the BSSID, and the observed WPA2 security values (`cipher=3`, `encryption=6`). The AP app's passphrase is not used or retained; the user supplies the target password. Hidden target APs are rejected because setup firmware cannot discover them reliably.

`Appliance.Config.Key` is intentionally not part of the initial flow. It is associated with the Meross MQTT endpoint/account or a private MQTT setup and is not needed for the Wi-Fi-only provisioning attempt. Device-control keys and MQTT binding are a separate project decision.

The app makes no Meross cloud requests, but omitting `Appliance.Config.Key` is not proof that every device firmware stays offline after joining Wi-Fi. Record observed network behavior per model/firmware. Do not claim strict cloud isolation until it has been verified or enforced by the user's network policy.

## Credential encoding and transport security

The documented Wi-Fi payload encodes the SSID and password as Base64. Base64 is reversible encoding, not encryption. The local setup AP/HTTP exchange must therefore be treated as plaintext. The UI must clearly disclose this and the implementation must never log or persist the password.

The Wi-Fi scan response also commonly encodes SSIDs as Base64. The exact BSSID, channel, cipher, and encryption values returned by the device should be reused when building the Wi-Fi `SET` request instead of guessed constants.

## BLE

Some Meross models support BLE commissioning. The public `Fabi019/MerossBLE` project lists MSS210 and MSS425FC among its expected devices, but this project has not independently verified those models or their revisions. MSL430 is not in that project's published support list. BLE will be a separate transport adapter, not an assumption in the SoftAP implementation.

## References

- [bytespider/Meross utilities](https://github.com/bytespider/Meross)
- [MerossIot device pairing notes](https://github.com/albertogeniola/MerossIot/wiki/Device-pairing)
- [Meross protocol inspection](https://albertogeniola.github.io/MerossIot/meross-protocol.html)
- [Fabi019/MerossBLE](https://github.com/Fabi019/MerossBLE)

These projects have different licenses. This repository documents the protocol at a high level and does not copy their source code. Check licenses before reusing any implementation.
