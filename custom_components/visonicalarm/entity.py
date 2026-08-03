"""Base entities for the Visonic Alarm integration.

⚠️ Entity IDs are pinned by ``unique_id``. The values below are load bearing:
changing any of them orphans the existing entity and creates a ``_2`` duplicate,
breaking dashboards and automations that reference the original.

In particular the legacy zone sensors were registered with **integer**
unique_ids (``828776``), while every other entity uses a string. That asymmetry
is preserved deliberately — see :class:`VisonicLegacyZoneEntity`.
"""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_BYPASSED,
    ATTR_DEVICE_TYPE,
    ATTR_ENROLLMENT_ID,
    ATTR_FAULTS,
    ATTR_LOCATION,
    ATTR_REPEATER,
    ATTR_RF_CHANNEL,
    ATTR_SIGNAL,
    ATTR_SIGNAL_AVERAGE,
    ATTR_SIGNAL_SURVEYED,
    ATTR_SOAK_TEST,
    ATTR_SUBTYPE,
    ATTR_ZONE_TYPE,
    DOMAIN,
)
from .coordinator import VisonicDataUpdateCoordinator
from .models import VisonicDevice


class VisonicEntity(CoordinatorEntity[VisonicDataUpdateCoordinator]):
    """Base for panel-level entities."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: VisonicDataUpdateCoordinator) -> None:
        """Attach the entity to the panel device."""
        super().__init__(coordinator)
        self._attr_device_info = panel_device_info(coordinator)

    @property
    def available(self) -> bool:
        """Whether the last poll of the Visonic cloud succeeded.

        This tracks the *cloud API*. A panel that has gone offline still answers
        via cached data, which is what
        ``binary_sensor.visonic_alarm_cloud_connection`` reports.
        """
        return super().available


class VisonicZoneEntity(VisonicEntity):
    """Base for entities backed by one enrolled device."""

    def __init__(self, coordinator: VisonicDataUpdateCoordinator, device_id: int) -> None:
        """Attach the entity to its own zone device, under the panel."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_device_info = zone_device_info(coordinator, device_id)

    @property
    def device(self) -> VisonicDevice | None:
        """The current snapshot of this zone, if still enrolled."""
        return self.coordinator.data.device_by_id(self._device_id)

    @property
    def available(self) -> bool:
        """Unavailable if the device has been unenrolled from the panel."""
        return super().available and self.device is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the device traits the cloud publishes for this zone."""
        device = self.device
        if device is None:
            return {}

        attrs: dict[str, Any] = {
            ATTR_LOCATION: device.location,
            ATTR_ZONE_TYPE: device.zone_type,
            ATTR_SUBTYPE: device.subtype,
            ATTR_DEVICE_TYPE: device.device_type,
            ATTR_ENROLLMENT_ID: device.enrollment_id,
            ATTR_BYPASSED: device.bypassed,
            ATTR_SOAK_TEST: device.soak,
            ATTR_FAULTS: device.fault_types,
        }
        if rssi := device.rssi:
            attrs[ATTR_SIGNAL] = rssi.get("current")
            attrs[ATTR_SIGNAL_AVERAGE] = rssi.get("average")
            attrs[ATTR_RF_CHANNEL] = rssi.get("channel")
            attrs[ATTR_REPEATER] = rssi.get("repeater")
            # Survey timestamp, not a live reading. See VisonicDevice.rssi.
            attrs[ATTR_SIGNAL_SURVEYED] = rssi.get("last_updated")
        return attrs


def panel_device_info(coordinator: VisonicDataUpdateCoordinator) -> DeviceInfo:
    """Device entry representing the alarm panel itself."""
    data = coordinator.data
    serial = data.serial or coordinator.config_entry.unique_id or DOMAIN
    return DeviceInfo(
        identifiers={(DOMAIN, str(serial))},
        manufacturer=data.panel_info.get("manufacturer") or "Visonic",
        model=data.model,
        name=data.alias or "Visonic Alarm",
        serial_number=data.serial,
        sw_version=data.rest_version,
        configuration_url="https://www.visonic.com/",
    )


def zone_device_info(coordinator: VisonicDataUpdateCoordinator, device_id: int) -> DeviceInfo:
    """Device entry for one enrolled zone, linked back to the panel."""
    data = coordinator.data
    serial = data.serial or coordinator.config_entry.unique_id or DOMAIN
    device = data.device_by_id(device_id)
    return DeviceInfo(
        identifiers={(DOMAIN, f"{serial}_zone_{device_id}")},
        via_device=(DOMAIN, str(serial)),
        manufacturer="Visonic",
        model=device.subtype if device else None,
        name=device.display_name if device else f"Zone {device_id}",
        # The enrollment id is the closest thing a wireless device has to a
        # serial number, and it is what an installer reads off the panel.
        serial_number=device.enrollment_id if device else None,
    )
