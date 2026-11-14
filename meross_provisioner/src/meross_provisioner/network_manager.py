"""Narrow NetworkManager adapter for the unmanaged AP interface."""

from __future__ import annotations

import asyncio
import contextlib
import os
import re
import uuid

from .errors import NetworkManagerError
from .models import AccessPoint, WifiProfile

_FREQUENCY_RE = re.compile(r"^(\d+)")
_BSSID_RE = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
_WIFI_PROFILE_TYPES = {"802-11-wireless", "wifi"}


class NetworkManagerClient:
    """Run a small, allowlisted set of nmcli operations over host D-Bus."""

    def __init__(self, *, command_timeout: float = 25) -> None:
        self._command_timeout = command_timeout

    async def _run(self, *args: str, timeout: float | None = None) -> str:
        environment = os.environ.copy()
        environment["LANG"] = "C"
        environment["LC_ALL"] = "C"
        try:
            process = await asyncio.create_subprocess_exec(
                "nmcli",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=environment,
            )
        except FileNotFoundError as err:
            raise NetworkManagerError(
                "nmcli is not installed in the app image."
            ) from err
        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(), timeout or self._command_timeout
            )
        except TimeoutError as err:
            await _stop_process(process)
            raise NetworkManagerError("A NetworkManager command timed out.") from err
        except asyncio.CancelledError:
            await _stop_process(process)
            raise
        if process.returncode != 0:
            # nmcli errors can include network names. Keep the UI/log message generic.
            raise NetworkManagerError(
                f"NetworkManager command {args[0]!r} failed "
                f"(exit {process.returncode})."
            )
        return stdout.decode("utf-8", errors="replace").strip()

    async def get_device_info(self, interface: str) -> dict[str, str]:
        """Return the state of a Wi-Fi device, including `unmanaged` devices."""
        output = await self._run(
            "--terse",
            "--escape",
            "yes",
            "--fields",
            "DEVICE,TYPE,STATE",
            "device",
            "status",
        )
        for line in output.splitlines():
            fields = _split_nmcli_fields(line)
            if len(fields) < 3 or fields[0] != interface:
                continue
            if fields[1].casefold() not in _WIFI_PROFILE_TYPES:
                raise NetworkManagerError(
                    f"NetworkManager reports {interface!r} as a non-Wi-Fi device."
                )
            return {"interface": interface, "state": fields[2]}
        raise NetworkManagerError(
            f"NetworkManager does not list Wi-Fi interface {interface!r}."
        )

    async def find_autoconnecting_wifi_profiles(
        self, interface: str
    ) -> list[WifiProfile]:
        """Return Wi-Fi profiles that could autoconnect to this interface."""
        output = await self._run(
            "--terse",
            "--escape",
            "yes",
            "--fields",
            "NAME,UUID,TYPE",
            "connection",
            "show",
        )
        blocking: list[WifiProfile] = []
        for line in output.splitlines():
            fields = _split_nmcli_fields(line)
            if len(fields) < 3:
                continue
            name, connection_uuid, profile_type = fields[:3]
            if profile_type.casefold() not in _WIFI_PROFILE_TYPES:
                continue
            try:
                uuid.UUID(connection_uuid)
            except ValueError:
                raise NetworkManagerError(
                    "NetworkManager returned an invalid Wi-Fi profile ID."
                ) from None
            profile_interface = (
                await self._run(
                    "--get-values",
                    "connection.interface-name",
                    "connection",
                    "show",
                    "uuid",
                    connection_uuid,
                )
            ).strip()
            autoconnect = (
                await self._run(
                    "--get-values",
                    "connection.autoconnect",
                    "connection",
                    "show",
                    "uuid",
                    connection_uuid,
                )
            ).strip()
            if autoconnect.casefold() == "no":
                continue
            if profile_interface in {"", "--", interface}:
                blocking.append(
                    WifiProfile(
                        name=name or "unnamed profile",
                        connection_uuid=str(uuid.UUID(connection_uuid)),
                    )
                )
        return blocking

    async def set_profiles_autoconnect(
        self, connection_uuids: list[str], enabled: bool
    ) -> None:
        """Temporarily change autoconnect only for the identified profiles."""
        value = "yes" if enabled else "no"
        for connection_uuid in connection_uuids:
            try:
                parsed_uuid = uuid.UUID(connection_uuid)
            except ValueError as err:
                raise NetworkManagerError(
                    "A saved Wi-Fi profile has an invalid connection ID."
                ) from err
            await self._run(
                "connection",
                "modify",
                "uuid",
                str(parsed_uuid),
                "connection.autoconnect",
                value,
            )

    async def set_managed(self, interface: str, managed: bool) -> None:
        """Allow or release an interface from NetworkManager control."""
        await self._run(
            "device",
            "set",
            interface,
            "managed",
            "yes" if managed else "no",
        )

    async def scan_access_points(self, interface: str) -> list[AccessPoint]:
        """Scan nearby SSIDs with NetworkManager after the AP app is stopped."""
        output = await self._run(
            "--terse",
            "--escape",
            "yes",
            "--fields",
            "SSID,BSSID,FREQ,SIGNAL,MODE",
            "device",
            "wifi",
            "list",
            "ifname",
            interface,
            "--rescan",
            "yes",
            timeout=35,
        )
        access_points: list[AccessPoint] = []
        for line in output.splitlines():
            fields = _split_nmcli_fields(line)
            if len(fields) < 5:
                continue
            ssid, bssid, frequency, signal, mode = fields[:5]
            frequency_match = _FREQUENCY_RE.match(frequency)
            if not ssid or not _BSSID_RE.fullmatch(bssid) or not frequency_match:
                continue
            try:
                signal_value = int(signal)
                frequency_value = int(frequency_match.group(1))
            except ValueError:
                continue
            mode_value = {
                "infra": "infrastructure",
                "infrastructure": "infrastructure",
                "ad-hoc": "adhoc",
                "adhoc": "adhoc",
                "ap": "ap",
            }.get(mode.casefold(), mode.casefold())
            access_points.append(
                AccessPoint(
                    ssid=ssid,
                    mac=bssid,
                    frequency=frequency_value,
                    signal=signal_value,
                    mode=mode_value,
                )
            )
        return access_points

    async def create_open_connection(
        self, interface: str, ssid: str, bssid: str, connection_uuid: str
    ) -> None:
        """Create a uniquely identified, non-autoconnecting profile for one scan."""
        try:
            parsed_uuid = uuid.UUID(connection_uuid)
        except ValueError as err:
            raise NetworkManagerError(
                "The temporary NetworkManager profile ID is invalid."
            ) from err
        if not _BSSID_RE.fullmatch(bssid):
            raise NetworkManagerError("The selected setup AP has an invalid BSSID.")
        profile_name = f"meross-provisioner-{parsed_uuid.hex[:12]}"
        await self._run(
            "connection",
            "add",
            "type",
            "wifi",
            "ifname",
            interface,
            "con-name",
            profile_name,
            "ssid",
            ssid,
            "802-11-wireless.bssid",
            bssid,
            "802-11-wireless-security.key-mgmt",
            "none",
            "connection.uuid",
            str(parsed_uuid),
            "connection.autoconnect",
            "no",
            "ipv4.method",
            "auto",
            "ipv4.route-metric",
            "700",
            "ipv6.method",
            "auto",
            "ipv6.route-metric",
            "700",
        )

    async def activate_connection(self, interface: str, connection_uuid: str) -> None:
        """Activate the temporary open setup-AP profile and wait for DHCP."""
        await self._run(
            "--wait",
            "45",
            "connection",
            "up",
            "uuid",
            connection_uuid,
            "ifname",
            interface,
            timeout=55,
        )

    async def get_gateway(self, interface: str) -> str:
        """Read the gateway assigned to the temporary Wi-Fi connection."""
        output = await self._run(
            "--get-values",
            "IP4.GATEWAY",
            "device",
            "show",
            interface,
        )
        gateway = next(
            (line.strip() for line in output.splitlines() if line.strip()), ""
        )
        if not gateway:
            raise NetworkManagerError(
                "NetworkManager did not report an IPv4 gateway for the setup AP."
            )
        return gateway

    async def delete_connection(self, connection_uuid: str) -> None:
        """Delete only the unique temporary profile recorded in the journal."""
        try:
            parsed_uuid = uuid.UUID(connection_uuid)
        except ValueError as err:
            raise NetworkManagerError(
                "The journaled NetworkManager profile ID is invalid."
            ) from err
        all_uuids = await self._run(
            "--terse", "--get-values", "UUID", "connection", "show"
        )
        if str(parsed_uuid) not in {line.strip() for line in all_uuids.splitlines()}:
            return
        await self._run("connection", "delete", "uuid", str(parsed_uuid))


def _split_nmcli_fields(line: str) -> list[str]:
    """Split nmcli terse output, honoring escaped separators."""
    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for character in line:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            fields.append("".join(current))
            current.clear()
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    fields.append("".join(current))
    return fields


async def _stop_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        process.kill()
    await process.communicate()
