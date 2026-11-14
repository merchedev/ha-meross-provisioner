# After provisioning

This guide starts when Meross Provisioner reports that the device acknowledged its Wi-Fi configuration and is restarting. Provisioner only configures Wi-Fi; device control is handled by Home Assistant integrations.

## 1. Confirm the access point is back

Provisioner restores the configured AP app in its recovery step. Check that:

- The AP SSID (for example `HA-AP`) is visible again.
- Home Assistant is still reachable over Ethernet.
- The AP app state is `started` in Home Assistant.

If the AP did not return, open the AP app page in Home Assistant and start it. The Provisioner transaction journal and app logs contain the recovery result.

## 2. Find the device address

Wait 30–60 seconds after the device reboots, then check the AP app's DHCP leases or its log for a `DHCPACK` entry for the device MAC shown in the Provisioner result.

- A DHCP reservation in the AP app makes the address stable.
- You can test reachability from the Home Assistant host with `ping <device-ip>`.
- If the AP app has DHCP disabled, the device cannot obtain an address unless another DHCP server serves that network. Enable DHCP or use a reservation.

## 3. Add the device to Home Assistant

### HomeKit Device

If the model supports HomeKit, Home Assistant may discover a **HomeKit Device**. Add it with the setup code printed on the device label. Never publish that code.

### Meross LAN (local HTTP)

For models without HomeKit, the recommended local option is [Meross LAN](https://github.com/krahabb/meross_lan), a HACS custom integration. It can talk to the device over local HTTP without a Meross account.

1. Install **Meross LAN** from HACS (not the official **Meross** integration).
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration → Meross LAN**.
4. Choose the manual device option. Do not choose the MQTT hub or the Meross cloud account.
5. Enter the device IP address.
6. Leave the device key empty and let Meross LAN try the local key fallback. In the verified setup, entering any key caused an invalid-key error.
7. Set the protocol to **HTTP** (or leave it on Auto) to keep normal control local.

If Meross LAN reports an invalid key or cannot add the device, restart the Hass.io Access Point app first. Wait for the device to reassociate and obtain its DHCP lease, then add it again with the IP and an empty key. This order was required in the verified setup.

The official **Meross** integration in Home Assistant Core uses the Meross cloud account. It is not required for local control and is not the integration described here.

## 4. Understand the LED

The LED reflects the device firmware state, not only the relay state.

| LED | Meaning |
| --- | --- |
| Solid amber | Initializing or firmware upgrade |
| Alternating amber/green | Ready to pair |
| Fast flashing green | Connecting to Wi-Fi |
| Solid green | Connected to Wi-Fi / paired |
| Blinking green after provisioning | Usually connected to Wi-Fi but not bound to Meross cloud/MQTT |
| Solid red | No internet connection |
| Off | No power or LED disabled |

Provisioner intentionally does not send `Appliance.Config.Key` or complete a Meross cloud/MQTT binding. On some firmware, the device therefore stays in the “connected but unbound” state and keeps blinking green even though local HTTP control works.

This behavior is model/firmware-dependent. In the verified setup, the MSS210 US kept blinking green, while the MSS425FC and MSL430 did not keep blinking after provisioning. Do not treat the LED alone as proof that provisioning failed; check the DHCP lease and local control first.

Meross LAN exposes a **DND / LED** entity for many plugs. Turning it off/on disables the status LED. In Meross LAN the DND logic is inverted relative to the Meross app, so test both positions. Disabling the LED also removes the visual on/off indication.

## 5. Optional: local MQTT binding for normal LED behavior

A device that is bound to a local MQTT broker should leave the unbound state and behave like a normally paired device, including its LED indication. This is optional, advanced, and not implemented by Provisioner. It has not been hardware-verified by this project.

At a high level:

1. Configure Mosquitto with a TLS listener on port 8883 and a certificate whose CN/SAN matches the broker address (for example the AP gateway `192.168.99.1`).
2. Meross devices use a MAC-shaped MQTT username containing `:`, which the Home Assistant Mosquitto authentication plugin does not accept. A dedicated listener with `allow_anonymous true` is the common workaround. Restrict that listener to the IoT/AP network with firewall rules where possible.
3. In Meross LAN, open the device → **Configure** → **Wifi/MQTT binding**.
4. Leave the Wi-Fi fields empty if the device is already on the target network.
5. Set the new broker address to the reachable TLS endpoint, for example `192.168.99.1:8883`.
6. Leave the device key and user ID empty to keep the current values, unless the Meross LAN MQTT hub uses a specific key.
7. Run the broker compatibility check, submit, and watch the Mosquitto and Meross LAN logs for the `Appliance.Control.Bind` exchange.
8. After binding, the device should reconnect to the local broker and the LED should leave the unbound state.

Binding failures can leave the device needing a factory reset and a new provisioning attempt. Treat this as an advanced experiment, not part of the supported provisioning flow.

## 6. Further reading

- [Troubleshooting and FAQ](troubleshooting.md)
- [Architecture and workflow](architecture.md)
- [Meross setup protocol notes](meross-protocol.md)
- [Hardware and platform support](platform-support.md)
