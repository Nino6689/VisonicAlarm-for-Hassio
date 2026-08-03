"""The Visonic Alarm integration."""

from __future__ import annotations

import logging

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import CONF_HOST, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_APP_ID,
    CONF_EVENT_HOUR_OFFSET,
    CONF_NO_PIN_REQUIRED,
    CONF_PANEL_ID,
    CONF_PARTITION,
    CONF_USER_CODE,
    CONF_USER_EMAIL,
    CONF_USER_PASSWORD,
    DEFAULT_HOST,
    DEFAULT_NAME,
    DEFAULT_PARTITION,
    DOMAIN,
    ISSUE_YAML_DEPRECATED,
    PLATFORMS,
)
from .coordinator import VisonicConfigEntry, VisonicDataUpdateCoordinator
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

# The legacy YAML schema, kept only so existing configurations can be imported.
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_HOST, default=DEFAULT_HOST): cv.string,
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


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register actions and import any legacy YAML configuration.

    Quality scale (action-setup): actions are registered here so they exist even
    with no entry loaded, and the handlers raise if the entry they need is gone.
    """
    async_setup_services(hass)

    if DOMAIN not in config:
        return True

    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data=dict(config[DOMAIN]),
        )
    )

    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_YAML_DEPRECATED,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_YAML_DEPRECATED,
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: VisonicConfigEntry) -> bool:
    """Set up Visonic Alarm from a config entry."""
    coordinator = VisonicDataUpdateCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    # Per-entry state lives on the entry itself (quality scale: runtime-data).
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: VisonicConfigEntry) -> None:
    """Reload the entry when its options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: VisonicConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
