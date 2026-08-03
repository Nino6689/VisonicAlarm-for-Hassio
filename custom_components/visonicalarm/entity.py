"""Shared entity base for the Visonic Alarm integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from . import DOMAIN


def _hub():
    """Resolve the hub lazily.

    `from . import HUB` binds the value at import time, and HUB is still None
    until `setup()` runs. Reading the attribute on each access avoids depending
    on module import order.
    """
    from . import HUB  # noqa: PLC0415 - deliberate late binding

    return HUB


class VisonicEntity(Entity):
    """Attaches every entity to a single Visonic panel device.

    Without this each entity floated unattached in the UI. Grouping them means
    the panel model, serial and account alias are shown once, on the device page.
    """

    _attr_has_entity_name = False

    @property
    def device_info(self) -> DeviceInfo:
        hub = _hub()
        serial = hub.alarm.serial_number
        return DeviceInfo(
            identifiers={(DOMAIN, str(serial))},
            manufacturer=hub.alarm.panel_info.get("manufacturer") or "Visonic",
            model=hub.alarm.model,
            name=hub.alarm.alias or "Visonic Alarm",
            serial_number=serial,
        )

    @property
    def available(self) -> bool:
        """Reflect whether the last poll of the Visonic cloud succeeded.

        Note this tracks the *cloud API*, not the panel's own link to the cloud.
        A panel that has gone offline still answers via cached data, which is
        what `binary_sensor.visonic_alarm_cloud_connection` is for.
        """
        return _hub().available
