"""Safety-oriented provisioning transaction independent of the HA UI."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from .errors import (
    ConfigurationError,
    DeviceProtocolError,
    NetworkManagerError,
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
    WifiProfile,
)

_LOGGER = logging.getLogger(__name__)
_BSSID_RE = re.compile(r"^(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$")


class SupervisorPort(Protocol):
    """Operations required from a host/platform adapter."""

    async def get_network_info(self) -> dict[str, Any]: ...

    async def get_addon_info(self, slug: str) -> dict[str, Any]: ...

    async def get_addons(self) -> list[dict[str, Any]]: ...

    async def stop_addon(self, slug: str) -> None: ...

    async def start_addon(self, slug: str) -> None: ...

    async def restart_addon(self, slug: str) -> None: ...


class NetworkManagerPort(Protocol):
    """Operations for the AP interface, which may be unmanaged by Supervisor."""

    async def get_device_info(self, interface: str) -> dict[str, str]: ...

    async def find_autoconnecting_wifi_profiles(
        self, interface: str
    ) -> list[WifiProfile]: ...

    async def set_profiles_autoconnect(
        self, connection_uuids: list[str], enabled: bool
    ) -> None: ...

    async def enable_wifi_radio(self) -> None: ...

    async def set_managed(self, interface: str, managed: bool) -> None: ...

    async def scan_access_points(self, interface: str) -> list[AccessPoint]: ...

    async def create_open_connection(
        self, interface: str, ssid: str, bssid: str, connection_uuid: str
    ) -> None: ...

    async def activate_connection(
        self, interface: str, connection_uuid: str
    ) -> None: ...

    async def get_gateway(self, interface: str) -> str: ...

    async def delete_connection(self, connection_uuid: str) -> None: ...


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
    wifi_device_state: str | None
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
            "wifi_device_state": self.wifi_device_state,
            "issues": list(self.issues),
            "warnings": list(self.warnings),
        }


class ProvisioningWorkflow:
    """Coordinate Wi-Fi discovery, one device write, and AP recovery."""

    def __init__(
        self,
        supervisor: SupervisorPort,
        network_manager: NetworkManagerPort,
        device_factory: DeviceFactory,
        journal: TransactionJournal,
        config: WorkflowConfig,
    ) -> None:
        self._supervisor = supervisor
        self._network_manager = network_manager
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
                "Confirm this Wi-Fi interface is dedicated to the AP app. Profiles "
                "that could interfere have autoconnect suspended and restored."
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
                wifi_device_state=None,
                issues=tuple(issues),
                warnings=tuple(warnings),
            )

        try:
            network = await self._supervisor.get_network_info()
            wifi_device = await self._network_manager.get_device_info(
                self._config.wifi_interface
            )
            blocking_wifi_profiles = (
                await self._network_manager.find_autoconnecting_wifi_profiles(
                    self._config.wifi_interface
                )
            )
            addon = await self._supervisor.get_addon_info(
                self._config.access_point_addon_slug
            )
        except (SupervisorError, NetworkManagerError) as err:
            return PreflightReport(
                ready=False,
                wifi_interface=self._config.wifi_interface,
                wifi_interface_type=None,
                ethernet_interface=None,
                access_point_addon_slug=self._config.access_point_addon_slug,
                access_point_addon_state=None,
                wifi_device_state=None,
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

        wifi_device_state = wifi_device.get("state", "unknown")
        if wifi_device_state.casefold() not in {"unmanaged", "disconnected"}:
            issues.append(
                "NetworkManager reports the AP interface in state "
                f"{wifi_device_state!r}; expected unmanaged or disconnected."
            )
        if blocking_wifi_profiles:
            unique_names = list(
                dict.fromkeys(profile.name for profile in blocking_wifi_profiles)
            )
            names = ", ".join(unique_names[:5])
            if len(unique_names) > 5:
                names += f", and {len(unique_names) - 5} more"
            warnings.append(
                "These saved Wi-Fi profiles could autoconnect to "
                f"{self._config.wifi_interface!r} and will be temporarily disabled, "
                f"then restored: {names}."
            )

        state = addon.get("state")
        addon_state = str(state) if state is not None else None
        if addon_state != "started":
            issues.append(
                "The configured AP app is not running; refusing a workflow "
                "that cannot restore it."
            )

        return PreflightReport(
            ready=not issues,
            wifi_interface=self._config.wifi_interface,
            wifi_interface_type=(str(wifi_device.get("type", "wireless"))),
            ethernet_interface=(
                str(ethernet.get("interface")) if isinstance(ethernet, dict) else None
            ),
            access_point_addon_slug=self._config.access_point_addon_slug,
            access_point_addon_state=(str(addon_state) if addon_state else None),
            wifi_device_state=wifi_device_state,
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
                blocking_profiles = (
                    await self._network_manager.find_autoconnecting_wifi_profiles(
                        self._config.wifi_interface
                    )
                )
                suspended_uuids = [
                    profile.connection_uuid for profile in blocking_profiles
                ]
                journal["suspended_profile_uuids"] = ",".join(suspended_uuids)
                journal["phase"] = "suspending_wifi_autoconnect"
                self._journal.write(journal)
                if suspended_uuids:
                    await self._network_manager.set_profiles_autoconnect(
                        suspended_uuids, False
                    )
                journal["phase"] = "wifi_autoconnect_suspended"
                self._journal.write(journal)
                await self._network_manager.enable_wifi_radio()
                await self._network_manager.set_managed(
                    self._config.wifi_interface, True
                )
                await self._wait_for_wifi_ready(self._config.wifi_interface)
                journal["phase"] = "wifi_managed"
                self._journal.write(journal)
                access_points = await self._network_manager.scan_access_points(
                    self._config.wifi_interface
                )
                candidates = [
                    ap
                    for ap in access_points
                    if ap.looks_like_meross_setup_ap and ap.mode == "infrastructure"
                ]
                if not candidates:
                    seen = sorted({ap.ssid for ap in access_points})
                    if not seen:
                        raise SessionError(
                            "NetworkManager returned no Wi-Fi networks. Check that "
                            "the setup device is broadcasting its AP and that wlan0 "
                            "can scan."
                        )
                    preview = ", ".join(seen[:12])
                    if len(seen) > 12:
                        preview += f", and {len(seen) - 12} more"
                    raise SessionError(
                        "No Meross-looking setup AP was found. Networks seen: "
                        f"{preview}. Check the device model's reset procedure and "
                        "that it is in AP setup mode, not only Bluetooth pairing."
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
                    suspended_profile_uuids=tuple(suspended_uuids),
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
        connection_uuid = str(uuid.uuid4())
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
                    "temporary_connection_uuid": connection_uuid,
                    "suspended_profile_uuids": ",".join(
                        session.suspended_profile_uuids
                    ),
                    "created_at": session.created_at.isoformat(),
                }
            )
            # Journal the unique profile ID before creation so recovery can
            # remove it if NetworkManager succeeds but the response times out.
            profile_created = True
            await self._network_manager.create_open_connection(
                session.interface,
                selected_ap.ssid,
                selected_ap.mac,
                connection_uuid,
            )
            self._journal.write(
                {
                    "interface": session.interface,
                    "access_point_addon_slug": session.access_point_addon_slug,
                    "phase": "temporary_profile_created",
                    "ap_was_running": True,
                    "remove_temporary_profile": True,
                    "temporary_connection_uuid": connection_uuid,
                    "suspended_profile_uuids": ",".join(
                        session.suspended_profile_uuids
                    ),
                    "created_at": session.created_at.isoformat(),
                }
            )

            await self._network_manager.activate_connection(
                session.interface, connection_uuid
            )
            gateway = self._private_gateway(
                await self._network_manager.get_gateway(session.interface)
            )
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
                        "temporary_connection_uuid": (
                            connection_uuid if profile_created else None
                        ),
                        "suspended_profile_uuids": ",".join(
                            session.suspended_profile_uuids
                        ),
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
                "temporary_connection_uuid": None,
                "suspended_profile_uuids": ",".join(session.suspended_profile_uuids),
            },
            remove_temporary_profile=False,
        )

    async def recover_interrupted_transaction(self) -> str | None:
        """Restore the AP app if a prior app process stopped unexpectedly."""
        journal = self._journal.read()
        if journal is None:
            return None
        remove_profile = bool(journal.get("remove_temporary_profile"))
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
                    "temporary_connection_uuid": None,
                    "suspended_profile_uuids": ",".join(
                        session.suspended_profile_uuids
                    ),
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
                    "temporary_connection_uuid": None,
                    "suspended_profile_uuids": ",".join(
                        session.suspended_profile_uuids
                    ),
                },
                remove_temporary_profile=False,
            )
        except asyncio.CancelledError:
            raise
        except RecoveryError:
            _LOGGER.exception("Session timed out and AP recovery failed")

    async def _wait_for_wifi_ready(
        self, interface: str, timeout_seconds: float = 15
    ) -> None:
        """Wait until NetworkManager has brought the interface up for scanning."""
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        last_state = "unknown"
        while asyncio.get_running_loop().time() < deadline:
            info = await self._network_manager.get_device_info(interface)
            last_state = info.get("state", "unknown")
            if last_state.casefold() in {"disconnected", "connected"}:
                return
            await asyncio.sleep(0.5)
        raise NetworkManagerError(
            "NetworkManager did not make the Wi-Fi device available for scanning "
            f"(last state: {last_state!r})."
        )

    def _private_gateway(self, gateway: str) -> str:
        if not isinstance(gateway, str) or not gateway:
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
        suspended_value = journal.get("suspended_profile_uuids", "")
        suspended_uuids = (
            [value for value in suspended_value.split(",") if value]
            if isinstance(suspended_value, str)
            else []
        )

        temporary_connection_uuid = journal.get("temporary_connection_uuid")
        released = False
        if interface and journal.get("ap_was_running") is True:
            try:
                await self._network_manager.set_managed(interface, False)
                released = True
            except Exception:
                errors.append(
                    "could not release the Wi-Fi interface from NetworkManager"
                )
                _LOGGER.exception("Could not release the Wi-Fi interface")

        if remove_temporary_profile:
            if not isinstance(temporary_connection_uuid, str):
                errors.append("the temporary Wi-Fi connection ID is missing")
            else:
                try:
                    await self._network_manager.delete_connection(
                        temporary_connection_uuid
                    )
                except Exception:
                    errors.append("could not remove the temporary Wi-Fi connection")
                    _LOGGER.exception("Could not remove the temporary Wi-Fi connection")

        if released and suspended_uuids:
            try:
                await self._network_manager.set_profiles_autoconnect(
                    suspended_uuids, True
                )
            except Exception:
                errors.append("could not restore Wi-Fi profile autoconnect")
                _LOGGER.exception("Could not restore Wi-Fi profile autoconnect")

        if journal.get("ap_was_running") is True and addon_slug:
            try:
                info = await self._supervisor.get_addon_info(addon_slug)
                if info.get("state") != "started":
                    await self._supervisor.start_addon(addon_slug)
                else:
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
                    "temporary_connection_uuid": temporary_connection_uuid,
                    "suspended_profile_uuids": ",".join(suspended_uuids),
                    "created_at": journal.get(
                        "created_at", datetime.now(UTC).isoformat()
                    ),
                }
            )
            raise RecoveryError("Recovery was incomplete: " + "; ".join(errors))

        self._journal.clear()
