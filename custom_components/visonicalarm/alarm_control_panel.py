"""Alarm control panel for the Visonic Alarm integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import VisonicError
from .const import (
    CONF_NO_PIN_REQUIRED,
    CONF_USER_CODE,
    DOMAIN,
    STATE_ALARM,
    STATE_ARMING,
    STATE_AWAY,
    STATE_DISARM,
    STATE_ENTRY_DELAY,
    STATE_HOME,
)
from .coordinator import VisonicConfigEntry, VisonicDataUpdateCoordinator
from .entity import VisonicEntity

PARALLEL_UPDATES = 1

STATE_MAP = {
    STATE_AWAY: AlarmControlPanelState.ARMED_AWAY,
    STATE_HOME: AlarmControlPanelState.ARMED_HOME,
    STATE_DISARM: AlarmControlPanelState.DISARMED,
    STATE_ARMING: AlarmControlPanelState.ARMING,
    STATE_ENTRY_DELAY: AlarmControlPanelState.PENDING,
    STATE_ALARM: AlarmControlPanelState.TRIGGERED,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: VisonicConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Visonic alarm control panel."""
    async_add_entities([VisonicAlarmPanel(entry.runtime_data)])


class VisonicAlarmPanel(VisonicEntity, AlarmControlPanelEntity):
    """The alarm panel itself."""

    _attr_name = None

    def __init__(self, coordinator: VisonicDataUpdateCoordinator) -> None:
        """Initialise the panel entity."""
        super().__init__(coordinator)
        # ⚠️ Pins alarm_control_panel.visonic_alarm. Never change.
        self._attr_unique_id = coordinator.data.serial
        self._code = coordinator.config_entry.data[CONF_USER_CODE]

    @property
    def supported_features(self) -> AlarmControlPanelEntityFeature:
        """Arm modes the panel advertises.

        Read from ``panel_info.state_sets`` so a panel that cannot arm home does
        not offer it, rather than hard-coding both.
        """
        features = AlarmControlPanelEntityFeature(0)
        state_sets = self.coordinator.data.panel_info.get("state_sets") or {}
        names = {
            entry.get("name")
            for states in state_sets.values()
            for entry in states
            if isinstance(entry, dict) and entry.get("settable")
        }
        if not names:
            names = {STATE_HOME, STATE_AWAY}
        if STATE_HOME in names:
            features |= AlarmControlPanelEntityFeature.ARM_HOME
        if STATE_AWAY in names:
            features |= AlarmControlPanelEntityFeature.ARM_AWAY
        return features

    @property
    def _no_pin_required(self) -> bool:
        entry = self.coordinator.config_entry
        return bool(
            entry.options.get(CONF_NO_PIN_REQUIRED, entry.data.get(CONF_NO_PIN_REQUIRED, False))
        )

    @property
    def code_format(self) -> CodeFormat | None:
        """Whether Home Assistant should prompt for a code."""
        return None if self._no_pin_required else CodeFormat.NUMBER

    @property
    def code_arm_required(self) -> bool:
        """Whether arming requires the code."""
        return not self._no_pin_required

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        """Current arm state."""
        return STATE_MAP.get(self.coordinator.data.state or "")

    @property
    def changed_by(self) -> str | None:
        """Who last changed the arm state, per the panel event log."""
        event = self.coordinator.data.last_event
        return event.user if event else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Panel attributes.

        The session token used to be published here, putting a live credential
        into the states API, the recorder database and every dashboard showing
        the entity. It is deliberately absent.
        """
        data = self.coordinator.data
        event = data.last_event
        return {
            "serial_number": data.serial,
            "model": data.model,
            "alias": data.alias,
            "ready": data.ready,
            # Derived so a routine check-in gap does not rewrite this entity
            # (and a recorder row with it) every ~90 seconds.
            "connected": data.is_cloud_connected,
            "alarm": data.alarm_active,
            "trouble_count": len(data.troubles),
            "trouble_types": [t.get("trouble_type") for t in data.troubles],
            "changed_timestamp": event.timestamp if event else None,
        }

    def _check_code(self, code: str | None) -> None:
        """Validate the user-entered code."""
        if self._no_pin_required:
            return
        if code != self._code:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="invalid_code")

    def _check_ready(self) -> None:
        """Refuse to arm when the panel reports open zones."""
        if not self.coordinator.data.ready:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_ready")

    async def _async_set(self, state: str) -> None:
        try:
            await self.coordinator.async_set_state(state)
        except VisonicError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"error": str(err)},
            ) from err

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command."""
        self._check_code(code)
        await self._async_set(STATE_DISARM)

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm home command."""
        self._check_code(code)
        self._check_ready()
        await self._async_set(STATE_HOME)

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command."""
        self._check_code(code)
        self._check_ready()
        await self._async_set(STATE_AWAY)
