from __future__ import annotations

import asyncio

import pytest
from aiohttp.test_utils import TestClient, TestServer

from meross_provisioner.config import AppConfig
from meross_provisioner.journal import TransactionJournal
from meross_provisioner.models import ProvisioningResult
from meross_provisioner.supervisor import SupervisorClient
from meross_provisioner.web import create_app
from meross_provisioner.workflow import PreflightReport, WorkflowConfig


class FakeWorkflow:
    def __init__(self) -> None:
        self.password_seen: str | None = None

    async def preflight(self) -> PreflightReport:
        return PreflightReport(
            ready=True,
            wifi_interface="wlan0",
            wifi_interface_type="wireless",
            ethernet_interface="eth0",
            access_point_addon_slug="local_test_ap",
            access_point_addon_state="started",
            current_wifi_mode=None,
            issues=(),
            warnings=(),
        )

    async def recover_interrupted_transaction(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def list_addons(self) -> list[dict[str, str]]:
        return []

    @property
    def session_active(self) -> bool:
        return False

    async def provision(self, **kwargs) -> ProvisioningResult:
        self.password_seen = kwargs["target_password"]
        await asyncio.sleep(0)
        return ProvisioningResult(
            model="mss210",
            subtype="eu",
            firmware="test",
            mac_address="00:11:22:33:44:55",
            target_ssid=kwargs["target_ssid"],
            message="Device acknowledged configuration.",
        )


@pytest.mark.asyncio
async def test_ingress_page_and_preflight_are_available(tmp_path) -> None:
    workflow = FakeWorkflow()
    app = create_app(
        config=AppConfig(
            workflow=WorkflowConfig("wlan0", "local_test_ap"),
            journal_path=tmp_path / "transaction.json",
        ),
        supervisor=SupervisorClient("test-token"),
        workflow=workflow,  # type: ignore[arg-type]
        journal=TransactionJournal(tmp_path / "transaction.json"),
        ingress_peer_ip="127.0.0.1",
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        page = await client.get("/")
        preflight = await client.get("/api/preflight")
        assert page.status == 200
        assert "Meross Provisioner" in await page.text()
        assert (await preflight.json())["preflight"]["ready"] is True
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_provision_job_does_not_return_wifi_password(tmp_path) -> None:
    workflow = FakeWorkflow()
    app = create_app(
        config=AppConfig(
            workflow=WorkflowConfig("wlan0", "local_test_ap"),
            journal_path=tmp_path / "transaction.json",
        ),
        supervisor=SupervisorClient("test-token"),
        workflow=workflow,  # type: ignore[arg-type]
        journal=TransactionJournal(tmp_path / "transaction.json"),
        ingress_peer_ip="127.0.0.1",
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    secret = "one-time-iot-password"
    try:
        response = await client.post(
            "/api/provision",
            json={
                "session_id": "test-session",
                "device_ssid": "Meross_SETUP",
                "device_bssid": "aa:bb:cc:dd:ee:ff",
                "target_ssid": "HA-AP",
                "target_password": secret,
            },
        )
        job_id = (await response.json())["job_id"]
        for _ in range(20):
            status_response = await client.get(f"/api/jobs/{job_id}")
            job = await status_response.json()
            if job["status"] != "running":
                break
            await asyncio.sleep(0.005)
        assert job["status"] == "succeeded"
        assert secret not in str(job)
        assert workflow.password_seen == secret
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_web_api_rejects_requests_that_bypass_ingress(tmp_path) -> None:
    workflow = FakeWorkflow()
    app = create_app(
        config=AppConfig(
            workflow=WorkflowConfig("wlan0", "local_test_ap"),
            journal_path=tmp_path / "transaction.json",
        ),
        supervisor=SupervisorClient("test-token"),
        workflow=workflow,  # type: ignore[arg-type]
        journal=TransactionJournal(tmp_path / "transaction.json"),
    )
    client = TestClient(TestServer(app, host="127.0.0.1"))
    await client.start_server()
    try:
        response = await client.get("/api/preflight")
        assert response.status == 403
    finally:
        await client.close()
