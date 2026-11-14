from __future__ import annotations

import pytest

from meross_provisioner.errors import (
    ConfigurationError,
    NetworkManagerError,
    SafetyCheckError,
    UnsupportedDeviceError,
)
from meross_provisioner.journal import TransactionJournal
from meross_provisioner.models import (
    AccessPoint,
    DeviceInfo,
    DeviceWifiNetwork,
    WifiProfile,
)
from meross_provisioner.workflow import ProvisioningWorkflow, WorkflowConfig


class FakeSupervisor:
    def __init__(self, *, ethernet_subnet: str = "192.168.1.20/24") -> None:
        self.addon_state = "started"
        self.wifi_connected = False
        self.wifi_ssid: str | None = None
        self.ethernet_subnet = ethernet_subnet
        self.stopped: list[str] = []
        self.started: list[str] = []
        self.restarted: list[str] = []
        self.profile_cleanup_count = 0
        self.nm_state = "unmanaged"
        self.device_present = True
        self.wifi_profiles = [
            WifiProfile(
                name="Supervisor wlan0",
                connection_uuid="11111111-1111-4111-8111-111111111111",
            ),
            WifiProfile(
                name="Supervisor wlan0",
                connection_uuid="22222222-2222-4222-8222-222222222222",
            ),
        ]
        self.autoconnect_snapshots: dict[str, bool] = {
            profile.connection_uuid: True for profile in self.wifi_profiles
        }
        self.temp_connection_uuid: str | None = None

    async def get_network_info(self) -> dict:
        return {
            "interfaces": [
                {
                    "interface": "eth0",
                    "type": "ethernet",
                    "connected": True,
                    "ipv4": {"address": [self.ethernet_subnet]},
                },
                {
                    "interface": "wlan0",
                    "type": "wireless",
                    "connected": self.wifi_connected,
                    "wifi": (
                        {"mode": "infrastructure", "ssid": self.wifi_ssid}
                        if self.wifi_ssid
                        else None
                    ),
                },
            ]
        }

    async def get_device_info(self, interface: str) -> dict[str, str]:
        assert interface == "wlan0"
        if not self.device_present:
            raise NetworkManagerError("NetworkManager does not list wlan0.")
        return {"interface": interface, "type": "wifi", "state": self.nm_state}

    async def find_autoconnecting_wifi_profiles(
        self, interface: str
    ) -> list[WifiProfile]:
        assert interface == "wlan0"
        return [
            profile
            for profile in self.wifi_profiles
            if self.autoconnect_snapshots[profile.connection_uuid]
        ]

    async def set_profiles_autoconnect(
        self, connection_uuids: list[str], enabled: bool
    ) -> None:
        for connection_uuid in connection_uuids:
            assert connection_uuid in self.autoconnect_snapshots
            self.autoconnect_snapshots[connection_uuid] = enabled

    async def set_managed(self, interface: str, managed: bool) -> None:
        assert interface == "wlan0"
        self.nm_state = "disconnected" if managed else "unmanaged"
        if not managed:
            self.wifi_connected = False
            self.wifi_ssid = None

    async def scan_access_points(self, interface: str) -> list[AccessPoint]:
        assert interface == "wlan0"
        assert self.addon_state == "stopped"
        assert self.nm_state == "disconnected"
        return [
            AccessPoint(
                ssid="Meross_SETUP_1234",
                mac="aa:bb:cc:dd:ee:ff",
                frequency=2412,
                signal=77,
            ),
            AccessPoint(
                ssid="ordinary-network",
                mac="11:22:33:44:55:66",
                frequency=2437,
                signal=80,
            ),
        ]

    async def create_open_connection(
        self, interface: str, ssid: str, bssid: str, connection_uuid: str
    ) -> None:
        assert interface == "wlan0"
        assert bssid == "aa:bb:cc:dd:ee:ff"
        self.wifi_ssid = ssid
        self.temp_connection_uuid = connection_uuid

    async def activate_connection(self, interface: str, connection_uuid: str) -> None:
        assert interface == "wlan0"
        assert connection_uuid == self.temp_connection_uuid
        self.nm_state = "connected"
        self.wifi_connected = True

    async def get_gateway(self, interface: str) -> str:
        assert interface == "wlan0"
        return "10.10.10.1"

    async def delete_connection(self, connection_uuid: str) -> None:
        if connection_uuid == self.temp_connection_uuid:
            self.profile_cleanup_count += 1
            self.temp_connection_uuid = None

    async def get_addon_info(self, slug: str) -> dict:
        assert slug == "local_test_ap"
        return {"slug": slug, "state": self.addon_state}

    async def get_addons(self) -> list[dict]:
        return [{"slug": "local_test_ap", "name": "Test AP", "state": self.addon_state}]

    async def stop_addon(self, slug: str) -> None:
        assert slug == "local_test_ap"
        self.addon_state = "stopped"
        self.stopped.append(slug)

    async def start_addon(self, slug: str) -> None:
        assert slug == "local_test_ap"
        self.addon_state = "started"
        self.started.append(slug)

    async def restart_addon(self, slug: str) -> None:
        assert slug == "local_test_ap"
        self.addon_state = "started"
        self.restarted.append(slug)


class FakeDevice:
    def __init__(
        self,
        *,
        model: str = "mss210",
        journal: TransactionJournal | None = None,
        fail_write: bool = False,
    ) -> None:
        self.model = model
        self.journal = journal
        self.password_was_journaled = False
        self.wifi_write: tuple[DeviceWifiNetwork, str] | None = None
        self.fail_write = fail_write

    async def get_device_info(self) -> DeviceInfo:
        return DeviceInfo(
            model=self.model,
            subtype="eu",
            firmware="test-firmware",
            uuid="test-uuid",
            mac_address="00:11:22:33:44:55",
        )

    async def get_wifi_list(self) -> list[DeviceWifiNetwork]:
        return [
            DeviceWifiNetwork(
                ssid="HA-AP",
                bssid="12:34:56:78:9a:bc",
                channel=6,
                signal=90,
                cipher=3,
                encryption=6,
            )
        ]

    async def set_wifi(self, network: DeviceWifiNetwork, password: str) -> None:
        if self.journal is not None and self.journal._path.exists():
            self.password_was_journaled = password in self.journal._path.read_text(
                encoding="utf-8"
            )
        if self.fail_write:
            raise RuntimeError("simulated device write failure")
        self.wifi_write = (network, password)


def make_workflow(tmp_path, *, supervisor=None, device=None, config=None):
    selected_supervisor = supervisor or FakeSupervisor()
    journal = TransactionJournal(tmp_path / "transaction.json")
    selected_device = device or FakeDevice(journal=journal)
    workflow = ProvisioningWorkflow(
        supervisor=selected_supervisor,
        network_manager=selected_supervisor,
        device_factory=lambda _: selected_device,
        journal=journal,
        config=config
        or WorkflowConfig(
            wifi_interface="wlan0",
            access_point_addon_slug="local_test_ap",
            session_timeout_seconds=60,
        ),
    )
    return workflow, selected_supervisor, selected_device, journal


async def start_scan(workflow: ProvisioningWorkflow) -> str:
    session_id, access_points = await workflow.scan(
        confirm_ap_interruption=True,
        confirm_dedicated_interface=True,
    )
    assert len(access_points) == 1
    return session_id


@pytest.mark.asyncio
async def test_preflight_requires_wired_management_path(tmp_path) -> None:
    supervisor = FakeSupervisor()
    original_get_network_info = supervisor.get_network_info

    async def without_ethernet() -> dict:
        result = await original_get_network_info()
        result["interfaces"] = [
            item for item in result["interfaces"] if item["type"] != "ethernet"
        ]
        return result

    supervisor.get_network_info = without_ethernet
    workflow, _, _, _ = make_workflow(tmp_path, supervisor=supervisor)

    report = await workflow.preflight()

    assert not report.ready
    assert any("Ethernet" in issue for issue in report.issues)


@pytest.mark.asyncio
async def test_preflight_checks_wifi_interface_via_networkmanager(tmp_path) -> None:
    supervisor = FakeSupervisor()
    supervisor.device_present = False
    workflow, _, _, _ = make_workflow(tmp_path, supervisor=supervisor)

    report = await workflow.preflight()

    assert not report.ready
    assert any("NetworkManager does not list" in issue for issue in report.issues)


@pytest.mark.asyncio
async def test_scan_requires_both_explicit_confirmations(tmp_path) -> None:
    workflow, supervisor, _, _ = make_workflow(tmp_path)

    with pytest.raises(SafetyCheckError):
        await workflow.scan(
            confirm_ap_interruption=True,
            confirm_dedicated_interface=False,
        )

    assert supervisor.stopped == []


@pytest.mark.asyncio
async def test_preflight_warns_about_autoconnecting_profiles(tmp_path) -> None:
    supervisor = FakeSupervisor()
    workflow, _, _, _ = make_workflow(tmp_path, supervisor=supervisor)

    report = await workflow.preflight()

    assert report.ready
    assert any("Supervisor wlan0" in warning for warning in report.warnings)
    assert not any("Supervisor wlan0" in issue for issue in report.issues)
    assert supervisor.stopped == []


@pytest.mark.asyncio
async def test_scan_pauses_ap_and_returns_only_meross_candidates(tmp_path) -> None:
    workflow, supervisor, _, journal = make_workflow(tmp_path)

    session_id, access_points = await workflow.scan(
        confirm_ap_interruption=True,
        confirm_dedicated_interface=True,
    )

    assert session_id
    assert [item.ssid for item in access_points] == ["Meross_SETUP_1234"]
    assert supervisor.stopped == ["local_test_ap"]
    assert supervisor.addon_state == "stopped"
    assert not any(supervisor.autoconnect_snapshots.values())
    saved = journal.read()
    assert saved is not None
    assert "password" not in saved

    await workflow.cancel(session_id)
    assert supervisor.addon_state == "started"
    assert supervisor.started == ["local_test_ap"]
    assert all(supervisor.autoconnect_snapshots.values())
    assert journal.read() is None


@pytest.mark.asyncio
async def test_startup_recovery_removes_journaled_temporary_profile(tmp_path) -> None:
    supervisor = FakeSupervisor()
    supervisor.addon_state = "stopped"
    supervisor.wifi_ssid = "Meross_SETUP_1234"
    supervisor.wifi_connected = True
    supervisor.nm_state = "connected"
    supervisor.temp_connection_uuid = "00000000-0000-0000-0000-000000000001"
    suspended_uuid = supervisor.wifi_profiles[0].connection_uuid
    supervisor.autoconnect_snapshots[suspended_uuid] = False
    workflow, _, _, journal = make_workflow(tmp_path, supervisor=supervisor)
    journal.write(
        {
            "interface": "wlan0",
            "access_point_addon_slug": "local_test_ap",
            "phase": "temporary_profile_created",
            "ap_was_running": True,
            "remove_temporary_profile": True,
            "temporary_connection_uuid": supervisor.temp_connection_uuid,
            "suspended_profile_uuids": suspended_uuid,
        }
    )

    recovery_message = await workflow.recover_interrupted_transaction()

    assert recovery_message is not None
    assert supervisor.profile_cleanup_count == 1
    assert supervisor.autoconnect_snapshots[suspended_uuid] is True
    assert supervisor.addon_state == "started"
    assert journal.read() is None


@pytest.mark.asyncio
async def test_recovery_restarts_ap_if_it_started_before_profile_cleanup(
    tmp_path,
) -> None:
    supervisor = FakeSupervisor()
    supervisor.wifi_ssid = "Meross_SETUP_1234"
    supervisor.wifi_connected = True
    supervisor.nm_state = "connected"
    supervisor.temp_connection_uuid = "00000000-0000-0000-0000-000000000002"
    workflow, _, _, journal = make_workflow(tmp_path, supervisor=supervisor)
    journal.write(
        {
            "interface": "wlan0",
            "access_point_addon_slug": "local_test_ap",
            "phase": "temporary_profile_created",
            "ap_was_running": True,
            "remove_temporary_profile": True,
            "temporary_connection_uuid": supervisor.temp_connection_uuid,
        }
    )

    await workflow.recover_interrupted_transaction()

    assert supervisor.profile_cleanup_count == 1
    assert supervisor.restarted == ["local_test_ap"]
    assert journal.read() is None


@pytest.mark.asyncio
async def test_provision_writes_wifi_and_restores_ap(tmp_path) -> None:
    workflow, supervisor, device, journal = make_workflow(tmp_path)
    session_id = await start_scan(workflow)

    result = await workflow.provision(
        session_id=session_id,
        device_ssid="Meross_SETUP_1234",
        device_bssid="aa:bb:cc:dd:ee:ff",
        target_ssid="HA-AP",
        target_password="iot-only-test-password",
    )

    assert result.model == "mss210"
    assert device.wifi_write is not None
    assert device.wifi_write[0].bssid == "12:34:56:78:9a:bc"
    assert device.wifi_write[1] == "iot-only-test-password"
    assert not device.password_was_journaled
    assert supervisor.profile_cleanup_count == 1
    assert supervisor.addon_state == "started"
    assert all(supervisor.autoconnect_snapshots.values())
    assert journal.read() is None


@pytest.mark.asyncio
async def test_device_write_failure_still_restores_ap(tmp_path) -> None:
    device = FakeDevice(fail_write=True)
    workflow, supervisor, _, journal = make_workflow(tmp_path, device=device)
    session_id = await start_scan(workflow)

    with pytest.raises(RuntimeError, match="simulated"):
        await workflow.provision(
            session_id=session_id,
            device_ssid="Meross_SETUP_1234",
            device_bssid="aa:bb:cc:dd:ee:ff",
            target_ssid="HA-AP",
            target_password="iot-only-test-password",
        )

    assert supervisor.profile_cleanup_count == 1
    assert supervisor.addon_state == "started"
    assert all(supervisor.autoconnect_snapshots.values())
    assert journal.read() is None


@pytest.mark.asyncio
async def test_unsupported_model_is_not_configured_but_network_is_restored(
    tmp_path,
) -> None:
    device = FakeDevice(model="unknown_model")
    workflow, supervisor, _, journal = make_workflow(tmp_path, device=device)
    session_id = await start_scan(workflow)

    with pytest.raises(UnsupportedDeviceError):
        await workflow.provision(
            session_id=session_id,
            device_ssid="Meross_SETUP_1234",
            device_bssid="aa:bb:cc:dd:ee:ff",
            target_ssid="HA-AP",
            target_password="iot-only-test-password",
        )

    assert device.wifi_write is None
    assert supervisor.addon_state == "started"
    assert journal.read() is None


@pytest.mark.asyncio
async def test_route_overlap_aborts_before_device_write_and_restores_ap(
    tmp_path,
) -> None:
    supervisor = FakeSupervisor(ethernet_subnet="10.10.10.20/24")
    workflow, _, device, journal = make_workflow(tmp_path, supervisor=supervisor)
    session_id = await start_scan(workflow)

    with pytest.raises(SafetyCheckError, match="overlaps"):
        await workflow.provision(
            session_id=session_id,
            device_ssid="Meross_SETUP_1234",
            device_bssid="aa:bb:cc:dd:ee:ff",
            target_ssid="HA-AP",
            target_password="iot-only-test-password",
        )

    assert device.wifi_write is None
    assert supervisor.addon_state == "started"
    assert journal.read() is None


@pytest.mark.asyncio
async def test_invalid_password_restores_ap_without_creating_profile(tmp_path) -> None:
    workflow, supervisor, _, journal = make_workflow(tmp_path)
    session_id = await start_scan(workflow)

    with pytest.raises(ConfigurationError, match="between 8 and 63"):
        await workflow.provision(
            session_id=session_id,
            device_ssid="Meross_SETUP_1234",
            device_bssid="aa:bb:cc:dd:ee:ff",
            target_ssid="HA-AP",
            target_password="short",
        )

    assert supervisor.profile_cleanup_count == 0
    assert supervisor.addon_state == "started"
    assert journal.read() is None
