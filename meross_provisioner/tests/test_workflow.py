from __future__ import annotations

import pytest

from meross_provisioner.errors import (
    ConfigurationError,
    SafetyCheckError,
    UnsupportedDeviceError,
)
from meross_provisioner.journal import TransactionJournal
from meross_provisioner.models import DeviceInfo, DeviceWifiNetwork
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

    async def get_interface_info(self, interface: str) -> dict:
        assert interface == "wlan0"
        return {
            "interface": "wlan0",
            "type": "wireless",
            "connected": self.wifi_connected,
            "wifi": (
                {"mode": "infrastructure", "ssid": self.wifi_ssid}
                if self.wifi_ssid
                else None
            ),
            "ipv4": {
                "address": ["10.10.10.100/24"] if self.wifi_ssid else [],
                "gateway": "10.10.10.1" if self.wifi_ssid else None,
            },
        }

    async def scan_access_points(self, interface: str) -> list[dict]:
        assert interface == "wlan0"
        assert self.addon_state == "stopped"
        return [
            {
                "ssid": "Meross_SETUP_1234",
                "mac": "aa:bb:cc:dd:ee:ff",
                "frequency": 2412,
                "signal": 77,
                "mode": "infrastructure",
            },
            {
                "ssid": "ordinary-network",
                "mac": "11:22:33:44:55:66",
                "frequency": 2437,
                "signal": 80,
                "mode": "infrastructure",
            },
        ]

    async def update_interface(self, interface: str, body: dict) -> None:
        assert interface == "wlan0"
        if "wifi" in body:
            self.wifi_ssid = body["wifi"]["ssid"]
            self.wifi_connected = True
        elif body.get("enabled") is False:
            self.profile_cleanup_count += 1
            self.wifi_ssid = None
            self.wifi_connected = False

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
async def test_preflight_lists_wifi_interfaces_seen_by_supervisor(tmp_path) -> None:
    supervisor = FakeSupervisor()
    original_get_network_info = supervisor.get_network_info

    async def without_wifi() -> dict:
        result = await original_get_network_info()
        result["interfaces"] = [
            item for item in result["interfaces"] if item["type"] != "wireless"
        ]
        return result

    supervisor.get_network_info = without_wifi
    workflow, _, _, _ = make_workflow(tmp_path, supervisor=supervisor)

    report = await workflow.preflight()

    assert not report.ready
    assert any("Available Wi-Fi interfaces: none" in issue for issue in report.issues)


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
async def test_preflight_refuses_existing_wifi_profile(tmp_path) -> None:
    supervisor = FakeSupervisor()
    original_get_network_info = supervisor.get_network_info

    async def with_existing_profile() -> dict:
        result = await original_get_network_info()
        wireless = next(
            item for item in result["interfaces"] if item["type"] == "wireless"
        )
        wireless["wifi"] = {"mode": "ap", "ssid": "HA-AP"}
        return result

    supervisor.get_network_info = with_existing_profile
    workflow, _, _, _ = make_workflow(tmp_path, supervisor=supervisor)

    report = await workflow.preflight()

    assert not report.ready
    assert any("existing Wi-Fi profile" in issue for issue in report.issues)
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
    saved = journal.read()
    assert saved is not None
    assert "password" not in saved

    await workflow.cancel(session_id)
    assert supervisor.addon_state == "started"
    assert supervisor.started == ["local_test_ap"]
    assert journal.read() is None


@pytest.mark.asyncio
async def test_startup_recovery_removes_journaled_temporary_profile(tmp_path) -> None:
    supervisor = FakeSupervisor()
    supervisor.addon_state = "stopped"
    supervisor.wifi_ssid = "Meross_SETUP_1234"
    supervisor.wifi_connected = True
    workflow, _, _, journal = make_workflow(tmp_path, supervisor=supervisor)
    journal.write(
        {
            "interface": "wlan0",
            "access_point_addon_slug": "local_test_ap",
            "phase": "temporary_profile_created",
            "ap_was_running": True,
            "remove_temporary_profile": True,
        }
    )

    recovery_message = await workflow.recover_interrupted_transaction()

    assert recovery_message is not None
    assert supervisor.profile_cleanup_count == 1
    assert supervisor.addon_state == "started"
    assert journal.read() is None


@pytest.mark.asyncio
async def test_recovery_restarts_ap_if_it_started_before_profile_cleanup(
    tmp_path,
) -> None:
    supervisor = FakeSupervisor()
    supervisor.wifi_ssid = "Meross_SETUP_1234"
    supervisor.wifi_connected = True
    workflow, _, _, journal = make_workflow(tmp_path, supervisor=supervisor)
    journal.write(
        {
            "interface": "wlan0",
            "access_point_addon_slug": "local_test_ap",
            "phase": "temporary_profile_created",
            "ap_was_running": True,
            "remove_temporary_profile": True,
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
