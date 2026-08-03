"""Coordinator behaviour: polling cadence, error mapping, optional endpoints."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.visonicalarm.api import VisonicAuthError, VisonicError
from custom_components.visonicalarm.const import (
    CONF_EVENT_HOUR_OFFSET,
    SLOW_SCAN_INTERVAL,
)

from .conftest import FakeApi

PANEL = "alarm_control_panel.example_house"


async def test_arming_state_is_derived_from_exit_status(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeApi
) -> None:
    """A partition in EXIT while armed means arming, not armed."""
    fake_api.status["partitions"][0].update({"state": "AWAY", "status": "EXIT"})
    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(PANEL).state == "arming"


async def test_active_alarm_overrides_arm_state(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeApi
) -> None:
    """An active alarm while armed reports triggered."""
    fake_api.status["partitions"][0]["state"] = "AWAY"
    with patch.object(fake_api, "async_get_alarms", return_value=[{"id": 1}]):
        await hass.config_entries.async_reload(setup_integration.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get(PANEL).state == "triggered"


async def test_alarm_while_disarmed_keeps_partition_state(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeApi
) -> None:
    """An alarm recorded while disarmed does not fake an armed state."""
    fake_api.status["partitions"][0]["state"] = "DISARM"
    with patch.object(fake_api, "async_get_alarms", return_value=[{"id": 1}]):
        await hass.config_entries.async_reload(setup_integration.entry_id)
        await hass.async_block_till_done()

    assert hass.states.get(PANEL).state == "disarmed"


async def test_optional_endpoints_may_fail(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeApi
) -> None:
    """Newer endpoints are absent on some firmware; that must not break setup."""
    with (
        patch.object(fake_api, "async_get_feature_set", side_effect=VisonicError("404")),
        patch.object(fake_api, "async_get_users", side_effect=VisonicError("404")),
        patch.object(fake_api, "async_get_panels", side_effect=VisonicError("404")),
    ):
        await hass.config_entries.async_reload(setup_integration.entry_id)
        await hass.async_block_till_done()

    assert setup_integration.state is ConfigEntryState.LOADED
    assert hass.states.get(PANEL) is not None


async def test_update_failure_marks_entities_unavailable(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    """A failed poll makes entities unavailable rather than serving stale data."""
    with patch.object(fake_api, "async_get_status", side_effect=VisonicError("down")):
        freezer.tick(timedelta(seconds=30))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    assert hass.states.get(PANEL).state == "unavailable"


async def test_auth_failure_during_update_triggers_reauth(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeApi
) -> None:
    """An expired session that cannot be recovered starts a reauth flow."""
    with patch.object(fake_api, "async_get_status", side_effect=VisonicAuthError("nope")):
        await hass.config_entries.async_reload(setup_integration.entry_id)
        await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_slow_endpoints_are_not_polled_every_cycle(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeApi,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Troubles and events poll on their own, slower cadence."""
    with patch.object(
        fake_api, "async_get_troubles", wraps=fake_api.async_get_troubles
    ) as troubles:
        freezer.tick(timedelta(seconds=30))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert troubles.call_count == 0

        freezer.tick(SLOW_SCAN_INTERVAL + timedelta(seconds=30))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
        assert troubles.call_count >= 1


async def test_hour_offset_is_read_from_options(
    hass: HomeAssistant, mock_entry: MockConfigEntry, fake_api: FakeApi
) -> None:
    """The offset option reaches the coordinator."""
    hass.config_entries.async_update_entry(mock_entry, options={CONF_EVENT_HOUR_OFFSET: 4})
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_entry.runtime_data.hour_offset == 4


async def test_set_state_refreshes(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeApi
) -> None:
    """A command triggers an immediate refresh rather than waiting."""
    coordinator = setup_integration.runtime_data
    await coordinator.async_set_state("DISARM")
    await hass.async_block_till_done()
    assert fake_api.set_state_calls == ["DISARM"]


async def test_update_failed_is_raised_for_generic_errors(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeApi
) -> None:
    """Generic API errors surface as UpdateFailed."""
    coordinator = setup_integration.runtime_data
    with (
        patch.object(fake_api, "async_get_status", side_effect=VisonicError("x")),
        pytest.raises(UpdateFailed),
    ):
        await coordinator._async_update_data()  # noqa: SLF001
