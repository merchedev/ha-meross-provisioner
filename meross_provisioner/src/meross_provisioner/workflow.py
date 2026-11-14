"""Safety-oriented provisioning transaction independent of the HA UI."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import secrets
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from .errors import (
    ConfigurationError,
    DeviceProtocolError,
    RecoveryError,
    SafetyCheckError,
    SessionError,
    SupervisorError,
    UnsupportedDeviceError,
)
from .journal import TransactionJournal
from .meross_protocol import is_supported_model
from .models import (
    AccessPoint,
    DeviceInfo,
    DeviceWifiNetwork,
    ProvisioningResult,
    ScanSession,
)

_LOGGER = logging.getLogger(__name__)
_BSSID_RE = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")
_TEMP_ROUTE_METRIC = 700


class SupervisorPort(Protocol):
    """Operations required from a host/platform adapter."""

    async def get_network_info(self) -> dict[str, Any]: ...

    async def get_interface_info(self, interface: str) -> dict[str, Any]: ...

    async def scan_access_points(self, interface: str) -> list[dict[str, Any]]: ...

    async def update_interface(
        self, interface: str, body: Mapping[str, Any]
    ) -> None: ...

    async def get_addon_info(self, slug: str) -> dict[str, Any]: ...

    async def get_addons(self) -> list[dict[str, Any]]: ...

    async def stop_addon(self, slug: str) -> None: ...

    async def start_addon(self, slug: str) -> None: ...

    async def restart_addon(self, slug: str) -> None: ...


class DevicePort(Protocol):
    """Protocol subset required from a Meross setup transport."""

    async def get_device_info(self) -> DeviceInfo: ...

    async def get_wifi_list(self) -> list[DeviceWifiNetwork]: ...

    async def set_wifi(self, network: DeviceWifiNetwork, password: str) -> None: ...


DeviceFactory = Callable[[str], DevicePort]


@dataclass(frozen=True, slots=True)
class WorkflowConfig:
    """Non-secret app configuration."""

    wifi_interface: str
    access_point_addon_slug: str
    session_timeout_seconds: int = 240


@dataclass(frozen=True, slots=True)
class PreflightReport:
    """Machine-readable preflight status presented by the ingress UI."""

    ready: bool
    wifi_interface: str
    wifi_interface_type: str | None
    ethernet_interface: str | None
    access_point_addon_slug: str
    access_point_addon_state: str | None
    current_wifi_mode: str | None
    issues: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "wifi_interface": self.wifi_interface,
            "wifi_interface_type": self.wifi_interface_type,
            "ethernet_interface": self.ethernet_interface,
            "access_point_addon_slug": self.access_point_addon_slug,
            "access_point_addon_state": self.access_point_addon_state,
            "current_wifi_mode": self.current_wifi_mode,
            "issues": list(self.issues),
            "warnings": list(self.warnings),
        }


class ProvisioningWorkflow:
    """Coordinate Wi-Fi discovery, one device write, and AP recovery."""

    def __init__(
        self,
        supervisor: SupervisorPort,
        device_factory: DeviceFactory,
        journal: TransactionJournal,
        config: WorkflowConfig,
    ) -> None:
        self._supervisor = supervisor
        self._device_factory = device_factory
        self._journal = journal
        self._config = config
        self._session: ScanSession | None = None
        self._session_lock = asyncio.Lock()
        self._expiry_task: asyncio.Task[None] | None = None
        self._busy = False

    @property
    def session_active(self) -> bool:
        return self._session is not None

    async def preflight(self) -> PreflightReport:
        """Check the wired management path and configured platform objects."""
        issues: list[str] = []
        warnings: list[str] = [
            "The configured Wi-Fi AP will be interrupted during scanning/provisioning.",
            (
                "Confirm this Wi-Fi interface is dedicated to the AP app and has "
                "no saved station profile to preserve."
            ),
            (
                "The device setup protocol sends Wi-Fi credentials over "
                "unencrypted local HTTP."
            ),
        ]
        if not self._config.wifi_interface.strip():
            issues.append("Set the wireless interface name in the app options.")
        if not self._config.access_point_addon_slug.strip():
            issues.append("Set the AP app's Supervisor slug in the app options.")
        if self._config.access_point_addon_slug == "meross_provisioner":
            issues.append("The AP app cannot be Meross Provisioner itself.")

        if issues:
            return PreflightReport(
                ready=False,
                wifi_interface=self._config.wifi_interface,
                wifi_interface_type=None,
                ethernet_interface=None,
                access_point_addon_slug=self._config.access_point_addon_slug,
                access_point_addon_state=None,
                current_wifi_mode=None,
                issues=tuple(issues),
                warnings=tuple(warnings),
            )

        try:
            network = await self._supervisor.get_network_info()
            interface = await self._supervisor.get_interface_info(
                self._config.wifi_interface
            )
            addon = await self._supervisor.get_addon_info(
                self._config.access_point_addon_slug
            )
        except SupervisorError as err:
            return PreflightReport(
                ready=False,
                wifi_interface=self._config.wifi_interface,
                wifi_interface_type=None,
                ethernet_interface=None,
                access_point_addon_slug=self._config.access_point_addon_slug,
                access_point_addon_state=None,
                current_wifi_mode=None,
                issues=(str(err),),
                warnings=tuple(warnings),
            )

        interfaces = network.get("interfaces", [])
        if not isinstance(interfaces, list):
            interfaces = []
        ethernet = next(
            (
                item
                for item in interfaces
                if isinstance(item, dict)
                and item.get("type") == "ethernet"
                and item.get("connected") is True
            ),
            None,
        )
        if ethernet is None:
            issues.append(
                "No connected Ethernet interface was found. Connect HA over "
                "Ethernet before switching its Wi-Fi."
            )

        interface_type = interface.get("type")
        if interface_type != "wireless":
            issues.append(
                f"Configured interface {self._config.wifi_interface!r} is not "
                "reported as wireless."
            )
        wifi_profile = interface.get("wifi")
        current_mode = (
            wifi_profile.get("mode") if isinstance(wifi_profile, dict) else None
        )
        if isinstance(wifi_profile, dict):
            issues.append(
                "The Supervisor reports an existing Wi-Fi profile. This prototype "
                "cannot safely snapshot and restore it, so it will not replace it."
            )

        addon_state = addon.get("state")
        if addon_state != "started":
            issues.append(
                "The configured AP app is not running; refusing a workflow "
                "that cannot restore it."
            )

        return PreflightReport(
            ready=not issues,
            wifi_interface=self._config.wifi_interface,
            wifi_interface_type=(str(interface_type) if interface_type else None),
            ethernet_interface=(
                str(ethernet.get("interface")) if isinstance(ethernet, dict) else None
            ),
            access_point_addon_slug=self._config.access_point_addon_slug,
            access_point_addon_state=(str(addon_state) if addon_state else None),
            current_wifi_mode=(str(current_mode) if current_mode else None),
            issues=tuple(issues),
            warnings=tuple(warnings),
        )

    async def list_addons(self) -> list[dict[str, str]]:
        """Return only the display-safe fields needed to select an AP app."""
        addons = await self._supervisor.get_addons()
        return [
            {
                "slug": str(item.get("slug", "")),
                "name": str(item.get("name", "")),
                "state": str(item.get("state", "unknown")),
            }
            for item in addons
            if item.get("slug") != "meross_provisioner"
        ]

    async def scan(
        self,
        *,
        confirm_ap_interruption: bool,
        confirm_dedicated_interface: bool,
    ) -> tuple[str, list[AccessPoint]]:
        """Pause the AP app, discover setup APs, and keep a bounded session."""
        if not confirm_ap_interruption:
            raise SafetyCheckError(
                "Confirm the temporary HA-AP interruption to continue."
            )
        if not confirm_dedicated_interface:
            raise SafetyCheckError(
                "Confirm that the Wi-Fi interface is dedicated to the AP app "
                "and has no station profile to preserve."
            )
        report = await self.preflight()
        if not report.ready:
            raise SafetyCheckError("Preflight failed: " + " ".join(report.issues))

        async with self._session_lock:
            if self._session is not None or self._busy:
                raise SessionError("A provisioning session is already active.")

            ap_slug = self._config.access_point_addon_slug
            journal = {
                "interface": self._config.wifi_interface,
                "access_point_addon_slug": ap_slug,
                "phase": "stopping_ap",
                "ap_was_running": True,
                "remove_temporary_profile": False,
                "created_at": datetime.now(UTC).isoformat(),
            }
            self._journal.write(journal)
            try:
                await self._supervisor.stop_addon(ap_slug)
                journal["phase"] = "ap_stopped"
                self._journal.write(journal)
                raw_access_points = await self._supervisor.scan_access_points(
                    self._config.wifi_interface
                )
                access_points = self._parse_access_points(raw_access_points)
                candidates = [
                    ap
                    for ap in access_points
                    if ap.looks_like_meross_setup_ap and ap.mode == "infrastructure"
                ]
                if not candidates:
                    raise SessionError(
                        "No Meross-looking setup AP was found. Put one device "
                        "in setup mode and scan again."
                    )
                ssids = [ap.ssid for ap in candidates]
                if len(ssids) != len(set(ssids)):
                    raise SessionError(
                        "Multiple setup APs have the same SSID. Power off other "
                        "devices in setup mode and scan again."
                    )
                session = ScanSession(
                    session_id=secrets.token_urlsafe(24),
                    interface=self._config.wifi_interface,
                    access_point_addon_slug=ap_slug,
                    access_points=tuple(candidates),
                    created_at=datetime.now(UTC),
                )
                self._session = session
                self._expiry_task = asyncio.create_task(
                    self._expire_session(session.session_id),
                    name="meross-provisioner-session-expiry",
                )
                return session.session_id, candidates
            except BaseException:
                await asyncio.shield(
                    self._restore_ap(journal, remove_temporary_profile=False)
                )
                raise

    async def provision(
        self,
        *,
        session_id: str,
        device_ssid: str,
        device_bssid: str,
        target_ssid: str,
        target_password: str,
    ) -> ProvisioningResult:
        """Configure one selected device and always attempt AP restoration."""
        async with self._session_lock:
            session = self._session
            if session is None or session.session_id != session_id:
                raise SessionError(
                    "The scan session is missing or expired. Scan again."
                )
            if self._busy:
                raise SessionError("A provisioning operation is already running.")
            selected_ap = session.access_point(device_ssid, device_bssid)
            if selected_ap is None:
                raise SessionError("Select a Meross AP from the current scan results.")
            self._busy = True
            if self._expiry_task is not None:
                self._expiry_task.cancel()
                self._expiry_task = None

        profile_created = False
        operation_error: BaseException | None = None
        result: ProvisioningResult | None = None
        try:
            self._validate_target_wifi(target_ssid, target_password)
            self._journal.write(
                {
                    "interface": session.interface,
                    "access_point_addon_slug": session.access_point_addon_slug,
                    "phase": "connecting_to_device_ap",
                    "ap_was_running": True,
                    "remove_temporary_profile": True,
                    "created_at": session.created_at.isoformat(),
                }
            )
            # A timed-out Supervisor response may still mean NetworkManager
            # applied the change, so cleanup is required from this point.
            profile_created = True
            await self._supervisor.update_interface(
                session.interface,
                {
                    "wifi": {
                        "mode": "infrastructure",
                        "auth": "open",
                        "ssid": selected_ap.ssid,
                    },
                    "ipv4": {"method": "auto", "route_metric": _TEMP_ROUTE_METRIC},
                    "ipv6": {"method": "auto", "route_metric": _TEMP_ROUTE_METRIC},
                },
            )
            self._journal.write(
                {
                    "interface": session.interface,
                    "access_point_addon_slug": session.access_point_addon_slug,
                    "phase": "temporary_profile_created",
                    "ap_was_running": True,
                    "remove_temporary_profile": True,
                    "created_at": session.created_at.isoformat(),
                }
            )

            interface_info = await self._wait_for_connection(
                session.interface, selected_ap.ssid
            )
            gateway = self._private_gateway(interface_info)
            await self._check_route_overlap_async(gateway)
            device = self._device_factory(gateway)
            info = await device.get_device_info()
            if not is_supported_model(info.model):
                raise UnsupportedDeviceError(
                    f"Model {info.model!r} is not an initial test target. "
                    "No Wi-Fi settings were written."
                )
            wifi_network = self._find_target_network(
                await device.get_wifi_list(), target_ssid
            )
            await device.set_wifi(wifi_network, target_password)
            result = ProvisioningResult(
                model=info.model,
                subtype=info.subtype,
                firmware=info.firmware,
                mac_address=info.mac_address,
                target_ssid=target_ssid,
                message=(
                    "The device acknowledged its Wi-Fi configuration and is restarting."
                ),
            )
        except BaseException as err:
            operation_error = err
        finally:
            try:
                await self._restore_ap(
                    {
                        "interface": session.interface,
                        "access_point_addon_slug": session.access_point_addon_slug,
                        "phase": "temporary_profile_created"
                        if profile_created
                        else "ap_stopped",
                        "ap_was_running": True,
                        "remove_temporary_profile": profile_created,
                    },
                    remove_temporary_profile=profile_created,
                )
            except RecoveryError as recovery_error:
                async with self._session_lock:
                    self._session = None
                    self._busy = False
                if operation_error is not None:
                    raise RecoveryError(
                        "Provisioning stopped and AP recovery also failed: "
                        f"{recovery_error}"
                    ) from operation_error
                raise
            async with self._session_lock:
                self._session = None
                self._busy = False

        if operation_error is not None:
            if isinstance(operation_error, Exception):
                raise operation_error
            raise operation_error
        if result is None:
            raise DeviceProtocolError(
                "The device did not return a provisioning result."
            )
        return result

    async def cancel(self, session_id: str) -> None:
        """Cancel an idle scan session and restore the AP app."""
        async with self._session_lock:
            session = self._session
            if session is None or session.session_id != session_id:
                raise SessionError("The scan session is missing or expired.")
            if self._busy:
                raise SessionError(
                    "Provisioning is active; wait for its recovery step to finish."
                )
            self._session = None
            if self._expiry_task is not None:
                self._expiry_task.cancel()
                self._expiry_task = None
        await self._restore_ap(
            {
                "interface": session.interface,
                "access_point_addon_slug": session.access_point_addon_slug,
                "phase": "ap_stopped",
                "ap_was_running": True,
                "remove_temporary_profile": False,
            },
            remove_temporary_profile=False,
        )

    async def recover_interrupted_transaction(self) -> str | None:
        """Restore the AP app if a prior app process stopped unexpectedly."""
        journal = self._journal.read()
        if journal is None:
            return None
        phase = str(journal.get("phase", ""))
        remove_profile = (
            bool(journal.get("remove_temporary_profile"))
            or phase == "temporary_profile_created"
        )
        await self._restore_ap(journal, remove_temporary_profile=remove_profile)
        return "Recovered an interrupted transaction and restored the AP app."

    async def close(self) -> None:
        """Best-effort cleanup when the app process is shutting down."""
        session = self._session
        if session is None:
            return
        if self._expiry_task is not None:
            self._expiry_task.cancel()
            self._expiry_task = None
        try:
            await self._restore_ap(
                {
                    "interface": session.interface,
                    "access_point_addon_slug": session.access_point_addon_slug,
                    "phase": "ap_stopped",
                    "ap_was_running": True,
                    "remove_temporary_profile": False,
                },
                remove_temporary_profile=False,
            )
        except RecoveryError:
            _LOGGER.exception("Failed to restore the AP app during shutdown")
        self._session = None

    async def _expire_session(self, session_id: str) -> None:
        try:
            await asyncio.sleep(self._config.session_timeout_seconds)
            async with self._session_lock:
                session = self._session
                if session is None or session.session_id != session_id or self._busy:
                    return
                self._session = None
                self._expiry_task = None
            await self._restore_ap(
                {
                    "interface": session.interface,
                    "access_point_addon_slug": session.access_point_addon_slug,
                    "phase": "ap_stopped",
                    "ap_was_running": True,
                    "remove_temporary_profile": False,
                },
                remove_temporary_profile=False,
            )
        except asyncio.CancelledError:
            raise
        except RecoveryError:
            _LOGGER.exception("Session timed out and AP recovery failed")

    async def _wait_for_connection(
        self, interface: str, expected_ssid: str, timeout_seconds: float = 35
    ) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            info = await self._supervisor.get_interface_info(interface)
            wifi = info.get("wifi")
            if (
                info.get("connected") is True
                and isinstance(wifi, dict)
                and wifi.get("ssid") == expected_ssid
            ):
                return info
            await asyncio.sleep(1)
        raise SupervisorError(
            "The Wi-Fi interface did not join the Meross setup AP in time."
        )

    def _private_gateway(self, interface_info: Mapping[str, Any]) -> str:
        ipv4 = interface_info.get("ipv4")
        gateway = ipv4.get("gateway") if isinstance(ipv4, dict) else None
        if not isinstance(gateway, str):
            raise SafetyCheckError(
                "The setup AP did not report an IPv4 gateway; refusing to "
                "guess the device address."
            )
        try:
            address = ipaddress.ip_address(gateway)
        except ValueError as err:
            raise SafetyCheckError(
                "The setup AP returned an invalid gateway address."
            ) from err
        if address.version != 4 or not address.is_private:
            raise SafetyCheckError(
                "The setup AP gateway is not a private IPv4 address."
            )
        return str(address)

    async def _check_route_overlap_async(self, gateway: str) -> None:
        network = await self._supervisor.get_network_info()
        for interface in network.get("interfaces", []):
            if not isinstance(interface, dict) or interface.get("type") != "ethernet":
                continue
            ipv4 = interface.get("ipv4")
            addresses = ipv4.get("address", []) if isinstance(ipv4, dict) else []
            if not isinstance(addresses, list):
                continue
            for value in addresses:
                try:
                    if not isinstance(value, str):
                        continue
                    if (
                        ipaddress.ip_address(gateway)
                        in ipaddress.ip_interface(value).network
                    ):
                        raise SafetyCheckError(
                            "The wired LAN overlaps the Meross setup subnet; "
                            "refusing an ambiguous route."
                        )
                except ValueError:
                    continue

    @staticmethod
    def _parse_access_points(raw: list[dict[str, Any]]) -> list[AccessPoint]:
        access_points: list[AccessPoint] = []
        for item in raw:
            ssid = item.get("ssid")
            mac = item.get("mac")
            if not isinstance(ssid, str) or not ssid or not isinstance(mac, str):
                continue
            access_points.append(
                AccessPoint(
                    ssid=ssid,
                    mac=mac,
                    frequency=int(item.get("frequency", 0)),
                    signal=int(item.get("signal", 0)),
                    mode=str(item.get("mode", "infrastructure")),
                )
            )
        return access_points

    @staticmethod
    def _validate_target_wifi(ssid: str, password: str) -> None:
        if not ssid or len(ssid.encode("utf-8")) > 32 or "\x00" in ssid:
            raise ConfigurationError("Enter a valid Wi-Fi SSID of at most 32 bytes.")
        password_size = len(password.encode("utf-8"))
        if not 8 <= password_size <= 63:
            raise ConfigurationError(
                "The prototype supports WPA/WPA2 passphrases between 8 and 63 bytes."
            )

    @staticmethod
    def _find_target_network(
        networks: list[DeviceWifiNetwork], target_ssid: str
    ) -> DeviceWifiNetwork:
        matches = [network for network in networks if network.ssid == target_ssid]
        if not matches:
            raise DeviceProtocolError(
                "The Meross device cannot see the target SSID. Check its "
                "2.4 GHz coverage and try again."
            )
        for network in matches:
            if not _BSSID_RE.fullmatch(network.bssid):
                raise DeviceProtocolError(
                    "The device returned an invalid target BSSID."
                )
            if not 1 <= network.channel <= 14:
                raise DeviceProtocolError(
                    "The device returned an unsupported Wi-Fi channel."
                )
        return max(matches, key=lambda network: network.signal)

    async def _restore_ap(
        self,
        journal: dict[str, Any],
        *,
        remove_temporary_profile: bool,
    ) -> None:
        """Remove the temporary station profile if requested and restart AP."""
        interface = str(journal.get("interface", ""))
        addon_slug = str(journal.get("access_point_addon_slug", ""))
        errors: list[str] = []

        if remove_temporary_profile and interface:
            try:
                # Supervisor v1 deletes the active profile when disabling an
                # interface. The UI therefore requires explicit confirmation
                # that this interface has no profile the user needs to keep.
                await self._supervisor.update_interface(interface, {"enabled": False})
            except Exception:
                errors.append("could not remove the temporary Wi-Fi profile")
                _LOGGER.exception("Could not clean up the temporary Wi-Fi profile")

        if journal.get("ap_was_running") is True and addon_slug:
            try:
                info = await self._supervisor.get_addon_info(addon_slug)
                if info.get("state") != "started":
                    await self._supervisor.start_addon(addon_slug)
                elif remove_temporary_profile:
                    await self._supervisor.restart_addon(addon_slug)
            except Exception:
                errors.append("could not restart the configured AP app")
                _LOGGER.exception("Could not restart the configured AP app")

        if errors:
            # Keep the journal so startup recovery can retry.
            self._journal.write(
                {
                    "interface": interface,
                    "access_point_addon_slug": addon_slug,
                    "phase": "recovery_required",
                    "ap_was_running": journal.get("ap_was_running") is True,
                    "remove_temporary_profile": remove_temporary_profile,
                    "created_at": journal.get(
                        "created_at", datetime.now(UTC).isoformat()
                    ),
                }
            )
            raise RecoveryError("Recovery was incomplete: " + "; ".join(errors))

        self._journal.clear()
