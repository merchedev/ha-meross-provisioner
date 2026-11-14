# Home Assistant OS on Raspberry Pi 5

This is the initial target, not yet a verified installation guide. Do not use the prototype on a production system until the recovery test below has passed.

## Intended network layout

- `eth0`: wired LAN and internet; keeps the Home Assistant UI and Supervisor reachable.
- `wlan0`: dedicated to the configured Home Assistant access-point app, normally advertising `HA-AP`.
- The Meross device: physically placed in setup mode and advertising its temporary setup AP.

The app temporarily stops the configured AP app, suspends autoconnect on saved profiles that could claim `wlan0`, asks NetworkManager over host D-Bus to manage it, scans and connects to one selected Meross AP, configures the device to join the target SSID, removes only its UUID-identified temporary profile, restores the suspended autoconnect settings, marks the interface unmanaged again, and restarts the AP app. Wi-Fi clients may be offline during this transaction and should reconnect afterwards.

## Before installation

1. Confirm Home Assistant is reachable over Ethernet, not only through `HA-AP`.
2. Back up the access-point app's configuration. Record its SSID, channel, DHCP range, and internet-routing setting.
3. Confirm the exact AP app supports stopping and starting through Supervisor and reuses its saved configuration on start.
4. Confirm the Wi-Fi interface is dedicated to that AP app. If NetworkManager reports saved profiles that could autoconnect, Provisioner temporarily disables their autoconnect and restores it after the transaction.
5. Make `HA-AP` visible on 2.4 GHz and use a WPA/WPA2 passphrase of 8–63 bytes. The Meross device must see that SSID during its own Wi-Fi scan.
6. Check that the wired LAN is not using the Meross setup subnet (commonly `10.10.10.0/24`). Overlapping subnets can route setup traffic incorrectly.
7. Test with one non-critical Meross device, not the entire collection.

## Local repository development

To test a local checkout, place the `meross_provisioner/` app directory under Home Assistant's local add-on directory (`/addons/local/meross_provisioner/`) using a method you already use to manage HAOS files. The repository root is not itself an app. Refresh the local add-on repository in **Settings → Add-ons → Add-on Store**, then install the app.

Configure:

- `wifi_interface`: use the interface configured in Hass.io Access Point (normally `wlan0` on the Pi). Provisioner checks it with NetworkManager over host D-Bus, even though the AP app marks it unmanaged.
- `access_point_addon_slug`: the actual Supervisor slug of the AP app, not just its display name.
- `ingress_peer_ip`: normally `172.30.32.2`; change it only if the Supervisor's internal address differs.

The app requests the Supervisor `manager` role to stop/start the AP app and host D-Bus access for NetworkManager. Review the source and permissions before enabling it.

## First test sequence

1. Open the app through the Home Assistant sidebar while connected over Ethernet.
2. Run preflight. It must identify the wired connection, wireless interface, and selected AP app before allowing a scan.
3. Confirm the temporary AP interruption. Verify that the AP stops and the app still responds over Ethernet.
4. Put exactly one Meross device in setup mode and scan. The setup AP is not authenticated by this protocol; configure in a controlled location and select the AP that belongs to the device you just reset.
5. Enter the target SSID and password in the UI. They are sent only for this operation; do not paste them into logs or issues.
6. Confirm the displayed model/firmware before accepting the Wi-Fi write.
7. Verify that the AP app was restored and its original SSID/DHCP settings are active. Then confirm the device appears in the AP's DHCP leases.
8. Add it to Home Assistant using the appropriate local integration.

Stop testing immediately if the AP app fails to restore. Since HA is wired, use the normal Home Assistant UI to start it again. Do not attempt to repair host networking with unreviewed shell commands.

## Static DHCP reservations

The Meross device should use DHCP on `HA-AP`. Reserve its address in the AP add-on's DHCP configuration using the device MAC, for example:

```text
dhcp-host=AA:BB:CC:DD:EE:FF,192.168.99.20
```

Choose an unused address inside the AP subnet and follow the syntax of the AP add-on you actually use. This is a DHCP reservation, not a static IP configured on the Meross device.

## Recovery checklist

- Confirm `eth0` still has network access and reload Home Assistant over its wired address.
- In **Settings → Add-ons**, start the AP app selected in Meross Provisioner.
- Check the AP app's own logs and confirm `HA-AP` and DHCP are running.
- If the Wi-Fi interface remains in station mode, do not run another provisioning operation. Use the AP app's normal documented recovery steps and report the redacted logs plus the exact OS/AP app versions.
- After recovery, remove any temporary Meross SSID profile through supported Home Assistant network controls if one remains. Never post Wi-Fi passwords or QR codes in a bug report.
