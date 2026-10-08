"""Config flow for the Modbus RTU multi-channel relay integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT, CONF_SCAN_INTERVAL
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_CHANNELS,
    CONF_READ_STATE,
    CONF_SLAVE,
    DEFAULT_CHANNELS,
    DEFAULT_HOST,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SLAVE,
    DEFAULT_TIMEOUT,
    DOMAIN,
    MAX_CHANNELS,
    MAX_SCAN_INTERVAL,
    MIN_CHANNELS,
)
from .modbus_rtu import ModbusRtuClient, ModbusRtuError

_LOGGER = logging.getLogger(__name__)


def _build_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, DEFAULT_HOST)): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Required(CONF_SLAVE, default=defaults.get(CONF_SLAVE, DEFAULT_SLAVE)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=255)
            ),
            vol.Required(
                CONF_CHANNELS, default=defaults.get(CONF_CHANNELS, DEFAULT_CHANNELS)
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_CHANNELS, max=MAX_CHANNELS)),
            vol.Optional(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): str,
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=defaults.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_SCAN_INTERVAL)),
            vol.Required(CONF_READ_STATE, default=defaults.get(CONF_READ_STATE, True)): bool,
        }
    )


class RelayConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the initial setup of a relay module."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            client = ModbusRtuClient(
                host=user_input[CONF_HOST],
                port=user_input[CONF_PORT],
                slave=user_input[CONF_SLAVE],
                timeout=DEFAULT_TIMEOUT,
            )
            try:
                if user_input.get(CONF_READ_STATE, True):
                    await client.test_connection()
                else:
                    # Only the TCP link can be verified when state read-back
                    # is disabled.
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(
                            user_input[CONF_HOST], user_input[CONF_PORT]
                        ),
                        timeout=DEFAULT_TIMEOUT,
                    )
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:  # noqa: BLE001
                        pass
            except (ModbusRtuError, OSError, asyncio.TimeoutError) as err:
                _LOGGER.warning("Cannot reach relay module: %s", err)
                errors["base"] = "cannot_connect"
            finally:
                await client.close()

            if not errors:
                name = user_input.get(CONF_NAME) or DEFAULT_NAME
                await self.async_set_unique_id(
                    f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}:"
                    f"{user_input[CONF_SLAVE]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=name, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=_build_schema({}), errors=errors
        )

    @staticmethod
    def async_get_options_flow(
        entry: config_entries.ConfigEntry,
    ) -> RelayOptionsFlow:
        return RelayOptionsFlow(entry)


class RelayOptionsFlow(config_entries.OptionsFlow):
    """Allow tweaking polling and channel count after setup."""

    def __init__(self, entry: config_entries.ConfigEntry | None = None) -> None:
        # Older Home Assistant releases pass the entry to the constructor,
        # newer ones inject it via the `config_entry` attribute instead.
        self._entry = entry

    @property
    def entry(self) -> config_entries.ConfigEntry:
        return self._entry or getattr(self, "config_entry")

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        merged = {**self.entry.data, **self.entry.options}

        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CHANNELS,
                        default=merged.get(CONF_CHANNELS, DEFAULT_CHANNELS),
                    ): vol.All(vol.Coerce(int), vol.Range(min=MIN_CHANNELS, max=MAX_CHANNELS)),
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=merged.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_SCAN_INTERVAL)),
                    vol.Required(
                        CONF_READ_STATE, default=merged.get(CONF_READ_STATE, True)
                    ): bool,
                }
            ),
        )
