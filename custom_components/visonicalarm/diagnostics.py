"""Diagnostics for the Visonic Alarm integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import (
    CONF_APP_ID,
    CONF_PANEL_ID,
    CONF_USER_CODE,
    CONF_USER_EMAIL,
    CONF_USER_PASSWORD,
)
from .coordinator import VisonicConfigEntry

# Credentials, the panel serial and anything that identifies the household.
TO_REDACT = {
    CONF_USER_PASSWORD,
    CONF_USER_CODE,
    CONF_USER_EMAIL,
    CONF_PANEL_ID,
    CONF_APP_ID,
    "serial",
    "serial_number",
    "panel_serial",
    "email",
    "phone",
    "sms",
    "alias",
    "user_token",
    "session_token",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: VisonicConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data

    return async_redact_data(
        {
            "entry": {
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            "panel": {
                "model": data.model,
                "serial": data.serial,
                "alias": data.alias,
                "rest_version": data.rest_version,
                "state": data.state,
                "ready": data.ready,
                "connected": data.connected,
                "alarm_active": data.alarm_active,
                "transports": data.connection_detail,
            },
            "panel_info": data.panel_info,
            "feature_set": data.feature_set,
            "status": data.status,
            "counts": {
                "devices": len(data.devices),
                "zones": len(data.zones),
                "troubles": len(data.troubles),
                "alerts": len(data.alerts),
                "alarms": len(data.alarms),
                "events": len(data.events),
                "cameras": len(data.cameras),
                "smart_devices": len(data.smart_devices),
                "users": len((data.users or {}).get("users") or []),
            },
            "troubles": data.troubles,
            "alerts": data.alerts,
            "faulty_devices": data.faulty_devices,
            "bypassed_zones": [z.display_name for z in data.bypassed_zones],
            "devices": [d.raw for d in data.devices],
            "events": [
                {
                    "type_id": e.type_id,
                    "label": e.label,
                    "description": e.description,
                    "timestamp": e.timestamp,
                    "zone": e.zone,
                }
                for e in data.events
            ],
        },
        TO_REDACT,
    )
