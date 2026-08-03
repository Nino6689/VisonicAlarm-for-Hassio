"""Support for Visonic Alarm components.

Configuration stays YAML-based (`visonicalarm:` in configuration.yaml) so that
existing entity IDs and automations keep working. The panel client lives in
`visonic_api.py`; this module owns the polling hub and the shared snapshot the
platforms read from.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.helpers import discovery
from homeassistant.util import Throttle

from .visonic_api import VisonicAPI, VisonicAuthError, VisonicError

_LOGGER = logging.getLogger(__name__)

CONF_NO_PIN_REQUIRED = "no_pin_required"
CONF_USER_CODE = "user_code"
CONF_APP_ID = "app_id"
CONF_USER_EMAIL = "user_email"
CONF_USER_PASSWORD = "user_password"
CONF_PANEL_ID = "panel_id"
CONF_PARTITION = "partition"
CONF_EVENT_HOUR_OFFSET = "event_hour_offset"

DEFAULT_NAME = "Visonic Alarm"
DEFAULT_PARTITION = "ALL"

DOMAIN = "visonicalarm"
PLATFORMS = ("sensor", "binary_sensor", "alarm_control_panel")

# The cloud is polled no faster than this regardless of platform SCAN_INTERVALs.
MIN_UPDATE_INTERVAL = timedelta(seconds=10)
# Slow-moving endpoints are refreshed on their own, longer cadence.
SLOW_UPDATE_INTERVAL = timedelta(minutes=5)

HUB = None

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_HOST): cv.string,
                vol.Required(CONF_APP_ID): cv.string,
                vol.Required(CONF_USER_CODE): cv.string,
                vol.Required(CONF_USER_EMAIL): cv.string,
                vol.Required(CONF_USER_PASSWORD): cv.string,
                vol.Required(CONF_PANEL_ID): cv.string,
                vol.Optional(CONF_PARTITION, default=DEFAULT_PARTITION): cv.string,
                vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
                vol.Optional(CONF_NO_PIN_REQUIRED, default=False): cv.boolean,
                vol.Optional(CONF_EVENT_HOUR_OFFSET, default=0): vol.All(
                    vol.Coerce(int), vol.Range(min=-24, max=24)
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


def setup(hass, config):
    """Set up the Visonic Alarm component."""
    global HUB  # noqa: PLW0603 - platform modules import this by name
    HUB = VisonicAlarmHub(config[DOMAIN])
    if not HUB.connect():
        return False

    HUB.update()

    for platform in PLATFORMS:
        discovery.load_platform(hass, platform, DOMAIN, {}, config)

    return True


class Device:
    """One enrolled device, as reported by /devices."""

    def __init__(self, raw: dict) -> None:
        self._raw = raw

    @property
    def id(self):
        return self._raw.get("id")

    @property
    def name(self):
        return self._raw.get("name")

    @property
    def zone(self):
        # The API calls it zone_type; the original library exposed it as `zone`
        # and the sensor platform matches on substrings of it.
        return self._raw.get("zone_type") or ""

    @property
    def device_type(self):
        return self._raw.get("device_type")

    @property
    def device_number(self):
        return self._raw.get("device_number")

    @property
    def subtype(self):
        return self._raw.get("subtype")

    @property
    def warnings(self):
        return self._raw.get("warnings")

    @property
    def partitions(self):
        return self._raw.get("partitions")

    @property
    def traits(self):
        """Per-device metadata. Only populated while the panel is online."""
        return self._raw.get("traits") or {}

    @property
    def location(self):
        """Room label, e.g. "Living room".

        Lives under `traits.location.name`, not at the top level. Most devices
        have an empty `name`, so this is the only human-readable label available
        and it is what the entities are named from.
        """
        return (self.traits.get("location") or {}).get("name") or None

    @property
    def enrollment_id(self):
        """Enrollment code, e.g. "120-0918". The prefix encodes device type."""
        return self._raw.get("enrollment_id")

    @property
    def bypassed(self):
        """Whether this zone is currently bypassed (excluded from arming)."""
        return (self.traits.get("bypass") or {}).get("enabled")

    @property
    def soak(self):
        """Whether the zone is in soak-test mode (reports but never alarms)."""
        return (self.traits.get("soak") or {}).get("enabled")

    @property
    def rssi(self):
        """Stored RF survey for this device.

        NOTE: `last_updated` is the time of the last survey, not a live reading -
        every device on this panel reports the same enrollment-time timestamp.
        Treat signal as static metadata, not telemetry.
        """
        return self.traits.get("rssi") or {}

    @property
    def fault_types(self):
        """Active warning types on this device, e.g. ['INACTIVE', '1_WAY']."""
        return [w.get("type") for w in (self.warnings or []) if isinstance(w, dict)]

    @property
    def state(self):
        """Contact state derived from device warnings.

        Only contact-style devices report a real state. Motion detectors expose
        nothing usable here, which is why the sensor platform infers their state
        from the arm mode instead.
        """
        subtype = self.subtype or ""
        if "CONTACT" in subtype or "KEYFOB" in subtype:
            if self.warnings and "OPENED" in str(self.warnings):
                return "opened"
            return "closed"
        return None


class VisonicSystem:
    """Snapshot of the alarm system, refreshed by the hub."""

    def __init__(self, api: VisonicAPI) -> None:
        self._api = api
        self._devices: list[Device] = []
        self._state = None
        self._ready = None
        self._connected = None
        self._alarm = False
        self._serial = None
        self._model = None
        self._panel_info: dict = {}
        self._status: dict = {}
        self._troubles: list = []
        self._alerts: list = []
        self._alarms: list = []
        self._events: list = []
        self._panels: list = []
        self._feature_set: dict = {}
        self._users: dict = {}

    # -- identity ----------------------------------------------------------

    @property
    def serial_number(self):
        return self._serial

    @property
    def model(self):
        return self._model

    @property
    def alias(self):
        """Account-level panel name, e.g. the street address."""
        if self._panels:
            return self._panels[0].get("alias")
        return None

    @property
    def rest_version(self):
        return self._api.rest_version

    # -- live state --------------------------------------------------------

    @property
    def state(self):
        return self._state

    @property
    def ready(self):
        return self._ready

    @property
    def connected(self):
        """True when the panel is reachable by the Visonic cloud."""
        return self._connected

    @property
    def alarm(self):
        return self._alarm

    @property
    def devices(self):
        return self._devices

    @property
    def troubles(self):
        return self._troubles

    @property
    def alerts(self):
        return self._alerts

    @property
    def alarms(self):
        return self._alarms

    @property
    def events(self):
        return self._events

    @property
    def status(self):
        return self._status

    @property
    def panel_info(self):
        return self._panel_info

    @property
    def feature_set(self):
        return self._feature_set

    @property
    def users(self):
        return self._users

    @property
    def connection_detail(self):
        """Per-transport connectivity, e.g. {'bba': {...}, 'gprs': {...}}."""
        detail = {}
        for name, info in (self._status.get("connected_status") or {}).items():
            if isinstance(info, dict):
                detail[name] = {
                    "is_connected": info.get("is_connected"),
                    "state": info.get("state"),
                }
        return detail

    def get_device_by_id(self, device_id):
        for device in self._devices:
            if device.id == device_id:
                return device
        return None

    # -- refresh -----------------------------------------------------------

    def connect(self) -> None:
        self._api.connect()
        info = self._api.get_panel_info()
        self._panel_info = info
        self._serial = info.get("serial")
        self._model = info.get("model")

    def update_fast(self) -> None:
        """Refresh everything that changes with arm state."""
        status = self._api.get_status()
        self._status = status
        partition = (status.get("partitions") or [{}])[0]

        self._ready = partition.get("ready")
        self._connected = status.get("connected")

        self._alarms = self._api.get_alarms() or []
        if self._alarms:
            self._alarm = True
            state = partition.get("state")
            self._state = "ALARM" if state in ("HOME", "AWAY") else state
        else:
            self._alarm = False
            if partition.get("status") == "EXIT" and partition.get("state") in (
                "AWAY",
                "HOME",
            ):
                self._state = "ARMING"
            else:
                self._state = partition.get("state")

        self._devices = [
            Device(raw)
            for raw in (self._api.get_devices() or [])
            if raw and raw.get("subtype")
        ]

    def update_slow(self) -> None:
        """Refresh diagnostics that rarely change."""
        self._troubles = self._api.get_troubles() or []
        self._alerts = self._api.get_alerts() or []
        self._events = self._api.get_events() or []
        try:
            self._panels = self._api.get_panels() or []
            self._feature_set = self._api.get_feature_set() or {}
            self._users = self._api.get_users() or {}
        except VisonicError as err:
            # These endpoints are newer than the panel firmware in some
            # deployments; their absence must not break the integration.
            _LOGGER.debug("Optional Visonic endpoint unavailable: %s", err)

    # -- commands ----------------------------------------------------------

    def disarm(self):
        return self._api.set_state("DISARM")

    def arm_home(self):
        return self._api.set_state("HOME")

    def arm_away(self):
        return self._api.set_state("AWAY")

    def get_last_event(self, timestamp_hour_offset: int = 0):
        """Most recent panel event, or None if the log is empty."""
        events = self._events or self._api.get_events() or []
        if not events:
            return None

        last = events[-1]

        # The API supplies `label` (DISARM, BURGLER, ...) and a human-readable
        # `description` ("Disarm after alarm"). Prefer those over guessing from
        # type_id: the upstream map only covered four IDs, so real events such
        # as type_id 173 rendered as "Unknown type_id: 173".
        actions = {89: "Disarm", 85: "ArmHome", 86: "ArmAway", 2: "Alarm"}
        type_id = last.get("type_id")
        action = last.get("label") or actions.get(type_id) or f"type_id {type_id}"

        timestamp = last.get("datetime")
        try:
            # Stdlib parsing, so the integration no longer drags in dateutil.
            parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
            parsed += timedelta(hours=timestamp_hour_offset)
            timestamp = parsed.strftime("%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            _LOGGER.debug("Could not parse event timestamp %r", timestamp)

        return {
            "event_id": last.get("event"),
            "action": action,
            "description": last.get("description"),
            "user": last.get("appointment"),
            "timestamp": timestamp,
            "label": last.get("label"),
            "type_id": type_id,
            "zone": last.get("zone"),
            "zone_name": last.get("zone_name"),
            "device_type": last.get("device_type"),
        }


class VisonicAlarmHub:
    """Owns the API session and throttles polling for all platforms."""

    def __init__(self, domain_config) -> None:
        self.config = domain_config
        self._lock = threading.Lock()
        self._last_update = None
        self._last_slow_update = None
        self._available = False

        api = VisonicAPI(
            domain_config[CONF_HOST],
            domain_config[CONF_APP_ID],
            domain_config[CONF_USER_CODE],
            domain_config[CONF_USER_EMAIL],
            domain_config[CONF_USER_PASSWORD],
            domain_config[CONF_PANEL_ID],
            domain_config[CONF_PARTITION],
        )
        self.alarm = VisonicSystem(api)

    @property
    def name(self):
        return "Visonic Alarm Hub"

    @property
    def last_update(self):
        return self._last_update

    @property
    def available(self):
        """False once a poll has failed, so entities can go unavailable."""
        return self._available

    def connect(self) -> bool:
        try:
            self.alarm.connect()
            self._available = True
            return True
        except VisonicError as err:
            _LOGGER.error("Connection failed: %s", err)
            return False

    @Throttle(MIN_UPDATE_INTERVAL)
    def update(self) -> None:
        """Refresh the shared snapshot.

        Re-authentication is handled inside the API client, which retries once
        on a 401 instead of relying on a validity flag. That flag was a no-op in
        the upstream library (And3rsL/VisonicAlarm2#16), which is why stale
        sessions used to need a full Home Assistant restart.
        """
        with self._lock:
            try:
                self.alarm.update_fast()

                now = datetime.now(timezone.utc)
                if (
                    self._last_slow_update is None
                    or now - self._last_slow_update >= SLOW_UPDATE_INTERVAL
                ):
                    self.alarm.update_slow()
                    self._last_slow_update = now

                self._last_update = datetime.now()
                self._available = True
            except VisonicAuthError as err:
                self._available = False
                _LOGGER.error("Visonic authentication failed: %s", err)
            except VisonicError as err:
                self._available = False
                _LOGGER.error("Update failed: %s", err)
