"""Actions exposed by the Visonic Alarm integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import VisonicError
from .const import DOMAIN

if TYPE_CHECKING:
    from .coordinator import VisonicConfigEntry, VisonicDataUpdateCoordinator

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_ZONE = "zone"
ATTR_NAME = "name"
ATTR_MODE = "mode"

SERVICE_REFRESH = "refresh"
SERVICE_SOUND_SIREN = "sound_siren"
SERVICE_SILENCE_SIREN = "silence_siren"
SERVICE_SET_ZONE_NAME = "set_zone_name"

_ENTRY_SCHEMA = vol.Schema({vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string})

_SET_ZONE_NAME_SCHEMA = _ENTRY_SCHEMA.extend(
    {
        vol.Required(ATTR_ZONE): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Required(ATTR_NAME): cv.string,
    }
)

_SILENCE_SCHEMA = _ENTRY_SCHEMA.extend({vol.Optional(ATTR_MODE, default="all"): cv.string})


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> VisonicDataUpdateCoordinator:
    """Resolve the target entry, raising if it is not usable.

    Quality scale (action-setup): actions are registered at startup, so they can
    be called when the entry is missing or not loaded. That must be a clear
    error rather than an AttributeError.
    """
    entry_id: str = call.data[ATTR_CONFIG_ENTRY_ID]
    entry: VisonicConfigEntry | None = hass.config_entries.async_get_entry(entry_id)

    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_found",
            translation_placeholders={"target": entry_id},
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"target": entry.title},
        )
    return entry.runtime_data


def _require_feature(coordinator: VisonicDataUpdateCoordinator, feature: str) -> None:
    """Refuse an action the panel does not advertise."""
    features = coordinator.data.panel_info.get("features") or {}
    if not features.get(feature):
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="feature_unsupported",
            translation_placeholders={"feature": feature},
        )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""

    async def _async_refresh(call: ServiceCall) -> None:
        """Force an immediate poll of the panel."""
        await _coordinator(hass, call).async_request_refresh()

    async def _async_sound_siren(call: ServiceCall) -> None:
        """Sound the siren — a panic alarm.

        Deliberately an action rather than a switch: sounding a house alarm must
        take an explicit, intentional call and must not be one stray toggle away
        on a dashboard.
        """
        coordinator = _coordinator(hass, call)
        _require_feature(coordinator, "enabling_siren")
        try:
            await coordinator.api.async_activate_siren()
        except VisonicError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await coordinator.async_request_refresh()

    async def _async_silence_siren(call: ServiceCall) -> None:
        """Silence a sounding siren."""
        coordinator = _coordinator(hass, call)
        _require_feature(coordinator, "disabling_siren")
        try:
            await coordinator.api.async_disable_siren(call.data[ATTR_MODE])
        except VisonicError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await coordinator.async_request_refresh()

    async def _async_set_zone_name(call: ServiceCall) -> None:
        """Rename a zone on the panel itself."""
        coordinator = _coordinator(hass, call)
        try:
            await coordinator.api.async_set_name("zone", call.data[ATTR_ZONE], call.data[ATTR_NAME])
        except VisonicError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err
        await coordinator.async_request_refresh()

    services: tuple[tuple[str, Any, vol.Schema], ...] = (
        (SERVICE_REFRESH, _async_refresh, _ENTRY_SCHEMA),
        (SERVICE_SOUND_SIREN, _async_sound_siren, _ENTRY_SCHEMA),
        (SERVICE_SILENCE_SIREN, _async_silence_siren, _SILENCE_SCHEMA),
        (SERVICE_SET_ZONE_NAME, _async_set_zone_name, _SET_ZONE_NAME_SCHEMA),
    )
    for name, handler, schema in services:
        if not hass.services.has_service(DOMAIN, name):
            hass.services.async_register(DOMAIN, name, handler, schema=schema)
