"""Sensors for the Visonic Alarm system.

The per-zone entities here are legacy surface. Their `unique_id` values are the
raw Visonic device IDs, which is what pins their entity IDs
(`sensor.visonicalarm_<id>`, plus named ones like `sensor.bedroom_4`). Those IDs
are referenced by dashboards, so they must not change. New, properly typed
equivalents live in the `binary_sensor` platform.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.const import (
    STATE_CLOSED,
    STATE_OFF,
    STATE_ON,
    STATE_OPEN,
    STATE_UNKNOWN,
)
from homeassistant.helpers.entity import EntityCategory

from . import HUB as hub
from .entity import VisonicEntity

_LOGGER = logging.getLogger(__name__)

CONTACT_ATTR_ZONE = "zone"
CONTACT_ATTR_NAME = "name"
CONTACT_ATTR_DEVICE_TYPE = "device_type"
CONTACT_ATTR_SUBTYPE = "subtype"

SCAN_INTERVAL = timedelta(seconds=10)


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the Visonic Alarm sensor platform."""
    hub.update()

    entities: list[SensorEntity] = [
        VisonicTroubleCount(),
        VisonicLastEvent(),
        VisonicPanelInfo(),
    ]

    for device in hub.alarm.devices:
        subtype = device.subtype or ""
        if "CONTACT" in subtype or "MOTION" in subtype or "CURTAIN" in subtype:
            _LOGGER.debug(
                "Visonic zone device found [subtype:%s] [id:%s]", subtype, device.id
            )
            entities.append(VisonicAlarmContact(hub.alarm, device.id))

    add_devices(entities, True)


class VisonicAlarmContact(VisonicEntity, SensorEntity):
    """A Visonic zone device, kept on the sensor domain for compatibility."""

    def __init__(self, alarm, contact_id):
        self._state = STATE_UNKNOWN
        self._alarm = alarm
        self._id = contact_id
        self._name = None
        self._location = None
        self._zone = ""
        self._device_type = None
        self._subtype = None
        self._enrollment_id = None
        self._bypassed = None
        self._rssi = {}
        self._faults = []

    @property
    def name(self):
        # Most devices have an empty `name`; traits.location.name is then the
        # only human-readable label. Entity IDs are pinned by unique_id, so this
        # only affects the displayed friendly name.
        return str(self._name or self._location or self._id)

    @property
    def unique_id(self):
        # Pins the entity ID. Never change this.
        return self._id

    @property
    def extra_state_attributes(self):
        attrs = {
            CONTACT_ATTR_ZONE: self._zone,
            CONTACT_ATTR_NAME: self._name,
            CONTACT_ATTR_DEVICE_TYPE: self._device_type,
            CONTACT_ATTR_SUBTYPE: self._subtype,
            "location": self._location,
            "enrollment_id": self._enrollment_id,
            "bypassed": self._bypassed,
            "faults": self._faults,
        }
        if self._rssi:
            attrs["signal"] = self._rssi.get("current")
            attrs["rf_channel"] = self._rssi.get("channel")
            # Survey timestamp, not live telemetry - see Device.rssi.
            attrs["signal_surveyed"] = self._rssi.get("last_updated")
        return attrs

    @property
    def icon(self):
        zone = self._zone or ""
        if "24H" in zone:
            if self._state == STATE_CLOSED:
                return "mdi:hours-24"
            if self._state == STATE_OPEN:
                return "mdi:alarm-light"
        if self._state == STATE_CLOSED:
            return "mdi:door-closed"
        if self._state == STATE_OPEN:
            return "mdi:door-open"
        if self._state == STATE_OFF:
            return "mdi:motion-sensor-off"
        if self._state == STATE_ON:
            return "mdi:motion-sensor"
        return None

    @property
    def native_value(self):
        return self._state

    def update(self):
        """Refresh this zone from the shared snapshot."""
        hub.update()

        device = self._alarm.get_device_by_id(self._id)
        if device is None:
            _LOGGER.warning("Device could not be found: %s", self._id)
            return

        # Metadata first, so the zone-based inference below sees current values
        # even on the first pass.
        self._zone = device.zone or ""
        self._name = device.name
        self._location = device.location
        self._device_type = device.device_type
        self._subtype = device.subtype
        self._enrollment_id = device.enrollment_id
        self._bypassed = device.bypassed
        self._rssi = device.rssi
        self._faults = device.fault_types

        status = device.state
        subtype = device.subtype or ""

        if status == "opened":
            self._state = STATE_OPEN
        elif status == "closed":
            self._state = STATE_CLOSED
        elif "CURTAIN" in subtype or "MOTION" in subtype:
            # The cloud does not publish live motion, only whether the zone is
            # active in the current arm mode.
            alarm_state = self._alarm.state
            if alarm_state in ("DISARM", "ARMING"):
                self._state = STATE_ON if "24H" in self._zone else STATE_OFF
            elif alarm_state == "HOME":
                self._state = STATE_OFF if "INTERIOR" in self._zone else STATE_ON
            elif alarm_state in ("AWAY", "DISARMING"):
                self._state = STATE_ON
            else:
                self._state = STATE_UNKNOWN
        else:
            self._state = STATE_UNKNOWN


class VisonicPanelSensor(VisonicEntity, SensorEntity):
    """Base for panel-level diagnostic sensors."""

    _attr_should_poll = True

    def update(self):
        hub.update()


class VisonicTroubleCount(VisonicPanelSensor):
    """Number of active trouble conditions."""

    _attr_name = "Visonic Alarm Trouble Count"
    _attr_unique_id = "visonic_alarm_trouble_count"
    _attr_icon = "mdi:alert-circle-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        return len(hub.alarm.troubles or [])

    @property
    def extra_state_attributes(self):
        return {
            "trouble_types": [
                t.get("trouble_type") for t in (hub.alarm.troubles or [])
            ]
        }


class VisonicLastEvent(VisonicPanelSensor):
    """Most recent entry in the panel event log."""

    _attr_name = "Visonic Alarm Last Event"
    _attr_unique_id = "visonic_alarm_last_event"
    _attr_icon = "mdi:history"

    def __init__(self):
        self._event = None

    def update(self):
        hub.update()
        self._event = hub.alarm.get_last_event(
            hub.config.get("event_hour_offset", 0)
        )

    @property
    def native_value(self):
        if not self._event:
            return None
        return self._event.get("action")

    @property
    def extra_state_attributes(self):
        if not self._event:
            return {"event_count": len(hub.alarm.events or [])}
        return {
            "description": self._event.get("description"),
            "user": self._event.get("user"),
            "timestamp": self._event.get("timestamp"),
            "label": self._event.get("label"),
            "type_id": self._event.get("type_id"),
            "zone": self._event.get("zone"),
            "zone_name": self._event.get("zone_name"),
            "device_type": self._event.get("device_type"),
            "event_id": self._event.get("event_id"),
            "event_count": len(hub.alarm.events or []),
        }


class VisonicPanelInfo(VisonicPanelSensor):
    """Panel identity and capabilities, surfaced for diagnostics."""

    _attr_name = "Visonic Alarm Panel"
    _attr_unique_id = "visonic_alarm_panel_info"
    _attr_icon = "mdi:shield-home-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        return hub.alarm.model

    @property
    def extra_state_attributes(self):
        info = hub.alarm.panel_info or {}
        features = info.get("features") or {}
        users = (hub.alarm.users or {}).get("users") or []
        return {
            "alias": hub.alarm.alias,
            "manufacturer": info.get("manufacturer"),
            "current_user": info.get("current_user"),
            "bypass_mode": info.get("bypass_mode"),
            "local_wakeup_needed": info.get("local_wakeup_needed"),
            "rest_api_version": hub.alarm.rest_version,
            "features": sorted(k for k, v in features.items() if v),
            "user_count": len(users),
            "user_names": [u.get("name") for u in users if u.get("name")],
            "max_partitions": (
                (hub.alarm.feature_set.get("partitions") or {}).get("max_partitions")
            ),
        }
