"""Interfaces with the Visonic Alarm control panel."""

from __future__ import annotations

import logging
from datetime import timedelta
from time import sleep

import homeassistant.components.persistent_notification as pn
from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
)
from homeassistant.const import ATTR_CODE_FORMAT

from . import CONF_EVENT_HOUR_OFFSET, CONF_NO_PIN_REQUIRED, CONF_USER_CODE, HUB as hub
from .entity import VisonicEntity

SUPPORT_VISONIC = (
    AlarmControlPanelEntityFeature.ARM_HOME | AlarmControlPanelEntityFeature.ARM_AWAY
)

_LOGGER = logging.getLogger(__name__)

ATTR_SYSTEM_SERIAL_NUMBER = "serial_number"
ATTR_SYSTEM_MODEL = "model"
ATTR_SYSTEM_READY = "ready"
ATTR_SYSTEM_CONNECTED = "connected"
ATTR_SYSTEM_LAST_UPDATE = "last_update"
ATTR_CHANGED_BY = "changed_by"
ATTR_CHANGED_TIMESTAMP = "changed_timestamp"
ATTR_ALARMS = "alarm"
ATTR_TROUBLE_COUNT = "trouble_count"
ATTR_TROUBLE_TYPES = "trouble_types"
ATTR_TRANSPORTS = "transports"
ATTR_PANEL_ALIAS = "alias"

SCAN_INTERVAL = timedelta(seconds=10)

# Arm states after which it is worth spending a call on the event log to find
# out who did it.
_EVENT_WORTHY = {
    AlarmControlPanelState.ARMED_HOME,
    AlarmControlPanelState.ARMED_AWAY,
    AlarmControlPanelState.DISARMED,
}

_STATE_MAP = {
    "AWAY": AlarmControlPanelState.ARMED_AWAY,
    "HOME": AlarmControlPanelState.ARMED_HOME,
    "DISARM": AlarmControlPanelState.DISARMED,
    "ARMING": AlarmControlPanelState.ARMING,
    "ENTRYDELAY": AlarmControlPanelState.PENDING,
    "ALARM": AlarmControlPanelState.TRIGGERED,
}


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the Visonic Alarm platform."""
    hub.update()
    add_devices([VisonicAlarm(hass)])


class VisonicAlarm(VisonicEntity, AlarmControlPanelEntity):
    """Representation of a Visonic Alarm control panel."""

    _attr_code_arm_required = False
    _attr_name = "Visonic Alarm"

    def __init__(self, hass):
        self._hass = hass
        self._attr_alarm_state = None
        self._code = hub.config.get(CONF_USER_CODE)
        self._no_pin_required = hub.config.get(CONF_NO_PIN_REQUIRED)
        self._changed_by = None
        self._changed_timestamp = None
        self._event_hour_offset = hub.config.get(CONF_EVENT_HOUR_OFFSET)
        # Pins the entity ID (alarm_control_panel.visonic_alarm). Do not change.
        self._id = hub.alarm.serial_number

    @property
    def unique_id(self):
        return self._id

    @property
    def extra_state_attributes(self):
        """Panel attributes.

        The session token used to be published here. That put a live
        authentication credential into the states API, the recorder database and
        every dashboard that showed the entity, so it has been removed.
        """
        troubles = hub.alarm.troubles or []
        return {
            ATTR_SYSTEM_SERIAL_NUMBER: hub.alarm.serial_number,
            ATTR_SYSTEM_MODEL: hub.alarm.model,
            ATTR_PANEL_ALIAS: hub.alarm.alias,
            ATTR_SYSTEM_READY: hub.alarm.ready,
            ATTR_SYSTEM_CONNECTED: hub.alarm.connected,
            ATTR_SYSTEM_LAST_UPDATE: hub.last_update,
            ATTR_CODE_FORMAT: self.code_format,
            ATTR_CHANGED_BY: self._changed_by,
            ATTR_CHANGED_TIMESTAMP: self._changed_timestamp,
            ATTR_ALARMS: hub.alarm.alarm,
            ATTR_TROUBLE_COUNT: len(troubles),
            ATTR_TROUBLE_TYPES: [t.get("trouble_type") for t in troubles],
            ATTR_TRANSPORTS: hub.alarm.connection_detail,
        }

    @property
    def icon(self):
        icons = {
            AlarmControlPanelState.ARMED_AWAY: "mdi:shield-lock",
            AlarmControlPanelState.ARMED_HOME: "mdi:shield-home",
            AlarmControlPanelState.DISARMED: "mdi:shield-check",
            AlarmControlPanelState.ARMING: "mdi:shield-outline",
        }
        return icons.get(self._attr_alarm_state, "hass:bell-ring")

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        return self._attr_alarm_state

    @property
    def code_format(self):
        return None if self._no_pin_required else "Number"

    @property
    def changed_by(self):
        return self._changed_by

    @property
    def changed_timestamp(self):
        return self._changed_timestamp

    @property
    def event_hour_offset(self):
        return self._event_hour_offset

    @property
    def supported_features(self) -> int:
        return SUPPORT_VISONIC

    def update_last_event(self, user, timestamp):
        """Record who last changed the arm state, and when."""
        self._changed_by = user
        self._changed_timestamp = timestamp

    def update(self):
        """Update alarm status and, on an arm-state change, who caused it."""
        hub.update()
        previous = self._attr_alarm_state
        status = hub.alarm.state

        if status in _STATE_MAP:
            self._attr_alarm_state = _STATE_MAP[status]
        elif status is None:
            self._attr_alarm_state = None
        else:
            try:
                _LOGGER.warning("Unknown alarm state: %s. Trying to parse.", status)
                self._attr_alarm_state = AlarmControlPanelState(status.lower())
            except ValueError:
                _LOGGER.error("Unable to parse alarm state: %s", status)
                pn.create(
                    self._hass,
                    f"Unknown alarm state: {status}",
                    title="Alarm State Error",
                )
                self._attr_alarm_state = None

        # The event log is only consulted when the arm state actually changed.
        # Upstream did this with a global EVENT_STATE_CHANGED listener that was
        # never unregistered, which flooded ~250 errors on every shutdown.
        if (
            previous is not None
            and previous != self._attr_alarm_state
            and self._attr_alarm_state in _EVENT_WORTHY
        ):
            try:
                last_event = hub.alarm.get_last_event(self._event_hour_offset)
                if last_event:
                    self.update_last_event(
                        last_event.get("user"), last_event.get("timestamp")
                    )
            except Exception as err:  # noqa: BLE001 - never break a state update
                _LOGGER.debug("Could not fetch last event: %s", err)

    def _check_code(self, code, title):
        """Return True when the supplied code is acceptable."""
        if self._no_pin_required:
            return True
        if code == self._code:
            return True
        pn.create(self._hass, "You entered the wrong code.", title=title)
        return False

    def _refresh_now(self):
        """Force a poll, bypassing the hub throttle, after a command."""
        sleep(1)
        hub.update(no_throttle=True)
        self.update()

    def alarm_disarm(self, code=None):
        """Send disarm command."""
        if not self._check_code(code, "Disarm Failed"):
            return
        hub.alarm.disarm()
        self._refresh_now()

    def alarm_arm_home(self, code=None):
        """Send arm home command."""
        if not self._check_code(code, "Arm Failed"):
            return
        if not hub.alarm.ready:
            pn.create(
                self._hass,
                "The alarm system is not in a ready state. "
                "Maybe there are doors or windows open?",
                title="Arm Failed",
            )
            return
        hub.alarm.arm_home()
        self._refresh_now()

    def alarm_arm_away(self, code=None):
        """Send arm away command."""
        if not self._check_code(code, "Unable to Arm"):
            return
        if not hub.alarm.ready:
            pn.create(
                self._hass,
                "The alarm system is not in a ready state. "
                "Maybe there are doors or windows open?",
                title="Unable to Arm",
            )
            return
        hub.alarm.arm_away()
        self._refresh_now()
