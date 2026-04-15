from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CONF_LOGINNAME, CONF_PASSWORD, CONF_REGION, DEFAULT_REGION, DOMAIN, TITLE
from .core.async_client import YQTApiClient
from .core.protocol import REGIONS, YQTAuthError, YQTError


def _user_schema(user_input: dict[str, Any] | None = None) -> vol.Schema:
    user_input = user_input or {}
    return vol.Schema(
        {
            vol.Required(CONF_REGION, default=user_input.get(CONF_REGION, DEFAULT_REGION)): vol.In(sorted(REGIONS)),
            vol.Required(CONF_LOGINNAME, default=user_input.get(CONF_LOGINNAME, "")): str,
            vol.Required(CONF_PASSWORD): str,
        }
    )


def _reauth_schema() -> vol.Schema:
    return vol.Schema({vol.Required(CONF_PASSWORD): str})


class YQTConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if user_input is not None:
            unique_id = f"{user_input[CONF_REGION]}:{user_input[CONF_LOGINNAME]}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            client = YQTApiClient(
                async_get_clientsession(self.hass),
                region=user_input[CONF_REGION],
                loginname=user_input[CONF_LOGINNAME],
                password=user_input[CONF_PASSWORD],
            )
            try:
                await client.async_login()
            except YQTAuthError:
                errors["base"] = "invalid_auth"
            except YQTError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=f"{TITLE} ({user_input[CONF_LOGINNAME]})", data=user_input)

        return self.async_show_form(step_id="user", data_schema=_user_schema(user_input), errors=errors)

    async def async_step_reauth(self, entry_data: dict[str, Any]):
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None):
        errors: dict[str, str] = {}
        if self._reauth_entry is None:
            return self.async_abort(reason="reauth_unsuccessful")

        if user_input is not None:
            data = {
                **self._reauth_entry.data,
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            client = YQTApiClient(
                async_get_clientsession(self.hass),
                region=data[CONF_REGION],
                loginname=data[CONF_LOGINNAME],
                password=data[CONF_PASSWORD],
            )
            try:
                await client.async_login()
            except YQTAuthError:
                errors["base"] = "invalid_auth"
            except YQTError:
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(self._reauth_entry, data=data)
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(step_id="reauth_confirm", data_schema=_reauth_schema(), errors=errors)
