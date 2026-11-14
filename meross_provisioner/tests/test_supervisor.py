from __future__ import annotations

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from meross_provisioner.errors import ConfigurationError, SupervisorError
from meross_provisioner.supervisor import SupervisorClient


@pytest.mark.asyncio
async def test_supervisor_client_unwraps_success_response() -> None:
    async def network_info(_: web.Request) -> web.Response:
        return web.json_response(
            {"result": "ok", "data": {"interfaces": [{"interface": "eth0"}]}}
        )

    app = web.Application()
    app.router.add_get("/network/info", network_info)
    server = TestServer(app)
    await server.start_server()
    client = SupervisorClient(
        "test-token", base_url=str(server.make_url("")).rstrip("/")
    )
    try:
        result = await client.get_network_info()
    finally:
        await client.close()
        await server.close()

    assert result == {"interfaces": [{"interface": "eth0"}]}


@pytest.mark.asyncio
async def test_supervisor_error_message_is_sanitized() -> None:
    async def fail(_: web.Request) -> web.Response:
        return web.json_response(
            {"result": "error", "message": "sensitive value"}, status=400
        )

    app = web.Application()
    app.router.add_get("/network/info", fail)
    server = TestServer(app)
    await server.start_server()
    client = SupervisorClient(
        "test-token", base_url=str(server.make_url("")).rstrip("/")
    )
    try:
        with pytest.raises(SupervisorError) as error:
            await client.get_network_info()
    finally:
        await client.close()
        await server.close()

    assert "sensitive value" not in str(error.value)


def test_supervisor_client_requires_token() -> None:
    with pytest.raises(ConfigurationError):
        SupervisorClient(None)
