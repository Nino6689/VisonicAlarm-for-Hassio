"""Config flow tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_IMPORT, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.visonicalarm.api import (
    VisonicAuthError,
    VisonicConnectionError,
    VisonicError,
)
from custom_components.visonicalarm.const import (
    CONF_APP_ID,
    CONF_EVENT_HOUR_OFFSET,
    CONF_NO_PIN_REQUIRED,
    CONF_PANEL_ID,
    CONF_USER_CODE,
    CONF_USER_EMAIL,
    CONF_USER_PASSWORD,
    DOMAIN,
)

from .conftest import ENTRY_DATA, FakeApi

USER_INPUT: dict[str, Any] = {
    "host": "visonic.example.com",
    CONF_USER_EMAIL: "user@example.com",
    CONF_USER_PASSWORD: "hunter2",
    CONF_PANEL_ID: "1D0B0A",
    CONF_USER_CODE: "1234",
    CONF_APP_ID: "",
}


async def test_user_flow_creates_entry(
    hass: HomeAssistant, fake_api: FakeApi, mock_setup_entry: AsyncMock
) -> None:
    """A valid submission creates an entry keyed on the panel serial."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.flow.async_configure(result["flow_id"], dict(USER_INPUT))
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "PowerMaster 360R"
    assert result["result"].unique_id == "1D0B0A"
    # A blank app id is filled in rather than rejected.
    assert result["data"][CONF_APP_ID]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (VisonicAuthError("no"), "invalid_auth"),
        (VisonicConnectionError("no"), "cannot_connect"),
        (VisonicError("no"), "unknown"),
    ],
)
async def test_user_flow_errors_then_recovers(
    hass: HomeAssistant,
    fake_api: FakeApi,
    mock_setup_entry: AsyncMock,
    error: Exception,
    expected: str,
) -> None:
    """Each failure shows its error, and the form still works afterwards."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})

    with patch.object(fake_api, "async_connect", side_effect=error):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], dict(USER_INPUT))
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}

    result = await hass.config_entries.flow.async_configure(result["flow_id"], dict(USER_INPUT))
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_duplicate_panel_aborts(
    hass: HomeAssistant, fake_api: FakeApi, mock_entry: MockConfigEntry
) -> None:
    """The same panel cannot be added twice."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], dict(USER_INPUT))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_import_from_yaml(
    hass: HomeAssistant, fake_api: FakeApi, mock_setup_entry: AsyncMock
) -> None:
    """YAML import creates an entry and carries options across."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_IMPORT},
        data={**ENTRY_DATA, CONF_NO_PIN_REQUIRED: True, CONF_EVENT_HOUR_OFFSET: 2},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_NO_PIN_REQUIRED] is True
    assert result["options"][CONF_EVENT_HOUR_OFFSET] == 2


async def test_import_aborts_on_bad_credentials(hass: HomeAssistant, fake_api: FakeApi) -> None:
    """A YAML block with dead credentials must not create a broken entry."""
    with patch.object(fake_api, "async_connect", side_effect=VisonicAuthError("no")):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data=dict(ENTRY_DATA)
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_auth"


async def test_reauth_updates_credentials(
    hass: HomeAssistant, fake_api: FakeApi, mock_entry: MockConfigEntry
) -> None:
    """Reauth rewrites the stored password."""
    result = await mock_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM

    with patch("custom_components.visonicalarm.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER_INPUT, CONF_USER_PASSWORD: "newpass"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_entry.data[CONF_USER_PASSWORD] == "newpass"


async def test_reauth_shows_error_first(
    hass: HomeAssistant, fake_api: FakeApi, mock_entry: MockConfigEntry
) -> None:
    """Bad credentials during reauth are reported, not stored."""
    result = await mock_entry.start_reauth_flow(hass)
    with patch.object(fake_api, "async_connect", side_effect=VisonicAuthError("no")):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], dict(USER_INPUT))
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reconfigure_updates_entry(
    hass: HomeAssistant, fake_api: FakeApi, mock_entry: MockConfigEntry
) -> None:
    """Reconfigure can change the host."""
    result = await mock_entry.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.FORM

    with patch("custom_components.visonicalarm.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER_INPUT, "host": "other.example.com"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert mock_entry.data["host"] == "other.example.com"


async def test_reconfigure_rejects_a_different_panel(
    hass: HomeAssistant, fake_api: FakeApi, mock_entry: MockConfigEntry
) -> None:
    """Reconfiguring must not silently repoint the entry at another panel."""
    result = await mock_entry.start_reconfigure_flow(hass)

    other = {"serial": "OTHER1", "model": "PowerMaster 10"}
    with patch.object(fake_api, "async_get_panel_info", return_value=other):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], dict(USER_INPUT))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_panel"


async def test_options_flow(hass: HomeAssistant, setup_integration: MockConfigEntry) -> None:
    """Options round-trip through the flow."""
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_NO_PIN_REQUIRED: True, CONF_EVENT_HOUR_OFFSET: 3},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_integration.options[CONF_NO_PIN_REQUIRED] is True
