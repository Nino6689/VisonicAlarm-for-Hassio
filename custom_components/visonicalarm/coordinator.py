"""DataUpdateCoordinator for the Visonic Alarm integration."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    VisonicApi,
    VisonicAuthError,
    VisonicConnectionError,
    VisonicError,
)
from .const import (
    CONF_APP_ID,
    CONF_EVENT_HOUR_OFFSET,
    CONF_PANEL_ID,
    CONF_USER_CODE,
    CONF_USER_EMAIL,
    CONF_USER_PASSWORD,
    DEFAULT_HOST,
    DOMAIN,
    ISSUE_PANEL_OFFLINE,
    SCAN_INTERVAL,
    SLOW_SCAN_INTERVAL,
    STATE_ALARM,
    STATE_ARMING,
    STATE_AWAY,
    STATE_HOME,
)
from .models import VisonicData, VisonicDevice, VisonicEvent

_LOGGER = logging.getLogger(__name__)

type VisonicConfigEntry = ConfigEntry[VisonicDataUpdateCoordinator]


class VisonicDataUpdateCoordinator(DataUpdateCoordinator[VisonicData]):
    """Polls one panel and shares a single snapshot with every platform."""

    config_entry: VisonicConfigEntry

    def __init__(self, hass: HomeAssistant, entry: VisonicConfigEntry) -> None:
        """Set up the coordinator and its API client."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
            config_entry=entry,
        )
        self.api = VisonicApi(
            async_get_clientsession(hass),
            entry.data.get(CONF_HOST, DEFAULT_HOST),
            entry.data[CONF_APP_ID],
            entry.data[CONF_USER_CODE],
            entry.data[CONF_USER_EMAIL],
            entry.data[CONF_USER_PASSWORD],
            entry.data[CONF_PANEL_ID],
        )
        self._hour_offset: int = entry.options.get(
            CONF_EVENT_HOUR_OFFSET, entry.data.get(CONF_EVENT_HOUR_OFFSET, 0)
        )
        self._last_slow_update: datetime | None = None
        self._data = VisonicData()

    @property
    def hour_offset(self) -> int:
        """Configured offset applied to event timestamps."""
        return self._hour_offset

    async def _async_setup(self) -> None:
        """One-time setup: authenticate and read static panel identity."""
        try:
            await self.api.async_connect()
            info = await self.api.async_get_panel_info()
        except VisonicAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="invalid_auth",
            ) from err
        except VisonicConnectionError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err

        self._data.panel_info = info
        self._data.serial = info.get("serial")
        self._data.model = info.get("model")
        self._data.rest_version = self.api.rest_version

    async def _async_update_data(self) -> VisonicData:
        """Fetch the current panel state.

        Fast-moving endpoints are read every cycle; troubles, events and the
        capability endpoints are refreshed on a slower cadence because they
        rarely change and the API is rate sensitive.
        """
        try:
            await self._async_update_fast()

            now = datetime.now(UTC)
            if self._last_slow_update is None or now - self._last_slow_update >= SLOW_SCAN_INTERVAL:
                await self._async_update_slow()
                self._last_slow_update = now
        except VisonicAuthError as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="invalid_auth",
            ) from err
        except VisonicError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err

        return self._data

    async def _async_update_fast(self) -> None:
        """Refresh everything that changes with arm state."""
        data = self._data
        status = await self.api.async_get_status()
        data.status = status

        partition: dict[str, Any] = (status.get("partitions") or [{}])[0]
        data.ready = partition.get("ready")
        data.connected = status.get("connected")

        data.alarms = await self.api.async_get_alarms()
        if data.alarms:
            data.alarm_active = True
            state = partition.get("state")
            data.state = STATE_ALARM if state in (STATE_HOME, STATE_AWAY) else state
        else:
            data.alarm_active = False
            if partition.get("status") == "EXIT" and partition.get("state") in (
                STATE_AWAY,
                STATE_HOME,
            ):
                data.state = STATE_ARMING
            else:
                data.state = partition.get("state")

        data.devices = [
            VisonicDevice(raw)
            for raw in await self.api.async_get_devices()
            if raw and raw.get("subtype")
        ]

    async def _async_update_slow(self) -> None:
        """Refresh diagnostics and capability data."""
        data = self._data
        data.troubles = await self.api.async_get_troubles()
        data.alerts = await self.api.async_get_alerts()
        data.events = [
            VisonicEvent.from_raw(raw, self._hour_offset)
            for raw in await self.api.async_get_events()
        ]

        # These are newer than some panel firmware; their absence must not break
        # the integration.
        for attr, call in (
            ("feature_set", self.api.async_get_feature_set),
            ("users", self.api.async_get_users),
            ("cameras", self.api.async_get_cameras),
            ("smart_devices", self.api.async_get_smart_devices),
            ("home_automation_devices", self.api.async_get_home_automation_devices),
            ("email_notifications", self.api.async_get_email_notifications),
        ):
            try:
                setattr(data, attr, await call())
            except VisonicError as err:
                _LOGGER.debug("Optional endpoint %s unavailable: %s", attr, err)

        try:
            panels = await self.api.async_get_panels()
        except VisonicError as err:
            _LOGGER.debug("Optional endpoint panels unavailable: %s", err)
        else:
            if panels:
                data.alias = panels[0].get("alias")

        self._async_update_offline_issue()

    def _async_update_offline_issue(self) -> None:
        """Raise a repair issue while the panel is not reporting to the cloud.

        This matters more than it looks: when the panel is offline the cloud
        keeps serving its last known arm state, so the alarm entity silently
        goes stale rather than becoming unavailable, and automations keep
        trusting it.
        """
        if self._data.connected:
            ir.async_delete_issue(self.hass, DOMAIN, ISSUE_PANEL_OFFLINE)
            return

        ir.async_create_issue(
            self.hass,
            DOMAIN,
            ISSUE_PANEL_OFFLINE,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_PANEL_OFFLINE,
            translation_placeholders={"panel": self._data.alias or "Visonic Alarm"},
        )

    async def async_set_state(self, state: str) -> None:
        """Send an arm or disarm command, then refresh immediately."""
        await self.api.async_set_state(state)
        await self.async_request_refresh()
