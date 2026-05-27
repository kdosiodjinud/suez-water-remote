"""Config flow for the Suez Water Remote integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from aiohttp import CookieJar
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    SuezAuthenticationError,
    SuezConnectionError,
    SuezError,
    SuezVhsClient,
    derive_base_url,
)
from .const import CONF_BASE_URL, CONF_LOCALE, CONF_METERS, CONF_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL, autocomplete="url")
        ),
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.TEXT, autocomplete="username"
            )
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)


# ``domain`` is a valid class keyword on the real (typed) ConfigFlow; mypy only
# flags it because Home Assistant is treated as an untyped import here.
class SuezWaterConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    """Two-step flow: URL+credentials → meter selection."""

    VERSION = 1

    def __init__(self) -> None:
        self._collected: dict[str, Any] = {}
        self._meters: tuple[str, ...] = ()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect URL + credentials, probe the portal, then either finish
        immediately (single meter) or move on to meter selection."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                base_url = str(derive_base_url(user_input[CONF_URL]))
            except ValueError:
                errors[CONF_URL] = "invalid_url"
            else:
                try:
                    locale_code, meters = await self._probe_credentials(
                        base_url,
                        user_input[CONF_USERNAME],
                        user_input[CONF_PASSWORD],
                    )
                except SuezAuthenticationError:
                    errors["base"] = "invalid_auth"
                except SuezConnectionError:
                    errors["base"] = "cannot_connect"
                except SuezError as err:
                    _LOGGER.warning("unexpected portal error: %s", err)
                    errors["base"] = "unknown"
                else:
                    self._collected = {
                        CONF_URL: user_input[CONF_URL],
                        CONF_BASE_URL: base_url,
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_LOCALE: locale_code,
                    }
                    self._meters = meters
                    # Unique-id ties an account to a portal so that two
                    # accounts on different portals don't collide.
                    await self.async_set_unique_id(
                        f"{base_url}#{user_input[CONF_USERNAME]}"
                    )
                    self._abort_if_unique_id_configured(updates=self._collected)
                    if len(meters) == 1:
                        return self._create_entry(meters)
                    return await self.async_step_meters()
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_meters(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick meters when more than one is detected."""
        if user_input is not None:
            selected: list[str] = user_input[CONF_METERS]
            if not selected:
                return self.async_show_form(
                    step_id="meters",
                    data_schema=self._meters_schema(),
                    errors={"base": "select_at_least_one"},
                )
            return self._create_entry(tuple(selected))
        return self.async_show_form(
            step_id="meters", data_schema=self._meters_schema()
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        self._collected = dict(entry_data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await self._probe_credentials(
                    self._collected[CONF_BASE_URL],
                    self._collected[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except SuezAuthenticationError:
                errors["base"] = "invalid_auth"
            except SuezConnectionError:
                errors["base"] = "cannot_connect"
            except SuezError:
                errors["base"] = "unknown"
            else:
                entry = self._get_reauth_entry()
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.PASSWORD,
                            autocomplete="current-password",
                        )
                    )
                }
            ),
            description_placeholders={
                "username": str(self._collected.get(CONF_USERNAME, "")),
                "base_url": str(self._collected.get(CONF_BASE_URL, "")),
            },
            errors=errors,
        )

    # -- helpers -------------------------------------------------------------

    async def _probe_credentials(
        self, base_url: str, username: str, password: str
    ) -> tuple[str, tuple[str, ...]]:
        """Try to log in to ``base_url``, return (locale, meters) on success."""
        # Use a throw-away session with its own cookie jar so the probe does
        # not contaminate other integrations sharing HA's shared session.
        session = async_create_clientsession(
            self.hass, cookie_jar=CookieJar(unsafe=False)
        )
        client = SuezVhsClient(
            username, password, base_url=base_url, session=session
        )
        # The session is created via ``async_create_clientsession`` and is
        # therefore owned and cleaned up by Home Assistant on shutdown; the
        # client must not close it here.
        await client.async_login()
        meters = await client.async_discover_meters()
        return client.locale.code, meters

    def _create_entry(self, meters: tuple[str, ...]) -> ConfigFlowResult:
        username = self._collected[CONF_USERNAME]
        title = f"{username} ({', '.join(meters)})" if meters else username
        return self.async_create_entry(
            title=title,
            data={**self._collected, CONF_METERS: list(meters)},
        )

    def _meters_schema(self) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required(
                    CONF_METERS, default=list(self._meters)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=list(self._meters),
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )
