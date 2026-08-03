"""Async client for the Visonic PowerManage REST API.

Vendored to replace the `visonicalarm2` PyPI package, whose upstream repository
(``And3rsL/VisonicAlarm2``) was archived in December 2025 alongside the
integration itself. Vendoring is what makes it possible to fix the session
handling and to drop the ``python-dateutil==2.7.3`` pin, which was downgrading
dateutil for every other integration in the container.

The client is fully async and takes an injected :class:`aiohttp.ClientSession`
so it shares Home Assistant's connection pool.

Behaviour worth knowing, all established against the live API:

* PowerManage returns **400**, not 401, for an unrecognised *session* token
  (``"Unable to recognize session token"``). An expired *user* token gives 401.
  Both mean "re-authenticate", and only checking 401 silently fails.
* The original library swallowed ``HTTPError`` inside its request helper and
  returned ``None``, so a 401 was indistinguishable from an empty response and
  its ``is_logged_in()`` could never return False.
* ``System.is_token_valid`` was a ``@property`` returning the *bound method*
  ``API.is_logged_in`` without calling it, so ``is_token_valid == False`` was
  always False and the reconnect branch was dead code.
"""

from __future__ import annotations

import logging
from typing import Any, Final

import aiohttp

_LOGGER = logging.getLogger(__name__)

APP_TYPE: Final = "com.visonic.PowerMaxApp"
USER_AGENT: Final = "Visonic%20GO/2.8.62.91 CFNetwork/901.1 Darwin/17.6.0"
MIN_REST_VERSION: Final = 8.0
TIMEOUT: Final = aiohttp.ClientTimeout(total=30)
# PowerManage is HTTPS everywhere; kept as a constant so tests can point the
# client at a local stub server.
SCHEME: Final = "https"


class VisonicError(Exception):
    """Base error for the Visonic API."""


class VisonicAuthError(VisonicError):
    """Credentials or session rejected by the panel or cloud."""


class VisonicConnectionError(VisonicError):
    """The Visonic cloud could not be reached."""


def _is_auth_failure(status: int, body: str) -> bool:
    """Whether a response means the tokens are no longer good.

    See the module docstring: the 400 case is undocumented and was found by
    probing the live API with a deliberately corrupted session token.
    """
    if status in (401, 403):
        return True
    if status == 400:
        lowered = body.lower()
        return "token" in lowered and any(
            word in lowered for word in ("recognize", "invalid", "expired")
        )
    return False


class VisonicApi:
    """Thin async client for one PowerManage panel."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        hostname: str,
        app_id: str,
        user_code: str,
        user_email: str,
        user_password: str,
        panel_id: str,
    ) -> None:
        """Initialise the client. No I/O happens here."""
        self._session = session
        self._hostname = hostname
        self._app_id = app_id
        self._user_code = user_code
        self._user_email = user_email
        self._user_password = user_password
        self._panel_id = panel_id

        self._user_token: str | None = None
        self._session_token: str | None = None
        self._rest_version: str | None = None
        self._base: str | None = None

    @property
    def rest_version(self) -> str | None:
        """REST API version negotiated with the server."""
        return self._rest_version

    # -- plumbing ----------------------------------------------------------

    def _headers(self, *, user_token: bool, session_token: bool) -> dict[str, str]:
        headers = {
            "Host": self._hostname,
            "Accept": "*/*",
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-us",
        }
        if user_token and self._user_token:
            headers["User-Token"] = self._user_token
        if session_token and self._session_token:
            headers["Session-Token"] = self._session_token
        return headers

    async def _raw(
        self,
        method: str,
        url: str,
        *,
        payload: dict[str, Any] | None = None,
        user_token: bool = True,
        session_token: bool = True,
    ) -> Any:
        """One HTTP round trip. Raises on any non-2xx; never returns None."""
        headers = self._headers(user_token=user_token, session_token=session_token)
        if payload is not None:
            headers["Content-Type"] = "application/json"

        try:
            async with self._session.request(
                method, url, json=payload, headers=headers, timeout=TIMEOUT
            ) as response:
                body = await response.text()
                if _is_auth_failure(response.status, body):
                    raise VisonicAuthError(
                        f"{method} {url} rejected ({response.status}): {body[:200]}"
                    )
                if response.status >= 400:
                    raise VisonicError(f"{method} {url} returned {response.status}: {body[:200]}")
                if not body:
                    return None
                try:
                    return await response.json(content_type=None)
                except ValueError as err:
                    raise VisonicError(f"{method} {url} returned a non-JSON body") from err
        except aiohttp.ClientError as err:
            raise VisonicConnectionError(f"{method} {url} failed: {err}") from err
        except TimeoutError as err:
            raise VisonicConnectionError(f"{method} {url} timed out") from err

    async def _request(self, path: str) -> Any:
        """Send an authenticated GET, re-authenticating once on an auth failure.

        This is the fix for ``And3rsL/VisonicAlarm2#16``: the cloud session
        expires after a period of uptime and the original library never noticed,
        so recovery needed a full Home Assistant restart.
        """
        if self._base is None:
            await self.async_connect()
        try:
            return await self._raw("GET", f"{self._base}/{path}")
        except VisonicAuthError:
            _LOGGER.debug("Visonic session expired, re-authenticating")
            await self.async_connect()
            return await self._raw("GET", f"{self._base}/{path}")

    async def _post(self, path: str, payload: dict[str, Any]) -> Any:
        if self._base is None:
            await self.async_connect()
        try:
            return await self._raw("POST", f"{self._base}/{path}", payload=payload)
        except VisonicAuthError:
            _LOGGER.debug("Visonic session expired, re-authenticating")
            await self.async_connect()
            return await self._raw("POST", f"{self._base}/{path}", payload=payload)

    # -- session -----------------------------------------------------------

    async def async_connect(self) -> None:
        """Negotiate the API version and obtain user and session tokens."""
        versions = await self._raw(
            "GET",
            f"{SCHEME}://{self._hostname}/rest_api/version",
            user_token=False,
            session_token=False,
        )
        try:
            rest_version = versions["rest_versions"][0]
        except (KeyError, IndexError, TypeError) as err:
            raise VisonicError("Server did not advertise a REST version") from err

        try:
            if float(rest_version) < MIN_REST_VERSION:
                raise VisonicError(
                    f"REST API {rest_version} is below the minimum {MIN_REST_VERSION}"
                )
        except (TypeError, ValueError) as err:
            raise VisonicError(f"Unusable REST version {rest_version!r}") from err

        self._rest_version = rest_version
        self._base = f"{SCHEME}://{self._hostname}/rest_api/{rest_version}"

        auth = await self._raw(
            "POST",
            f"{self._base}/auth",
            payload={
                "email": self._user_email,
                "password": self._user_password,
                "app_id": self._app_id,
            },
            user_token=False,
            session_token=False,
        )
        self._user_token = auth["user_token"]

        panel = await self._raw(
            "POST",
            f"{self._base}/panel/login",
            payload={
                "user_code": self._user_code,
                "app_type": APP_TYPE,
                "app_id": self._app_id,
                "panel_serial": self._panel_id,
            },
            session_token=False,
        )
        self._session_token = panel["session_token"]
        _LOGGER.debug("Visonic session established (REST %s)", rest_version)

    async def async_is_session_valid(self) -> bool:
        """Probe the API to see whether the current session still works."""
        if self._session_token is None:
            return False
        try:
            await self._raw("GET", f"{self._base}/status")
        except VisonicAuthError:
            return False
        except VisonicError:
            # Reachability problems are not an authentication verdict.
            return True
        return True

    # -- read-only endpoints ----------------------------------------------

    async def async_get_status(self) -> dict[str, Any]:
        """Partition states, cloud connectivity and discovery progress."""
        return await self._request("status")  # type: ignore[no-any-return]

    async def async_get_panel_info(self) -> dict[str, Any]:
        """Return static panel identity, state sets and feature flags."""
        return await self._request("panel_info")  # type: ignore[no-any-return]

    async def async_get_devices(self) -> list[dict[str, Any]]:
        """Every enrolled device.

        The ``traits`` object on each device is **empty while the panel is
        offline**; when the panel is reporting it carries the room label, bypass
        and soak flags, an RF survey and an enrollment id.
        """
        return await self._request("devices")  # type: ignore[no-any-return]

    async def async_get_alarms(self) -> list[dict[str, Any]]:
        """Return currently active alarms."""
        return await self._request("alarms")  # type: ignore[no-any-return]

    async def async_get_troubles(self) -> list[dict[str, Any]]:
        """Active trouble conditions (offline, tamper, low battery, inactive)."""
        return await self._request("troubles")  # type: ignore[no-any-return]

    async def async_get_alerts(self) -> list[dict[str, Any]]:
        """Active alerts."""
        return await self._request("alerts")  # type: ignore[no-any-return]

    async def async_get_events(self) -> list[dict[str, Any]]:
        """Panel event log, oldest first.

        Query parameters are ignored by the API; the server decides how many
        events to return.
        """
        return await self._request("events")  # type: ignore[no-any-return]

    async def async_get_locations(self) -> list[dict[str, Any]]:
        """Catalogue of assignable location labels."""
        return await self._request("locations")  # type: ignore[no-any-return]

    async def async_get_wakeup_sms(self) -> dict[str, Any]:
        """Return the number and message body used to wake a sleeping panel."""
        return await self._request("wakeup_sms")  # type: ignore[no-any-return]

    # Endpoints the original library never implemented.

    async def async_get_feature_set(self) -> dict[str, Any]:
        """Capability matrix: partitions, sirens, enrollable device types."""
        return await self._request("feature_set")  # type: ignore[no-any-return]

    async def async_get_users(self) -> dict[str, Any]:
        """Enrolled users and their partitions."""
        return await self._request("users")  # type: ignore[no-any-return]

    async def async_get_panels(self) -> list[dict[str, Any]]:
        """Panels visible to this account, with the account-level alias."""
        return await self._request("panels")  # type: ignore[no-any-return]

    async def async_get_cameras(self) -> list[dict[str, Any]]:
        """Enrolled cameras."""
        return await self._request("cameras")  # type: ignore[no-any-return]

    async def async_get_smart_devices(self) -> list[dict[str, Any]]:
        """Enrolled smart-home devices."""
        return await self._request("smart_devices")  # type: ignore[no-any-return]

    async def async_get_home_automation_devices(self) -> list[dict[str, Any]]:
        """Enrolled home-automation devices (PGM outputs, plugs)."""
        return await self._request("home_automation_devices")  # type: ignore[no-any-return]

    async def async_get_email_notifications(self) -> dict[str, Any]:
        """Email notification settings, as a bitmask plus recipient mode."""
        return await self._request("notifications/email")  # type: ignore[no-any-return]

    async def async_get_process_status(self, token: str) -> Any:
        """Progress of a previously issued arm or disarm command."""
        result = await self._request(f"process_status?process_tokens={token}")
        return result[0] if result else None

    # -- commands ----------------------------------------------------------

    async def async_set_state(self, state: str, partition: int = -1) -> Any:
        """Arm or disarm. ``state`` is one of HOME, AWAY, DISARM."""
        return await self._post(
            "set_state",
            {"partition": partition, "state": state, "code": self._user_code},
        )

    async def async_set_bypass_zone(self, zone: int, enabled: bool) -> Any:
        """Bypass or unbypass a zone.

        ``zone`` is the panel's zone *number* (``device_number`` on the device
        payload), not the device id.
        """
        return await self._post("set_bypass_zone", {"zone": zone, "set": enabled})

    async def async_activate_siren(self) -> Any:
        """Sound the siren — a panic alarm.

        Only offered when ``panel_info.features.enabling_siren`` is set.
        """
        return await self._post("activate_siren", {})

    async def async_disable_siren(self, mode: str = "all") -> Any:
        """Silence a sounding siren."""
        return await self._post("disable_siren", {"mode": mode})

    async def async_set_name(self, object_class: str, object_id: int, name: str) -> Any:
        """Rename an object on the panel, e.g. a zone."""
        return await self._post("set_name", {"class": object_class, "id": object_id, "name": name})
