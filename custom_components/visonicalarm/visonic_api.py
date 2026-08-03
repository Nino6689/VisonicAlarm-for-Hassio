"""Client for the Visonic PowerManage REST API.

Vendored to replace the `visonicalarm2` PyPI package, whose upstream repository
(And3rsL/VisonicAlarm2) was archived in December 2025. Vendoring lets us fix the
session-expiry bug reported as And3rsL/VisonicAlarm2#16 and drops the
`python-dateutil==2.7.3` pin, which was downgrading dateutil inside the whole
Home Assistant container.

Differences from the original library:

* HTTP errors propagate. The original swallowed `HTTPError` inside its request
  helper and then returned `None`, so a 401 was indistinguishable from an empty
  response and `is_logged_in()` could never return False.
* `is_session_valid()` is a method that actually probes the API. The original
  exposed `System.is_token_valid` as a `@property` returning the *bound method*
  `API.is_logged_in` without calling it, so `is_token_valid == False` was always
  False and the reconnect path was dead code.
* Re-authentication is automatic and internal (`_request` retries once on 401).
* Adds the endpoints the original never implemented: /feature_set, /users,
  /panels, /cameras, /smart_devices.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

_LOGGER = logging.getLogger(__name__)

APP_TYPE = "com.visonic.PowerMaxApp"
USER_AGENT = "Visonic%20GO/2.8.62.91 CFNetwork/901.1 Darwin/17.6.0"
MIN_REST_VERSION = 8.0
TIMEOUT = 30


def _is_auth_failure(response) -> bool:
    """Whether a response means "your tokens are no longer good".

    PowerManage is inconsistent about this and the distinction matters, because
    only an auth failure should trigger a re-login:

    * an expired **user** token returns 401 "Wrong user token"
    * an unrecognised **session** token returns **400** with
      ``"error_reason_code": "InvalidRequestFormat"`` and a message naming the
      session token — verified against the live API, not documented anywhere

    Treating that 400 as a generic error is what left stale sessions needing a
    full Home Assistant restart.
    """
    if response.status_code in (401, 403):
        return True
    if response.status_code == 400:
        body = response.text.lower()
        return "token" in body and (
            "recognize" in body or "invalid" in body or "expired" in body
        )
    return False


class VisonicError(Exception):
    """Base error for the Visonic API."""


class VisonicAuthError(VisonicError):
    """Credentials or session rejected by the panel/cloud."""


class VisonicConnectionError(VisonicError):
    """The Visonic cloud could not be reached."""


class VisonicAPI:
    """Thin, synchronous client for one panel."""

    def __init__(
        self,
        hostname: str,
        app_id: str,
        user_code: str,
        user_email: str,
        user_password: str,
        panel_id: str,
        partition: str | int = -1,
    ) -> None:
        self._hostname = hostname
        self._app_id = app_id
        self._user_code = user_code
        self._user_email = user_email
        self._user_password = user_password
        self._panel_id = panel_id
        self._partition = partition

        self._session = requests.Session()
        self._user_token: str | None = None
        self._session_token: str | None = None
        self._rest_version: str | None = None
        self._base: str | None = None

    # -- plumbing ----------------------------------------------------------

    @property
    def rest_version(self) -> str | None:
        """REST API version negotiated with the server."""
        return self._rest_version

    def _headers(self, *, user_token: bool, session_token: bool) -> dict[str, str]:
        headers = {
            "Host": self._hostname,
            "Connection": "keep-alive",
            "Accept": "*/*",
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-us",
            "Accept-Encoding": "br, gzip, deflate",
        }
        if user_token and self._user_token:
            headers["User-Token"] = self._user_token
        if session_token and self._session_token:
            headers["Session-Token"] = self._session_token
        return headers

    def _raw(
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
        body = None
        if payload is not None:
            body = json.dumps(payload, separators=(",", ":"))
            headers["Content-Type"] = "application/json"

        try:
            response = self._session.request(
                method, url, data=body, headers=headers, timeout=TIMEOUT
            )
        except requests.exceptions.RequestException as err:
            raise VisonicConnectionError(f"{method} {url} failed: {err}") from err

        if _is_auth_failure(response):
            raise VisonicAuthError(
                f"{method} {url} rejected ({response.status_code}): "
                f"{response.text[:200]}"
            )
        if not response.ok:
            raise VisonicError(
                f"{method} {url} returned {response.status_code}: "
                f"{response.text[:200]}"
            )
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as err:
            raise VisonicError(f"{method} {url} returned non-JSON body") from err

    def _request(self, path: str, **kwargs: Any) -> Any:
        """Authenticated request that re-authenticates once on a 401.

        This is the fix for And3rsL/VisonicAlarm2#16: the cloud session expires
        after a period of uptime and the original library never noticed.
        """
        if self._base is None:
            self.connect()
        url = f"{self._base}/{path}"
        try:
            return self._raw("GET", url, **kwargs)
        except VisonicAuthError:
            _LOGGER.info("Visonic session expired, re-authenticating")
            self.connect()
            return self._raw("GET", f"{self._base}/{path}", **kwargs)

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        if self._base is None:
            self.connect()
        url = f"{self._base}/{path}"
        try:
            return self._raw("POST", url, payload=payload)
        except VisonicAuthError:
            _LOGGER.info("Visonic session expired, re-authenticating")
            self.connect()
            return self._raw("POST", f"{self._base}/{path}", payload=payload)

    # -- session -----------------------------------------------------------

    def connect(self) -> None:
        """Negotiate the API version and obtain user + session tokens."""
        versions = self._raw(
            "GET",
            f"https://{self._hostname}/rest_api/version",
            user_token=False,
            session_token=False,
        )
        rest_version = versions["rest_versions"][0]
        try:
            if float(rest_version) < MIN_REST_VERSION:
                raise VisonicError(
                    f"REST API {rest_version} is below the minimum "
                    f"{MIN_REST_VERSION}"
                )
        except (TypeError, ValueError) as err:
            raise VisonicError(f"Unusable REST version {rest_version!r}") from err

        self._rest_version = rest_version
        self._base = f"https://{self._hostname}/rest_api/{rest_version}"

        auth = self._raw(
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

        panel = self._raw(
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

    def is_session_valid(self) -> bool:
        """Probe the API to see whether the current session still works.

        Unlike the original `is_token_valid` property this actually performs the
        call and reports the result.
        """
        if self._session_token is None:
            return False
        try:
            self._raw("GET", f"{self._base}/status")
        except VisonicAuthError:
            return False
        except VisonicError:
            # Reachability problems are not an authentication verdict.
            return True
        return True

    # -- read-only endpoints ----------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """Partition states, cloud connectivity and discovery progress."""
        return self._request("status")

    def get_panel_info(self) -> dict[str, Any]:
        """Static panel identity, supported state sets and feature flags."""
        return self._request("panel_info")

    def get_devices(self) -> list[dict[str, Any]]:
        """Every enrolled device, including ones with no zone."""
        return self._request("devices")

    def get_alarms(self) -> list[dict[str, Any]]:
        """Currently active alarms."""
        return self._request("alarms")

    def get_troubles(self) -> list[dict[str, Any]]:
        """Active trouble conditions (offline, tamper, low battery...)."""
        return self._request("troubles")

    def get_alerts(self) -> list[dict[str, Any]]:
        """Active alerts."""
        return self._request("alerts")

    def get_events(self) -> list[dict[str, Any]]:
        """Panel event log, oldest first."""
        return self._request("events")

    def get_locations(self) -> list[dict[str, Any]]:
        """Catalogue of assignable location labels."""
        return self._request("locations")

    def get_wakeup_sms(self) -> dict[str, Any]:
        """Number and message body used to wake a sleeping panel."""
        return self._request("wakeup_sms")

    # Endpoints the original library never implemented.

    def get_feature_set(self) -> dict[str, Any]:
        """Capability matrix: partitions, sirens, enrollable device types."""
        return self._request("feature_set")

    def get_users(self) -> dict[str, Any]:
        """Enrolled users and their partitions."""
        return self._request("users")

    def get_panels(self) -> list[dict[str, Any]]:
        """Panels visible to this account, with the account-level alias."""
        return self._request("panels")

    def get_cameras(self) -> list[dict[str, Any]]:
        """Enrolled cameras."""
        return self._request("cameras")

    def get_smart_devices(self) -> list[dict[str, Any]]:
        """Enrolled smart-home devices."""
        return self._request("smart_devices")

    def get_process_status(self, token: str) -> Any:
        """Progress of an arm/disarm command."""
        result = self._request(f"process_status?process_tokens={token}")
        return result[0] if result else None

    # -- commands ----------------------------------------------------------

    def set_state(self, state: str) -> Any:
        """Arm or disarm. `state` is one of HOME, AWAY, DISARM."""
        return self._post(
            "set_state",
            {"partition": -1, "state": state, "code": self._user_code},
        )
