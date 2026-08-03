"""Transport-layer tests for the vendored API client."""

from __future__ import annotations

from unittest.mock import patch

import aiohttp
import pytest
from aiohttp import web
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.visonicalarm.api import (  # noqa: I001
    VisonicApi,
    VisonicConnectionError,
    VisonicError,
    _is_auth_failure,
)


def test_auth_failure_detection() -> None:
    """⚠️ PowerManage returns 400, not 401, for a bad *session* token.

    This is undocumented and was established against the live API. Only
    checking 401 is what left stale sessions needing a restart.
    """
    assert _is_auth_failure(401, "Wrong user token")
    assert _is_auth_failure(403, "forbidden")
    assert _is_auth_failure(
        400,
        '{"error":400,"error_message":"Unable to recognize session token",'
        '"error_reason_code":"InvalidRequestFormat"}',
    )
    # A 400 that is not about tokens must stay a plain error.
    assert not _is_auth_failure(400, '{"error_message":"Bad zone number"}')
    assert not _is_auth_failure(500, "server exploded")
    assert not _is_auth_failure(200, "fine")


@pytest.fixture(autouse=True)
def _plain_http():
    """Point the client at http:// so a local stub server can be used."""
    with patch("custom_components.visonicalarm.api.SCHEME", "http"):
        yield


@pytest.fixture
async def api_server(hass: HomeAssistant, aiohttp_server, socket_enabled):
    """Run a stub PowerManage server."""
    state = {"auth_calls": 0, "status_calls": 0, "reject_session": False}

    async def version(_request: web.Request) -> web.Response:
        return web.json_response({"rest_versions": ["14.0"]})

    async def auth(_request: web.Request) -> web.Response:
        state["auth_calls"] += 1
        return web.json_response({"user_token": "ut"})

    async def panel_login(_request: web.Request) -> web.Response:
        return web.json_response({"session_token": "st"})

    async def status(_request: web.Request) -> web.Response:
        state["status_calls"] += 1
        if state["reject_session"]:
            state["reject_session"] = False
            return web.json_response(
                {"error_message": "Unable to recognize session token"}, status=400
            )
        return web.json_response({"connected": True})

    async def boom(_request: web.Request) -> web.Response:
        return web.json_response({"error": "nope"}, status=500)

    async def not_json(_request: web.Request) -> web.Response:
        return web.Response(text="<html>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/rest_api/version", version)
    app.router.add_post("/rest_api/14.0/auth", auth)
    app.router.add_post("/rest_api/14.0/panel/login", panel_login)
    app.router.add_get("/rest_api/14.0/status", status)
    app.router.add_get("/rest_api/14.0/alarms", boom)
    app.router.add_get("/rest_api/14.0/alerts", not_json)
    server = await aiohttp_server(app)
    return server, state


def _client(hass: HomeAssistant, server) -> VisonicApi:
    """Build a client pointed at the local stub server (plain HTTP)."""
    api = VisonicApi(
        async_get_clientsession(hass),
        f"{server.host}:{server.port}",
        "app",
        "1234",
        "user@example.com",
        "pw",
        "1D0B0A",
    )
    return api


async def test_session_self_heals(hass: HomeAssistant, api_server) -> None:
    """A rejected session re-authenticates and retries once.

    This is the fix for And3rsL/VisonicAlarm2#16.
    """
    server, state = api_server
    api = _client(hass, server)
    await api.async_connect()
    assert state["auth_calls"] == 1

    state["reject_session"] = True
    result = await api.async_get_status()

    assert result == {"connected": True}
    assert state["auth_calls"] == 2  # re-authenticated
    assert state["status_calls"] == 2  # and retried


async def test_is_session_valid(hass: HomeAssistant, api_server) -> None:
    """Validity is probed, not inferred from a bound method."""
    server, state = api_server
    api = _client(hass, server)
    assert await api.async_is_session_valid() is False  # no token yet

    await api.async_connect()
    assert await api.async_is_session_valid() is True

    state["reject_session"] = True
    assert await api.async_is_session_valid() is False


async def test_http_error_propagates(hass: HomeAssistant, api_server) -> None:
    """A 500 is an error, not a silent None."""
    server, _ = api_server
    api = _client(hass, server)
    await api.async_connect()
    with pytest.raises(VisonicError):
        await api.async_get_alarms()


async def test_non_json_body_is_an_error(hass: HomeAssistant, api_server) -> None:
    """An HTML error page must not be mistaken for data."""
    server, _ = api_server
    api = _client(hass, server)
    await api.async_connect()
    with pytest.raises(VisonicError):
        await api.async_get_alerts()


async def test_connection_error(hass: HomeAssistant) -> None:
    """A transport failure raises VisonicConnectionError, not a raw aiohttp error."""
    session = async_get_clientsession(hass)
    api = VisonicApi(session, "unreachable.invalid", "app", "1234", "u@e.com", "pw", "S")

    with (
        patch.object(session, "request", side_effect=aiohttp.ClientError("boom")),
        pytest.raises(VisonicConnectionError),
    ):
        await api.async_connect()


async def test_timeout_is_a_connection_error(hass: HomeAssistant) -> None:
    """A timeout is reported as a connection problem."""
    session = async_get_clientsession(hass)
    api = VisonicApi(session, "slow.invalid", "app", "1234", "u@e.com", "pw", "S")

    with (
        patch.object(session, "request", side_effect=TimeoutError),
        pytest.raises(VisonicConnectionError),
    ):
        await api.async_connect()


async def test_rejects_old_rest_version(
    hass: HomeAssistant, aiohttp_server, socket_enabled
) -> None:
    """Servers below REST 8.0 are refused rather than half-supported."""

    async def version(_request: web.Request) -> web.Response:
        return web.json_response({"rest_versions": ["4.0"]})

    app = web.Application()
    app.router.add_get("/rest_api/version", version)
    server = await aiohttp_server(app)

    api = VisonicApi(
        async_get_clientsession(hass),
        f"{server.host}:{server.port}",
        "app",
        "1234",
        "u@e.com",
        "pw",
        "S",
    )
    with pytest.raises(VisonicError):
        await api.async_connect()
