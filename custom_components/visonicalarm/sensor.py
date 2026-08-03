"""Sensors for the Visonic Alarm integration.

The per-zone entities here are legacy surface kept for backwards compatibility.
⚠️ Their ``unique_id`` values are the raw Visonic device ids **as integers**
(``828776``, not ``"828776"``) because that is how they were first registered.
Returning a string orphans the entity and creates a ``_2`` duplicate, breaking
dashboards that reference ``sensor.visonicalarm_*``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    STATE_CLOSED,
    STATE_OFF,
    STATE_ON,
    STATE_OPEN,
    EntityCategory,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .binary_sensor import _zone_active
from .const import SUBTYPE_CURTAIN, SUBTYPE_MOTION
from .coordinator import VisonicConfigEntry, VisonicDataUpdateCoordinator
from .entity import VisonicEntity, VisonicZoneEntity
from .models import VisonicData

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class VisonicSensorDescription(SensorEntityDescription):
    """Describes a panel-level Visonic sensor."""

    value_fn: Callable[[VisonicData], StateType]
    attributes_fn: Callable[[VisonicData], dict[str, Any]] | None = None


PANEL_SENSORS: tuple[VisonicSensorDescription, ...] = (
    VisonicSensorDescription(
        key="trouble_count",
        translation_key="trouble_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: len(d.troubles),
        attributes_fn=lambda d: {"trouble_types": [t.get("trouble_type") for t in d.troubles]},
    ),
    VisonicSensorDescription(
        key="last_event",
        translation_key="last_event",
        value_fn=lambda d: d.last_event.label if d.last_event else None,
        attributes_fn=lambda d: _event_attributes(d),
    ),
    VisonicSensorDescription(
        key="panel_info",
        translation_key="panel_info",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.model,
        attributes_fn=lambda d: _panel_attributes(d),
    ),
)

# ⚠️ Historical unique_ids; see the module docstring.
_UNIQUE_IDS = {
    "trouble_count": "visonic_alarm_trouble_count",
    "last_event": "visonic_alarm_last_event",
    "panel_info": "visonic_alarm_panel_info",
}


def _event_attributes(data: VisonicData) -> dict[str, Any]:
    """Attributes for the last-event sensor."""
    event = data.last_event
    if event is None:
        return {"event_count": len(data.events)}
    return {
        "description": event.description,
        "user": event.user,
        "timestamp": event.timestamp,
        "label": event.label,
        "type_id": event.type_id,
        "zone": event.zone,
        "zone_name": event.zone_name,
        "device_type": event.device_type,
        "event_id": event.event_id,
        "event_count": len(data.events),
    }


def _panel_attributes(data: VisonicData) -> dict[str, Any]:
    """Attributes for the panel-info sensor."""
    info = data.panel_info
    features = info.get("features") or {}
    users = data.users.get("users") or []
    partitions = data.feature_set.get("partitions") or {}
    return {
        "alias": data.alias,
        "manufacturer": info.get("manufacturer"),
        "current_user": info.get("current_user"),
        "bypass_mode": info.get("bypass_mode"),
        "local_wakeup_needed": info.get("local_wakeup_needed"),
        "rest_api_version": data.rest_version,
        "features": sorted(k for k, v in features.items() if v),
        "user_count": len(users),
        "user_names": [u.get("name") for u in users if u.get("name")],
        "max_partitions": partitions.get("max_partitions"),
        "device_count": len(data.devices),
        "zone_count": len(data.zones),
        "camera_count": len(data.cameras),
        "smart_device_count": len(data.smart_devices),
    }


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VisonicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Visonic sensors, including new zones as they enroll."""
    coordinator = entry.runtime_data

    async_add_entities(
        VisonicPanelSensor(coordinator, description) for description in PANEL_SENSORS
    )

    known: set[int] = set()

    @callback
    def _add_new_zones() -> None:
        new: list[SensorEntity] = []
        for device in coordinator.data.devices:
            if device.id is None or device.id in known:
                continue
            if (
                device.is_contact
                or SUBTYPE_MOTION in device.subtype
                or SUBTYPE_CURTAIN in device.subtype
            ):
                known.add(device.id)
                new.append(VisonicLegacyZoneSensor(coordinator, device.id))
        if new:
            async_add_entities(new)

    _add_new_zones()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_zones))


class VisonicPanelSensor(VisonicEntity, SensorEntity):
    """A panel-level sensor driven by a description."""

    entity_description: VisonicSensorDescription

    def __init__(
        self,
        coordinator: VisonicDataUpdateCoordinator,
        description: VisonicSensorDescription,
    ) -> None:
        """Initialise from the description."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = _UNIQUE_IDS[description.key]

    @property
    def native_value(self) -> StateType:
        """Current value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Description-supplied attributes."""
        if self.entity_description.attributes_fn is None:
            return {}
        return self.entity_description.attributes_fn(self.coordinator.data)


class VisonicLegacyZoneSensor(VisonicZoneEntity, SensorEntity):
    """A zone as a text sensor, kept so existing dashboards keep working.

    ``binary_sensor.visonic_zone_*`` is the better-typed equivalent; this exists
    only because ``sensor.visonicalarm_*`` entity IDs are referenced by
    dashboards in the wild.
    """

    _attr_name = None

    def __init__(self, coordinator: VisonicDataUpdateCoordinator, device_id: int) -> None:
        """Initialise for one enrolled zone."""
        super().__init__(coordinator, device_id)
        # ⚠️ Integer on purpose. See the module docstring.
        self._attr_unique_id = device_id  # type: ignore[assignment]

    @property
    def native_value(self) -> StateType:
        """Open/closed for contacts, on/off participation for detectors."""
        device = self.device
        if device is None:
            return None

        if device.state == "opened":
            return STATE_OPEN
        if device.state == "closed":
            return STATE_CLOSED

        if SUBTYPE_MOTION in device.subtype or SUBTYPE_CURTAIN in device.subtype:
            active = _zone_active(self.coordinator.data.state, device)
            if active is None:
                return None
            return STATE_ON if active else STATE_OFF
        return None

    @property
    def icon(self) -> str | None:
        """Icon reflecting zone kind and state."""
        device = self.device
        state = self.native_value
        zone = device.zone_type if device else ""
        if "24H" in zone:
            return "mdi:hours-24" if state == STATE_CLOSED else "mdi:alarm-light"
        return {
            STATE_CLOSED: "mdi:door-closed",
            STATE_OPEN: "mdi:door-open",
            STATE_OFF: "mdi:motion-sensor-off",
            STATE_ON: "mdi:motion-sensor",
        }.get(str(state))
