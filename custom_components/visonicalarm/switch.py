"""Zone bypass switches for the Visonic Alarm integration.

A bypassed zone is excluded from arming: the system reports "armed" while that
door or detector does nothing. The panel does **not** raise bypass as a trouble,
so it is otherwise invisible from Home Assistant.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import VisonicError
from .const import DOMAIN
from .coordinator import VisonicConfigEntry, VisonicDataUpdateCoordinator
from .entity import VisonicZoneEntity

# Bypass changes are written to the panel; serialise them.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VisonicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up a bypass switch per zone, including zones added later."""
    coordinator = entry.runtime_data
    known: set[int] = set()

    @callback
    def _add_new_zones() -> None:
        new: list[SwitchEntity] = []
        for device in coordinator.data.devices:
            # Only real zones can be bypassed, and only if the panel published
            # a bypass trait for them.
            if (
                device.id is None
                or device.id in known
                or device.zone_number is None
                or device.bypassed is None
            ):
                continue
            known.add(device.id)
            new.append(VisonicBypassSwitch(coordinator, device.id))
        if new:
            async_add_entities(new)

    _add_new_zones()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_zones))


class VisonicBypassSwitch(VisonicZoneEntity, SwitchEntity):
    """Bypass state for one zone."""

    _attr_translation_key = "bypass"
    _attr_icon = "mdi:shield-off-outline"

    def __init__(self, coordinator: VisonicDataUpdateCoordinator, device_id: int) -> None:
        """Initialise for one enrolled zone."""
        super().__init__(coordinator, device_id)
        self._attr_unique_id = f"visonic_bypass_{device_id}"

    @property
    def is_on(self) -> bool | None:
        """True when the zone is bypassed."""
        device = self.device
        return device.bypassed if device else None

    async def _async_set(self, enabled: bool) -> None:
        device = self.device
        if device is None or device.zone_number is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="zone_unavailable")
        try:
            await self.coordinator.api.async_set_bypass_zone(device.zone_number, enabled)
        except VisonicError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Bypass the zone."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop bypassing the zone."""
        await self._async_set(False)
