# Troubleshooting and FAQ

This page collects the symptoms observed during development and the first hardware test. Version references describe when a fix was introduced; check the installed version in the app page.

## General questions

### Does `HA-AP` come back after provisioning?

Yes. The workflow restores the configured AP app in its recovery step, even after an error or timeout. If the SSID is not visible, open the AP app page in Home Assistant and start it. Check the app and Supervisor logs if it fails repeatedly.

### Do I need the Meross app or a Meross account?

No for provisioning. Provisioner uses the device's local setup AP and local HTTP. For control, use HomeKit Device when supported or the Meross LAN HACS integration over local HTTP. A Meross account is only needed for cloud pairing or for retrieving a cloud-managed device key; this project does not require it.

### Does Provisioner control the device after setup?

No. It only configures Wi-Fi. Device control, entities, automations, and MQTT binding are handled by HomeKit Device or Meross LAN.

### Does the target AP need to be visible to the Meross device during provisioning?

No when the target is the same AP that Provisioner stops. The app reads the AP app's saved SSID/channel/visibility before the outage and uses that metadata. The AP must be visible again when the device reboots and tries to join.

### Can the target be a normal router SSID instead of `HA-AP`?

Yes, as long as the Meross device can see it during its own scan and it is a supported 2.4 GHz WPA/WPA2 network. In that case the app uses the device-reported BSSID/channel/security metadata.

## Scanning and NetworkManager

### “No Meross-looking setup AP was found”

The scan returned networks, but none matched the Meross setup AP prefix. Check that:

- The device is in **AP setup mode**, not only Bluetooth pairing mode. Follow the model's reset procedure.
- Only one device is in setup mode.
- The phone or tablet is disconnected from the Meross setup AP. Some devices only serve one configuration client.
- The setup AP is 2.4 GHz. The Meross setup radio is normally 2.4 GHz only.
- The device is physically close enough.

The error lists nearby SSIDs so you can distinguish “no networks at all” from “the Meross AP has an unexpected name”.

### “NetworkManager returned no Wi-Fi networks”

NetworkManager did not see any networks on the configured interface. Check that the interface name is correct (`wlan0` on most Pi installations), the AP app released the radio, and `wlan0` can scan. `nmcli device status` on the host should show the Wi-Fi device.

### “NetworkManager reports the Wi-Fi device as unavailable”

After hostapd stops, the interface can be administratively down. Provisioner enables the Wi-Fi radio and asks NetworkManager to manage the device. If the state remains unavailable, see the app log for the last state. A reboot of Home Assistant OS or the AP app can clear a stuck driver state.

### “NetworkManager command 'device' failed (exit 2)”

Older NetworkManager versions do not support some `nmcli device set` values. Provisioner uses the compatible `managed yes` form. If the error persists, include the full message in an issue; the app now reports the underlying `nmcli` error text.

### “Profile is not compatible with device (wpa_supplicant does not support WEP)”

The temporary setup profile was created with an empty security section, which NetworkManager interpreted as WEP. Since 0.1.12 the profile is a truly open network with no security section. Update the app and retry.

## Reaching the device

### “Home Assistant could not reach the Meross setup AP”

The temporary connection activated but the HTTP request to the device failed. Since 0.1.13 the app retries the initial reads for several seconds and closes each HTTP connection after the response. The error now includes the transport error class and errno.

- `ClientConnectorError, errno 113` or `101`: no route from the app container/host to the setup gateway. Check the temporary connection and the route to `10.10.10.1` (or the address reported by DHCP).
- `ServerTimeoutError` / `ConnectionTimeoutError`: the device accepted the connection but did not answer in time. Retry; the device may still be starting its HTTP endpoint.
- `ServerDisconnectedError`: the device closed the connection. This can indicate a firmware/protocol difference; include the model and firmware.

### “The device returned an empty or invalid SSID”

The device's Wi-Fi scan contained a hidden network with an empty SSID or a firmware-specific encoding. Since 0.1.14 the parser:

- Skips hidden or malformed entries instead of aborting the whole list.
- Accepts Base64, plain-text, and NUL-padded SSIDs.
- Accepts hyphen-separated BSSIDs from older firmware.

### “The Meross device cannot see the target SSID”

This is expected when the target is the AP that Provisioner just stopped (for example `HA-AP`). Since 0.1.15 the app reads the configured AP app's SSID, channel, and visibility before stopping it, and uses those saved values to configure the device even though the device cannot see the AP during provisioning. The AP is restored immediately afterwards.

If the message still appears:

- The target SSID must match the AP app's SSID exactly, including case.
- The AP app must be visible, not hidden.
- The AP must be 2.4 GHz.
- If the target is a different network, the device must be able to see it during the scan.

### “Provisioner could not read the AP app's channel and MAC”

Since 0.1.16 the app tries several sources for the interface MAC (`nmcli` get-values, terse output, Supervisor network data) and for the AP channel (app options and `hostapd_config_override`). If metadata is still missing, it sends a minimal Wi-Fi profile with SSID, password, and WPA2 security values, and says so in the result.

A minimal profile is not guaranteed to work on every firmware. If the device does not join, check:

- The AP app exposes `ssid`, `channel`, and `hide_ssid`.
- The interface MAC is available to NetworkManager.
- The target AP is visible.

## After the device accepts the configuration

### The device accepted but the LED still blinks green

The device is probably connected to Wi-Fi but not bound to Meross cloud/MQTT. Provisioner only configures Wi-Fi and intentionally does not send `Appliance.Config.Key` or complete the cloud binding. Local HTTP control can still work.

Options:

1. Leave it blinking; control works.
2. Use the Meross LAN DND/LED entity to turn the status LED off. This also removes the visual on/off indication.
3. Advanced: bind the device to a local MQTT broker so it leaves the unbound state. See [After provisioning](post-provisioning.md).

### The device connects and disconnects repeatedly

Check in this order:

1. **DHCP**: does the AP app have DHCP enabled? Does the device get a lease/reservation? A full pool or a reservation for the wrong MAC can prevent an address.
2. **WPA**: the AP log should show `EAPOL-4WAY-HS-COMPLETED` for the device MAC. If it fails, the target password does not match the AP passphrase.
3. **Channel**: channels 12 and 13 are not supported by some US devices. Prefer 1, 6, or 11.
4. **AP client isolation/internet access**: the device may need to reach the local broker or the Meross cloud. The AP app's client internet access setting controls NAT to the wired LAN.
5. **Binding**: a device that cannot complete its Meross binding may reboot periodically. Local MQTT binding is the advanced remedy.

### “Meross LAN only lets me add hubs and asks for my Meross account”

That is the official **Meross** integration or the Meross cloud/MQTT hub option, not local device control. Use the HACS integration [Meross LAN](https://github.com/krahabb/meross_lan):

- Install it from HACS and restart Home Assistant.
- Add **Meross LAN**, choose the manual device option, and enter the device IP.
- Leave the device key empty and let the local key fallback run.
- Set the protocol to HTTP if you want to force local control.

### The DND/LED entity turns the LED off, but then I lose the on/off light

That is how the device works. The LED has a single status light; it does not expose a separate “power only, no connection status” mode. Without a cloud/MQTT binding, the options are blinking or off. Normal LED behavior requires leaving the unbound state, normally through local MQTT binding.

## Known limitations

- Wi-Fi provisioning is verified on an MSS210 US with firmware 4.2.9. MSS425FC and MSL430 remain untested.
- Device control is not implemented by Provisioner. Use HomeKit Device or Meross LAN.
- The vendor firmware may still contact Meross cloud services after joining Wi-Fi. Omitting `Appliance.Config.Key` is not a guarantee of cloud isolation.
- Local MQTT binding is outside Provisioner and has not been hardware-verified by this project.
- Recovery behavior is tested with mocks and the first hardware run; unusual AP apps, drivers, or interrupted transactions may still require manual recovery.
