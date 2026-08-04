"""Entity behaviour tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.visonicalarm.api import VisonicError
from custom_components.visonicalarm.const import CONF_NO_PIN_REQUIRED, DOMAIN

from .conftest import FakeApi

PANEL = "alarm_control_panel.example_house"


async def test_entity_ids_are_preserved(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The historical unique_ids must survive the config-entry migration.

    These exact values pin entity IDs that dashboards and automations use.
    ⚠️ The legacy zone sensors are registered with **integer** unique_ids.
    """
    registry = er.async_get(hass)
    by_unique = {
        e.unique_id: e.entity_id for e in registry.entities.values() if e.platform == DOMAIN
    }

    assert "ABC123" in by_unique  # the alarm panel
    assert "visonic_alarm_cloud_connection" in by_unique
    assert "visonic_alarm_problem" in by_unique
    assert "visonic_alarm_transport_bba" in by_unique
    assert "visonic_zone_828776" in by_unique
    assert "visonic_alarm_trouble_count" in by_unique

    # Integer, deliberately — a string here would orphan the entity.
    assert 828776 in by_unique
    assert isinstance(
        next(k for k in by_unique if k == 828776),
        int,
    )


async def test_devices_are_registered(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """One panel device, plus one per zone, linked via_device."""
    devices = dr.async_get(hass)
    entries = dr.async_entries_for_config_entry(devices, setup_integration.entry_id)
    names = {d.name for d in entries}

    assert "Example House" in names
    assert "Living room" in names
    assert "Kitchen" in names

    panel = next(d for d in entries if d.name == "Example House")
    zone = next(d for d in entries if d.name == "Kitchen")
    assert zone.via_device_id == panel.id


async def test_panel_state_and_attributes(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The panel reflects the fixture state and exposes no credentials."""
    state = hass.states.get(PANEL)
    assert state is not None
    assert state.state == "disarmed"
    assert state.attributes["connected"] is True
    assert state.attributes["trouble_count"] == 2
    # The session token must never be published.
    assert not any("token" in k.lower() for k in state.attributes)


async def test_zone_naming_prefers_explicit_name(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Explicit device names beat the panel's abbreviated room labels."""
    registry = er.async_get(hass)
    entity = registry.async_get_entity_id("binary_sensor", DOMAIN, "visonic_zone_6151684")
    assert entity is not None
    state = hass.states.get(entity)
    assert state is not None
    # Device name is "Master Bedroom"; the panel location is "Master Bdrm".
    assert "Master Bedroom" in state.attributes["friendly_name"]


async def test_faulty_device_surfaces_room(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Device warnings name the room, which the trouble list may not."""
    state = hass.states.get("binary_sensor.example_house_problem")
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes["faulty_devices"] == {"Kitchen": ["INACTIVE", "1_WAY"]}


async def test_bypass_switch_round_trip(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeApi
) -> None:
    """Bypassing a zone sends the zone number, not the device id."""
    registry = er.async_get(hass)
    entity = registry.async_get_entity_id("switch", DOMAIN, "visonic_bypass_6148586")
    assert entity is not None
    assert hass.states.get(entity).state == STATE_OFF

    await hass.services.async_call("switch", "turn_on", {ATTR_ENTITY_ID: entity}, blocking=True)
    await hass.async_block_till_done()

    # Kitchen is device 6148586 but zone number 5.
    assert fake_api.bypass_calls == [(5, True)]
    assert hass.states.get(entity).state == STATE_ON

    await hass.services.async_call("switch", "turn_off", {ATTR_ENTITY_ID: entity}, blocking=True)
    assert fake_api.bypass_calls[-1] == (5, False)


async def test_arm_requires_correct_code(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeApi
) -> None:
    """A wrong code is a user error, not a panel error."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "alarm_control_panel",
            "alarm_arm_away",
            {ATTR_ENTITY_ID: PANEL, "code": "9999"},
            blocking=True,
        )
    assert fake_api.set_state_calls == []

    await hass.services.async_call(
        "alarm_control_panel",
        "alarm_arm_away",
        {ATTR_ENTITY_ID: PANEL, "code": "1234"},
        blocking=True,
    )
    assert fake_api.set_state_calls == ["AWAY"]


async def test_arm_refused_when_not_ready(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    fake_api: FakeApi,
) -> None:
    """Arming with an open zone is refused before any request is sent."""
    fake_api.status["partitions"][0]["ready"] = False
    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "alarm_control_panel",
            "alarm_arm_home",
            {ATTR_ENTITY_ID: PANEL, "code": "1234"},
            blocking=True,
        )
    assert fake_api.set_state_calls == []


async def test_panel_error_is_reported(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeApi
) -> None:
    """A panel-side failure raises HomeAssistantError."""
    with (
        patch.object(fake_api, "async_set_state", side_effect=VisonicError("nope")),
        pytest.raises(HomeAssistantError),
    ):
        await hass.services.async_call(
            "alarm_control_panel",
            "alarm_disarm",
            {ATTR_ENTITY_ID: PANEL, "code": "1234"},
            blocking=True,
        )


async def test_no_pin_option_skips_the_code(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeApi
) -> None:
    """With the option set, no code is required."""
    hass.config_entries.async_update_entry(setup_integration, options={CONF_NO_PIN_REQUIRED: True})
    await hass.async_block_till_done()

    await hass.services.async_call(
        "alarm_control_panel", "alarm_disarm", {ATTR_ENTITY_ID: PANEL}, blocking=True
    )
    assert fake_api.set_state_calls == ["DISARM"]


async def test_zone_becomes_unavailable_when_unenrolled(
    hass: HomeAssistant, setup_integration: MockConfigEntry, fake_api: FakeApi
) -> None:
    """A device removed from the panel stops reporting a state."""
    registry = er.async_get(hass)
    entity = registry.async_get_entity_id("binary_sensor", DOMAIN, "visonic_zone_828776")
    assert hass.states.get(entity).state != STATE_UNAVAILABLE

    fake_api.devices = [d for d in fake_api.devices if d["id"] != 828776]
    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(entity).state == STATE_UNAVAILABLE


async def test_last_event_uses_label_not_type_id(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """type_id 173 has no entry in the legacy map; the label must win."""
    state = hass.states.get("sensor.example_house_last_event")
    assert state is not None
    assert state.state == "DISARM"
    assert state.attributes["description"] == "Disarm after alarm"
