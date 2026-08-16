"""Binary sensors for the Visonic Alarm integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    STATE_ARMING,
    STATE_AWAY,
    STATE_DISARM,
    STATE_HOME,
    SUBTYPE_CURTAIN,
    SUBTYPE_MOTION,
    ZONE_24H,
    ZONE_INTERIOR,
)
from .coordinator import VisonicConfigEntry, VisonicDataUpdateCoordinator
from .entity import VisonicEntity, VisonicZoneEntity
from .models import VisonicData, VisonicDevice

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class VisonicBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a panel-level Visonic binary sensor."""

    value_fn: Callable[[VisonicData], bool | None]
    attributes_fn: Callable[[VisonicData], dict[str, Any]] | None = None


PANEL_SENSORS: tuple[VisonicBinarySensorDescription, ...] = (
    VisonicBinarySensorDescription(
        # ⚠️ key is not the unique_id; see _UNIQUE_IDS below.
        key="cloud_connection",
        translation_key="cloud_connection",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        # Derived, not the raw `connected` flag - see VisonicData.is_cloud_connected.
        value_fn=lambda d: d.is_cloud_connected,
        attributes_fn=lambda d: {
            "transports": d.connection_detail,
            "raw_connected": d.connected,
        },
    ),
    VisonicBinarySensorDescription(
        key="problem",
        translation_key="problem",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda d: bool(d.troubles),
        attributes_fn=lambda d: {
            "count": len(d.troubles),
            "trouble_types": [t.get("trouble_type") for t in d.troubles],
            "troubles": [
                {
                    "type": t.get("trouble_type"),
                    "device_type": t.get("device_type"),
                    "zone": t.get("zone"),
                    "zone_name": t.get("zone_name"),
                    "location": t.get("location"),
                }
                for t in d.troubles
            ],
            "alerts": [a.get("alert_type") for a in d.alerts],
            # Device warnings name the room; the panel trouble list may not.
            "faulty_devices": d.faulty_devices,
        },
    ),
    VisonicBinarySensorDescription(
        key="triggered",
        translation_key="triggered",
        device_class=BinarySensorDeviceClass.SAFETY,
        value_fn=lambda d: bool(d.alarms),
        attributes_fn=lambda d: {"alarms": d.alarms},
    ),
    VisonicBinarySensorDescription(
        key="ready",
        translation_key="ready",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: bool(d.ready),
    ),
    VisonicBinarySensorDescription(
        key="zones_bypassed",
        translation_key="zones_bypassed",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda d: bool(d.bypassed_zones),
        attributes_fn=lambda d: {
            "count": len(d.bypassed_zones),
            "bypassed_zones": [z.display_name for z in d.bypassed_zones],
            "soak_test_zones": [z.display_name for z in d.soak_zones],
        },
    ),
)

TRANSPORTS = ("bba", "gprs")

# ⚠️ Historical unique_ids. These pin the entity IDs and predate the
# description-driven rewrite, so they are mapped explicitly rather than derived
# from `key`. Never change a value here.
_UNIQUE_IDS = {
    "cloud_connection": "visonic_alarm_cloud_connection",
    "problem": "visonic_alarm_problem",
    "triggered": "visonic_alarm_triggered",
    "ready": "visonic_alarm_ready",
    "zones_bypassed": "visonic_alarm_zones_bypassed",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VisonicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Visonic binary sensors, including new zones as they enroll."""
    coordinator = entry.runtime_data

    entities: list[BinarySensorEntity] = [
        VisonicPanelBinarySensor(coordinator, description) for description in PANEL_SENSORS
    ]
    entities += [VisonicTransportSensor(coordinator, t) for t in TRANSPORTS]
    async_add_entities(entities)

    known: set[int] = set()

    @callback
    def _add_new_zones() -> None:
        """Add entities for zones that appear after setup (dynamic devices)."""
        new: list[BinarySensorEntity] = []
        for device in coordinator.data.devices:
            if device.id is None or device.id in known:
                continue
            if device.is_contact:
                known.add(device.id)
                new.append(VisonicZoneContact(coordinator, device.id))
            elif SUBTYPE_MOTION in device.subtype or SUBTYPE_CURTAIN in device.subtype:
                known.add(device.id)
                new.append(VisonicZoneMotion(coordinator, device.id))
            else:
                # Keypads, sirens, smoke detectors, the PowerLink and the panel
                # itself occupy no zone, so they used to get no entity at all -
                # a keypad reporting LOW_BATTERY was visible only in the
                # aggregate problem sensor. Upstream issues #32, #43, #48 and
                # #57 are all this complaint.
                known.add(device.id)
                new.append(VisonicDeviceFault(coordinator, device.id))
        if new:
            async_add_entities(new)

    _add_new_zones()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_zones))


class VisonicPanelBinarySensor(VisonicEntity, BinarySensorEntity):
    """A panel-level binary sensor driven by a description."""

    entity_description: VisonicBinarySensorDescription

    def __init__(
        self,
        coordinator: VisonicDataUpdateCoordinator,
        description: VisonicBinarySensorDescription,
    ) -> None:
        """Initialise from the description."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = _UNIQUE_IDS[description.key]

    @property
    def is_on(self) -> bool | None:
        """Current value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Description-supplied attributes."""
        if self.entity_description.attributes_fn is None:
            return {}
        return self.entity_description.attributes_fn(self.coordinator.data)


class VisonicTransportSensor(VisonicEntity, BinarySensorEntity):
    """Connectivity of one panel transport (broadband adapter or GPRS)."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VisonicDataUpdateCoordinator, transport: str) -> None:
        """Initialise for one transport."""
        super().__init__(coordinator)
        self._transport = transport
        self._attr_translation_key = f"transport_{transport}"
        # ⚠️ Pins binary_sensor.visonic_alarm_broadband / _gprs.
        self._attr_unique_id = f"visonic_alarm_transport_{transport}"

    @property
    def is_on(self) -> bool:
        """Whether this transport is connected."""
        info = self.coordinator.data.connection_detail.get(self._transport) or {}
        return bool(info.get("is_connected"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Raw transport state string."""
        info = self.coordinator.data.connection_detail.get(self._transport) or {}
        return {"state": info.get("state")}


class VisonicZoneBinarySensor(VisonicZoneEntity, BinarySensorEntity):
    """Base for a per-zone binary sensor."""

    _attr_name = None

    def __init__(self, coordinator: VisonicDataUpdateCoordinator, device_id: int) -> None:
        """Initialise for one enrolled zone."""
        super().__init__(coordinator, device_id)
        # ⚠️ Pins binary_sensor.visonic_zone_<id> and the named variants.
        self._attr_unique_id = f"visonic_zone_{device_id}"


class VisonicZoneContact(VisonicZoneBinarySensor):
    """A door or window contact, reporting real open/closed state."""

    _attr_device_class = BinarySensorDeviceClass.DOOR

    @property
    def is_on(self) -> bool | None:
        """True when the contact is open."""
        device = self.device
        if device is None or device.state is None:
            return None
        return device.state == "opened"


class VisonicZoneMotion(VisonicZoneBinarySensor):
    """A motion or curtain detector.

    The cloud API never publishes live motion. It only reports whether a zone is
    *participating* in the current arm mode, which is what this reflects: "is
    this detector currently armed", not "is someone moving".
    """

    _attr_device_class = BinarySensorDeviceClass.RUNNING

    @property
    def is_on(self) -> bool | None:
        """Whether the zone is active in the current arm mode."""
        device = self.device
        if device is None:
            return None
        return _zone_active(self.coordinator.data.state, device)


def _zone_active(alarm_state: str | None, device: VisonicDevice) -> bool | None:
    """Whether a zone participates in the given arm mode."""
    zone = device.zone_type
    if alarm_state in (STATE_DISARM, STATE_ARMING):
        return ZONE_24H in zone
    if alarm_state == STATE_HOME:
        return ZONE_INTERIOR not in zone
    if alarm_state in (STATE_AWAY, "DISARMING"):
        return True
    return None


class VisonicDeviceFault(VisonicZoneEntity, BinarySensorEntity):
    """Fault state of an enrolled device that occupies no alarm zone.

    Keypads, sirens, smoke detectors, the PowerLink and the control panel all
    report warnings (low battery, tamper, inactive) but have no zone and so no
    open/closed state. This surfaces the fault on its own entity instead of
    leaving it buried in the panel-wide problem sensor.

    The cloud publishes no live state for these devices - only warnings - so
    this deliberately reports faults rather than pretending to be, say, a smoke
    detector that could tell you about smoke.
    """

    _attr_name = None
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: VisonicDataUpdateCoordinator, device_id: int) -> None:
        """Initialise for one non-zone device."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"visonic_device_{device_id}"

    @property
    def is_on(self) -> bool | None:
        """True when the device is reporting any warning."""
        device = self.device
        if device is None:
            return None
        return bool(device.fault_types)
