"""Shared fixtures for the Visonic Alarm tests."""

from __future__ import annotations

import copy
from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.visonicalarm.const import (
    CONF_APP_ID,
    CONF_PANEL_ID,
    CONF_USER_CODE,
    CONF_USER_EMAIL,
    CONF_USER_PASSWORD,
    DOMAIN,
)

from .fixtures import (
    ALARMS,
    ALERTS,
    DEVICES,
    EVENTS,
    FEATURE_SET,
    PANEL_INFO,
    PANELS,
    STATUS,
    TROUBLES,
    USERS,
)

pytest_plugins = "pytest_homeassistant_custom_component"

ENTRY_DATA: dict[str, Any] = {
    "host": "visonic.example.com",
    CONF_APP_ID: "00000000-0000-0000-0000-000000000000",
    CONF_USER_CODE: "1234",
    CONF_USER_EMAIL: "user@example.com",
    CONF_USER_PASSWORD: "hunter2",
    CONF_PANEL_ID: "1D0B0A",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations: None,
) -> None:
    """Enable loading of the custom integration in every test."""
    return None


class FakeApi:
    """Stand-in for VisonicApi that serves the captured fixtures."""

    def __init__(self, **_: Any) -> None:
        """Start from a pristine copy of the fixtures."""
        self.rest_version = "14.0"
        self.status = copy.deepcopy(STATUS)
        self.devices = copy.deepcopy(DEVICES)
        self.troubles = copy.deepcopy(TROUBLES)
        self.events = copy.deepcopy(EVENTS)
        self.connect_calls = 0
        self.set_state_calls: list[str] = []
        self.bypass_calls: list[tuple[int, bool]] = []
        self.siren_calls: list[str] = []
        self.name_calls: list[tuple[str, int, str]] = []

    async def async_connect(self) -> None:
        self.connect_calls += 1

    async def async_get_panel_info(self) -> dict[str, Any]:
        return copy.deepcopy(PANEL_INFO)

    async def async_get_status(self) -> dict[str, Any]:
        return copy.deepcopy(self.status)

    async def async_get_devices(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.devices)

    async def async_get_alarms(self) -> list[dict[str, Any]]:
        return copy.deepcopy(ALARMS)

    async def async_get_troubles(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.troubles)

    async def async_get_alerts(self) -> list[dict[str, Any]]:
        return copy.deepcopy(ALERTS)

    async def async_get_events(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.events)

    async def async_get_feature_set(self) -> dict[str, Any]:
        return copy.deepcopy(FEATURE_SET)

    async def async_get_users(self) -> dict[str, Any]:
        return copy.deepcopy(USERS)

    async def async_get_panels(self) -> list[dict[str, Any]]:
        return copy.deepcopy(PANELS)

    async def async_get_cameras(self) -> list[dict[str, Any]]:
        return []

    async def async_get_smart_devices(self) -> list[dict[str, Any]]:
        return []

    async def async_get_home_automation_devices(self) -> list[dict[str, Any]]:
        return []

    async def async_get_email_notifications(self) -> dict[str, Any]:
        return {"mode": 66815, "recipient_mode": 0}

    async def async_set_state(self, state: str, partition: int = -1) -> None:
        self.set_state_calls.append(state)

    async def async_set_bypass_zone(self, zone: int, enabled: bool) -> None:
        self.bypass_calls.append((zone, enabled))
        for device in self.devices:
            if device.get("device_number") == zone and device.get("traits"):
                device["traits"].setdefault("bypass", {})["enabled"] = enabled

    async def async_activate_siren(self) -> None:
        self.siren_calls.append("on")

    async def async_disable_siren(self, mode: str = "all") -> None:
        self.siren_calls.append(f"off:{mode}")

    async def async_set_name(self, object_class: str, object_id: int, name: str) -> None:
        self.name_calls.append((object_class, object_id, name))


@pytest.fixture
def fake_api() -> Generator[FakeApi]:
    """Patch VisonicApi everywhere it is constructed."""
    # Import the modules first: patch() resolves the target by attribute, and
    # config_flow is otherwise only imported lazily by the flow manager.
    from custom_components.visonicalarm import config_flow, coordinator  # noqa: F401

    api = FakeApi()
    with (
        patch.object(coordinator, "VisonicApi", return_value=api),
        patch.object(config_flow, "VisonicApi", return_value=api),
    ):
        yield api


@pytest.fixture
def mock_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Build a config entry matching the captured panel."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=ENTRY_DATA,
        unique_id="1D0B0A",
        title="PowerMaster 360R",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, mock_entry: MockConfigEntry, fake_api: FakeApi
) -> MockConfigEntry:
    """Set up the integration with fixture data."""
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()
    return mock_entry


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Skip real setup during config-flow tests."""
    with patch("custom_components.visonicalarm.async_setup_entry", return_value=True) as mock:
        yield mock
