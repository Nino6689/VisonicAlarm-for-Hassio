"""Binary sensors for the Visonic Alarm system.

Everything here is new surface. The `sensor` platform's zone entities are kept
untouched for backwards compatibility, but these expose the same zones with real
device classes plus the panel health data the integration previously fetched and
threw away.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.entity import EntityCategory

from . import HUB as hub
from .entity import VisonicEntity

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=10)

# Zone types that are only active while the system is armed away.
INTERIOR_ZONES = ("INTERIOR",)


def setup_platform(hass, config, add_devices, discovery_info=None):
    """Set up the Visonic Alarm binary sensors."""
    hub.update()

    entities: list[BinarySensorEntity] = [
        VisonicCloudConnection(),
        VisonicProblem(),
        VisonicTriggered(),
        VisonicReady(),
        VisonicZonesBypassed(),
    ]

    for transport in ("bba", "gprs"):
        entities.append(VisonicTransport(transport))

    for device in hub.alarm.devices:
        subtype = device.subtype or ""
        if "CONTACT" in subtype:
            entities.append(VisonicZoneContact(device.id))
        elif "MOTION" in subtype or "CURTAIN" in subtype:
            entities.append(VisonicZoneMotion(device.id))

    add_devices(entities, True)


class VisonicPanelBinarySensor(VisonicEntity, BinarySensorEntity):
    """Base for panel-level binary sensors."""

    _attr_should_poll = True

    def update(self):
        hub.update()


class VisonicCloudConnection(VisonicPanelBinarySensor):
    """Whether the Visonic cloud can currently reach the panel.

    When this is off the panel is not reporting, so every other Visonic entity
    is showing its last known value rather than live data.
    """

    _attr_name = "Visonic Alarm Cloud Connection"
    _attr_unique_id = "visonic_alarm_cloud_connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    @property
    def is_on(self):
        return bool(hub.alarm.connected)

    @property
    def extra_state_attributes(self):
        return {
            "transports": hub.alarm.connection_detail,
            "last_update": hub.last_update,
            "rest_api_version": hub.alarm.rest_version,
        }


class VisonicTransport(VisonicPanelBinarySensor):
    """Connectivity of one panel transport (broadband adapter or GPRS)."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, transport: str) -> None:
        self._transport = transport
        label = "Broadband" if transport == "bba" else transport.upper()
        self._attr_name = f"Visonic Alarm {label}"
        self._attr_unique_id = f"visonic_alarm_transport_{transport}"

    @property
    def is_on(self):
        info = hub.alarm.connection_detail.get(self._transport) or {}
        return bool(info.get("is_connected"))

    @property
    def extra_state_attributes(self):
        info = hub.alarm.connection_detail.get(self._transport) or {}
        return {"state": info.get("state")}


class VisonicProblem(VisonicPanelBinarySensor):
    """Active trouble conditions reported by the panel.

    The upstream integration fetched troubles and then discarded them, so
    conditions like a low sensor battery or the panel dropping off the network
    were invisible in Home Assistant.
    """

    _attr_name = "Visonic Alarm Problem"
    _attr_unique_id = "visonic_alarm_problem"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    @property
    def is_on(self):
        return bool(hub.alarm.troubles)

    @property
    def extra_state_attributes(self):
        troubles = hub.alarm.troubles or []
        return {
            "count": len(troubles),
            "trouble_types": [t.get("trouble_type") for t in troubles],
            "troubles": [
                {
                    "type": t.get("trouble_type"),
                    "device_type": t.get("device_type"),
                    "zone": t.get("zone"),
                    "zone_name": t.get("zone_name"),
                    "location": t.get("location"),
                }
                for t in troubles
            ],
            "alerts": [a.get("alert_type") for a in (hub.alarm.alerts or [])],
            # Device-level warnings name the room, which the panel-level trouble
            # list does not always do.
            "faulty_devices": {
                (d.location or str(d.id)): d.fault_types
                for d in hub.alarm.devices
                if d.fault_types
            },
        }


class VisonicTriggered(VisonicPanelBinarySensor):
    """Whether the panel currently reports an active alarm."""

    _attr_name = "Visonic Alarm Triggered"
    _attr_unique_id = "visonic_alarm_triggered"
    _attr_device_class = BinarySensorDeviceClass.SAFETY

    @property
    def is_on(self):
        return bool(hub.alarm.alarms)

    @property
    def extra_state_attributes(self):
        return {"alarms": hub.alarm.alarms or []}


class VisonicZonesBypassed(VisonicPanelBinarySensor):
    """Whether any zone is currently bypassed.

    A bypassed zone is excluded from arming, so the system reports "armed" while
    that door or detector is doing nothing. The panel does **not** raise this as
    a trouble, so without this entity it is invisible from Home Assistant.
    """

    _attr_name = "Visonic Alarm Zones Bypassed"
    _attr_unique_id = "visonic_alarm_zones_bypassed"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:shield-off-outline"

    @staticmethod
    def _bypassed():
        return [d for d in hub.alarm.devices if d.bypassed]

    @property
    def is_on(self):
        return bool(self._bypassed())

    @property
    def extra_state_attributes(self):
        bypassed = self._bypassed()
        soaked = [d for d in hub.alarm.devices if d.soak]
        return {
            "count": len(bypassed),
            "bypassed_zones": [d.location or d.id for d in bypassed],
            "soak_test_zones": [d.location or d.id for d in soaked],
        }


class VisonicReady(VisonicPanelBinarySensor):
    """Whether the system is ready to arm (no open zones)."""

    _attr_name = "Visonic Alarm Ready to Arm"
    _attr_unique_id = "visonic_alarm_ready"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def is_on(self):
        return bool(hub.alarm.ready)


class VisonicZone(VisonicEntity, BinarySensorEntity):
    """Base for a single enrolled zone device."""

    _attr_should_poll = True

    def __init__(self, device_id) -> None:
        self._device_id = device_id
        self._attr_unique_id = f"visonic_zone_{device_id}"
        self._name = None
        self._location = None
        self._zone = ""
        self._subtype = None
        self._device_type = None
        self._state = None
        self._enrollment_id = None
        self._bypassed = None
        self._soak = None
        self._rssi = {}
        self._faults = []

    @property
    def name(self):
        # Most devices have an empty `name`; the room label lives in
        # traits.location.name and is the only useful identifier.
        if self._name:
            return f"Visonic {self._name}"
        return f"Visonic Zone {self._device_id}"

    @property
    def is_on(self):
        return self._state

    @property
    def extra_state_attributes(self):
        attrs = {
            "location": self._location,
            "zone_type": self._zone,
            "subtype": self._subtype,
            "device_type": self._device_type,
            "device_id": self._device_id,
            "enrollment_id": self._enrollment_id,
            "bypassed": self._bypassed,
            "soak_test": self._soak,
            "faults": self._faults,
        }
        if self._rssi:
            attrs["signal"] = self._rssi.get("current")
            attrs["signal_average"] = self._rssi.get("average")
            attrs["rf_channel"] = self._rssi.get("channel")
            attrs["repeater"] = self._rssi.get("repeater")
            # Survey timestamp, not a live reading - see Device.rssi.
            attrs["signal_surveyed"] = self._rssi.get("last_updated")
        return attrs

    def _refresh_metadata(self, device):
        self._zone = device.zone or ""
        self._location = device.location
        # Prefer an explicitly set device name; fall back to the room label.
        # Some devices carry both ("Master Bedroom" vs the panel's abbreviated
        # "Master Bdrm"), and the explicit name is the better one.
        self._name = device.name or device.location or None
        self._subtype = device.subtype
        self._device_type = device.device_type
        self._enrollment_id = device.enrollment_id
        self._bypassed = device.bypassed
        self._soak = device.soak
        self._rssi = device.rssi
        self._faults = device.fault_types

    def update(self):
        hub.update()
        device = hub.alarm.get_device_by_id(self._device_id)
        if device is None:
            _LOGGER.debug("Visonic device %s not present in update", self._device_id)
            self._state = None
            return
        self._refresh_metadata(device)
        self._state = self._derive_state(device)

    def _derive_state(self, device):
        raise NotImplementedError


class VisonicZoneContact(VisonicZone):
    """A door or window contact. Reports real open/closed from the panel."""

    _attr_device_class = BinarySensorDeviceClass.DOOR

    def _derive_state(self, device):
        state = device.state
        if state is None:
            return None
        return state == "opened"


class VisonicZoneMotion(VisonicZone):
    """A motion or curtain detector.

    The cloud API never publishes live motion for these devices — it only
    reports whether the zone is *participating* in the current arm mode. That is
    what this entity reflects, so it answers "is this detector currently armed"
    rather than "is someone moving". Use the Frigate/Zigbee PIRs for real motion.
    """

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def _derive_state(self, device):
        alarm_state = hub.alarm.state
        zone = device.zone or ""

        if alarm_state in ("DISARM", "ARMING"):
            return "24H" in zone
        if alarm_state == "HOME":
            return not any(interior in zone for interior in INTERIOR_ZONES)
        if alarm_state in ("AWAY", "DISARMING"):
            return True
        return None
