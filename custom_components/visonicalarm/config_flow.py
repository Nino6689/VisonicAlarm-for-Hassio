"""Config flow for the Visonic Alarm integration."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import VisonicApi, VisonicAuthError, VisonicConnectionError, VisonicError
from .const import (
    CONF_APP_ID,
    CONF_EVENT_HOUR_OFFSET,
    CONF_NO_PIN_REQUIRED,
    CONF_PANEL_ID,
    CONF_USER_CODE,
    CONF_USER_EMAIL,
    CONF_USER_PASSWORD,
    DEFAULT_HOST,
    DEFAULT_NAME,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def _user_schema(defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    """Build the credentials form, pre-filled from `defaults` where given."""
    d = defaults or {}
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=d.get(CONF_HOST, DEFAULT_HOST)): str,
            vol.Required(CONF_USER_EMAIL, default=d.get(CONF_USER_EMAIL, "")): (
                TextSelector(TextSelectorConfig(type=TextSelectorType.EMAIL))
            ),
            vol.Required(CONF_USER_PASSWORD): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Required(CONF_PANEL_ID, default=d.get(CONF_PANEL_ID, "")): str,
            vol.Required(CONF_USER_CODE): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_APP_ID, default=d.get(CONF_APP_ID, "")): str,
        }
    )


async def _async_validate(
    hass: Any, data: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Try the credentials against the panel.

    Quality scale (test-before-configure): the flow must not create an entry it
    cannot use. Returns ``(panel_info, errors)``.
    """
    api = VisonicApi(
        async_get_clientsession(hass),
        data.get(CONF_HOST, DEFAULT_HOST),
        data[CONF_APP_ID],
        data[CONF_USER_CODE],
        data[CONF_USER_EMAIL],
        data[CONF_USER_PASSWORD],
        data[CONF_PANEL_ID],
    )
    try:
        await api.async_connect()
        return await api.async_get_panel_info(), {}
    except VisonicAuthError:
        return {}, {"base": "invalid_auth"}
    except VisonicConnectionError:
        return {}, {"base": "cannot_connect"}
    except VisonicError:
        _LOGGER.exception("Unexpected error validating Visonic credentials")
        return {}, {"base": "unknown"}


class VisonicConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Visonic Alarm."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise per-flow state."""
        self._reauth_entry: ConfigEntry | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> VisonicOptionsFlow:
        """Return the options flow."""
        return VisonicOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Collect credentials from the user."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # The app id is an arbitrary client identifier. Generating one keeps
            # the form short and avoids two installs sharing an id.
            if not user_input.get(CONF_APP_ID):
                user_input[CONF_APP_ID] = str(uuid.uuid4())

            info, errors = await _async_validate(self.hass, user_input)
            if not errors:
                serial = info.get("serial") or user_input[CONF_PANEL_ID]
                await self.async_set_unique_id(str(serial))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=info.get("model") or DEFAULT_NAME,
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_user_schema(user_input),
            errors=errors,
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Import the legacy `visonicalarm:` YAML block.

        Entity IDs survive because they are pinned by ``unique_id``, which is
        unchanged: the panel serial for the control panel, and the raw Visonic
        device id for each zone.
        """
        if not import_data.get(CONF_APP_ID):
            import_data[CONF_APP_ID] = str(uuid.uuid4())

        info, errors = await _async_validate(self.hass, import_data)
        if errors:
            return self.async_abort(reason=errors["base"])

        serial = info.get("serial") or import_data[CONF_PANEL_ID]
        await self.async_set_unique_id(str(serial))
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=info.get("model") or DEFAULT_NAME,
            data=import_data,
            options={
                CONF_NO_PIN_REQUIRED: import_data.get(CONF_NO_PIN_REQUIRED, False),
                CONF_EVENT_HOUR_OFFSET: import_data.get(CONF_EVENT_HOUR_OFFSET, 0),
            },
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Handle credentials being rejected while running."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for fresh credentials and update the existing entry."""
        errors: dict[str, str] = {}
        entry = self._reauth_entry
        assert entry is not None

        if user_input is not None:
            merged = {**entry.data, **user_input}
            _info, errors = await _async_validate(self.hass, merged)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=merged)

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_user_schema(entry.data),
            errors=errors,
            description_placeholders={"panel": entry.title},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user change connection details after setup."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            merged = {**entry.data, **user_input}
            if not merged.get(CONF_APP_ID):
                merged[CONF_APP_ID] = str(uuid.uuid4())

            info, errors = await _async_validate(self.hass, merged)
            if not errors:
                serial = info.get("serial") or merged[CONF_PANEL_ID]
                await self.async_set_unique_id(str(serial))
                self._abort_if_unique_id_mismatch(reason="wrong_panel")
                return self.async_update_reload_and_abort(entry, data=merged)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_user_schema(entry.data),
            errors=errors,
        )


class VisonicOptionsFlow(OptionsFlow):
    """Options that do not require re-authenticating."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        options = self.config_entry.options
        data = self.config_entry.data
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NO_PIN_REQUIRED,
                        default=options.get(
                            CONF_NO_PIN_REQUIRED,
                            data.get(CONF_NO_PIN_REQUIRED, False),
                        ),
                    ): bool,
                    vol.Required(
                        CONF_EVENT_HOUR_OFFSET,
                        default=options.get(
                            CONF_EVENT_HOUR_OFFSET,
                            data.get(CONF_EVENT_HOUR_OFFSET, 0),
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(min=-24, max=24, step=1, mode=NumberSelectorMode.BOX)
                    ),
                }
            ),
        )
