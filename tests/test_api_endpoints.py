"""Every endpoint wrapper and write command, against a stub server."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from aiohttp import web
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.visonicalarm.api import VisonicApi, VisonicError

# path -> canned body
READ_ENDPOINTS: dict[str, Any] = {
    "status": {"connected": True},
    "panel_info": {"serial": "S1"},
    "devices": [{"id": 1}],
    "alarms": [],
    "troubles": [{"trouble_type": "INACTIVE"}],
    "alerts": [],
    "events": [{"type_id": 173}],
    "locations": [{"name": "Loft"}],
    "wakeup_sms": {"phone": None},
    "feature_set": {"events": {"is_enabled": True}},
    "users": {"users": []},
    "panels": [{"alias": "House"}],
    "cameras": [],
    "smart_devices": [],
    "home_automation_devices": [],
    "notifications/email": {"mode": 1},
}

WRITE_ENDPOINTS = ("set_state", "set_bypass_zone", "activate_siren", "disable_siren", "set_name")


def _wire_handshake(app: web.Application) -> None:
    """Add the version/auth/panel-login routes every stub server needs."""

    async def version(_r: web.Request) -> web.Response:
        return web.json_response({"rest_versions": ["14.0"]})

    async def auth(_r: web.Request) -> web.Response:
        return web.json_response({"user_token": "ut"})

    async def panel_login(_r: web.Request) -> web.Response:
        return web.json_response({"session_token": "st"})

    app.router.add_get("/rest_api/version", version)
    app.router.add_post("/rest_api/14.0/auth", auth)
    app.router.add_post("/rest_api/14.0/panel/login", panel_login)


@pytest.fixture(autouse=True)
def _plain_http():
    """Point the client at http:// so a local stub server can be used."""
    with patch("custom_components.visonicalarm.api.SCHEME", "http"):
        yield


@pytest.fixture
async def server(hass: HomeAssistant, aiohttp_server, socket_enabled):
    """Stub PowerManage exposing every endpoint the client knows about."""
    posted: list[tuple[str, dict[str, Any]]] = []

    app = web.Application()
    _wire_handshake(app)

    def reader(body: Any):
        async def handler(_r: web.Request) -> web.Response:
            return web.json_response(body)

        return handler

    for path, body in READ_ENDPOINTS.items():
        app.router.add_get(f"/rest_api/14.0/{path}", reader(body))

    async def record(request: web.Request) -> web.Response:
        posted.append((request.path.rsplit("/", 1)[-1], await request.json()))
        return web.json_response({"ok": True})

    for path in WRITE_ENDPOINTS:
        app.router.add_post(f"/rest_api/14.0/{path}", record)

    app.router.add_get("/rest_api/14.0/process_status", reader([{"status": "ok"}]))

    async def empty(_r: web.Request) -> web.Response:
        """204 No Content: the client must return None, not raise."""
        return web.Response(status=204)

    app.router.add_get("/rest_api/14.0/empty", empty)

    srv = await aiohttp_server(app)
    return srv, posted


def _client(hass: HomeAssistant, srv) -> VisonicApi:
    return VisonicApi(
        async_get_clientsession(hass),
        f"{srv.host}:{srv.port}",
        "app",
        "1234",
        "u@e.com",
        "pw",
        "S1",
    )


async def test_every_read_endpoint(hass: HomeAssistant, server) -> None:
    """All read wrappers return their payload unchanged."""
    srv, _ = server
    api = _client(hass, srv)
    await api.async_connect()
    assert api.rest_version == "14.0"

    assert await api.async_get_status() == READ_ENDPOINTS["status"]
    assert await api.async_get_panel_info() == READ_ENDPOINTS["panel_info"]
    assert await api.async_get_devices() == READ_ENDPOINTS["devices"]
    assert await api.async_get_alarms() == []
    assert await api.async_get_troubles() == READ_ENDPOINTS["troubles"]
    assert await api.async_get_alerts() == []
    assert await api.async_get_events() == READ_ENDPOINTS["events"]
    assert await api.async_get_locations() == READ_ENDPOINTS["locations"]
    assert await api.async_get_wakeup_sms() == READ_ENDPOINTS["wakeup_sms"]
    assert await api.async_get_feature_set() == READ_ENDPOINTS["feature_set"]
    assert await api.async_get_users() == READ_ENDPOINTS["users"]
    assert await api.async_get_panels() == READ_ENDPOINTS["panels"]
    assert await api.async_get_cameras() == []
    assert await api.async_get_smart_devices() == []
    assert await api.async_get_home_automation_devices() == []
    assert await api.async_get_email_notifications() == {"mode": 1}
    assert await api.async_get_process_status("tok") == {"status": "ok"}


async def test_write_commands_send_the_right_payloads(hass: HomeAssistant, server) -> None:
    """Payload shapes match what PowerManage expects."""
    srv, posted = server
    api = _client(hass, srv)
    await api.async_connect()

    await api.async_set_state("AWAY")
    await api.async_set_bypass_zone(5, True)
    await api.async_activate_siren()
    await api.async_disable_siren("all")
    await api.async_set_name("zone", 5, "Scullery")

    assert posted[0] == ("set_state", {"partition": -1, "state": "AWAY", "code": "1234"})
    # ⚠️ zone is the panel zone number, not the device id.
    assert posted[1] == ("set_bypass_zone", {"zone": 5, "set": True})
    assert posted[2] == ("activate_siren", {})
    assert posted[3] == ("disable_siren", {"mode": "all"})
    assert posted[4] == ("set_name", {"class": "zone", "id": 5, "name": "Scullery"})


async def test_lazy_connect_on_first_request(hass: HomeAssistant, server) -> None:
    """A request before connect() authenticates first rather than failing."""
    srv, _ = server
    api = _client(hass, srv)
    assert await api.async_get_status() == {"connected": True}


async def test_lazy_connect_on_first_post(hass: HomeAssistant, server) -> None:
    """The same holds for write commands."""
    srv, posted = server
    api = _client(hass, srv)
    await api.async_set_state("DISARM")
    assert posted[0][0] == "set_state"


async def test_empty_body_returns_none(hass: HomeAssistant, server) -> None:
    """A 204 is not an error."""
    srv, _ = server
    api = _client(hass, srv)
    await api.async_connect()
    assert await api._request("empty") is None  # noqa: SLF001


async def test_process_status_handles_empty(hass: HomeAssistant, server) -> None:
    """An empty process list yields None rather than IndexError."""
    srv, _ = server
    api = _client(hass, srv)
    await api.async_connect()
    with patch.object(api, "_request", return_value=[]):
        assert await api.async_get_process_status("tok") is None


async def test_post_retries_after_auth_failure(
    hass: HomeAssistant, aiohttp_server, socket_enabled
) -> None:
    """A rejected session on a POST re-authenticates and retries once."""
    state = {"auth": 0, "reject": True}

    async def auth(_r: web.Request) -> web.Response:
        state["auth"] += 1
        return web.json_response({"user_token": "ut"})

    async def set_state(_r: web.Request) -> web.Response:
        if state["reject"]:
            state["reject"] = False
            return web.json_response(
                {"error_message": "Unable to recognize session token"}, status=400
            )
        return web.json_response({"ok": True})

    async def version(_r: web.Request) -> web.Response:
        return web.json_response({"rest_versions": ["14.0"]})

    async def panel_login(_r: web.Request) -> web.Response:
        return web.json_response({"session_token": "st"})

    app = web.Application()
    app.router.add_get("/rest_api/version", version)
    app.router.add_post("/rest_api/14.0/auth", auth)
    app.router.add_post("/rest_api/14.0/panel/login", panel_login)
    app.router.add_post("/rest_api/14.0/set_state", set_state)
    srv = await aiohttp_server(app)

    api = _client(hass, srv)
    await api.async_connect()
    assert await api.async_set_state("AWAY") == {"ok": True}
    assert state["auth"] == 2


async def test_missing_rest_version(hass: HomeAssistant, aiohttp_server, socket_enabled) -> None:
    """A server that advertises nothing usable is rejected clearly."""

    async def version(_r: web.Request) -> web.Response:
        return web.json_response({})

    app = web.Application()
    app.router.add_get("/rest_api/version", version)
    srv = await aiohttp_server(app)

    api = _client(hass, srv)
    with pytest.raises(VisonicError, match="REST version"):
        await api.async_connect()


async def test_non_numeric_rest_version(
    hass: HomeAssistant, aiohttp_server, socket_enabled
) -> None:
    """A non-numeric version string is rejected rather than compared."""

    async def version(_r: web.Request) -> web.Response:
        return web.json_response({"rest_versions": ["beta"]})

    app = web.Application()
    app.router.add_get("/rest_api/version", version)
    srv = await aiohttp_server(app)

    api = _client(hass, srv)
    with pytest.raises(VisonicError, match="Unusable"):
        await api.async_connect()
