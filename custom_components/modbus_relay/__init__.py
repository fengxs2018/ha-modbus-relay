"""The Modbus RTU multi-channel relay integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_CHANNELS,
    CONF_READ_STATE,
    CONF_SLAVE,
    DEFAULT_CHANNELS,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SLAVE,
    DEFAULT_TIMEOUT,
    DOMAIN,
)
from .coordinator import RelayCoordinator
from .modbus_rtu import ModbusRtuClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch"]

SERVICE_TURN_ALL = "turn_all"
SERVICE_TURN_ALL_SCHEMA = vol.Schema(
    {
        vol.Optional("state", default=True): cv.boolean,
        vol.Optional("entry_id"): cv.string,
    }
)


def _merged(entry: ConfigEntry) -> dict[str, Any]:
    """Return entry data with options applied on top."""
    return {**entry.data, **entry.options}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the relay module from a config entry."""
    conf = _merged(entry)

    client = ModbusRtuClient(
        host=conf["host"],
        port=conf.get("port", DEFAULT_PORT),
        slave=conf.get(CONF_SLAVE, DEFAULT_SLAVE),
        timeout=DEFAULT_TIMEOUT,
    )
    coordinator = RelayCoordinator(
        hass,
        client,
        channels=int(conf.get(CONF_CHANNELS, DEFAULT_CHANNELS)),
        scan_interval=int(conf.get("scan_interval", DEFAULT_SCAN_INTERVAL)),
        read_state=bool(conf.get(CONF_READ_STATE, True)),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    async def handle_turn_all(call: ServiceCall) -> None:
        state = bool(call.data.get("state", True))
        entry_id = call.data.get("entry_id") or entry.entry_id
        target: RelayCoordinator | None = hass.data.get(DOMAIN, {}).get(entry_id)
        if target is None:
            _LOGGER.error("No relay entry loaded with id %s", entry_id)
            return
        await target.async_turn_all(state)

    if not hass.services.has_service(DOMAIN, SERVICE_TURN_ALL):
        hass.services.async_register(
            DOMAIN, SERVICE_TURN_ALL, handle_turn_all, schema=SERVICE_TURN_ALL_SCHEMA
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: RelayCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.client.close()
        if not hass.data[DOMAIN] and hass.services.has_service(DOMAIN, SERVICE_TURN_ALL):
            hass.services.async_remove(DOMAIN, SERVICE_TURN_ALL)
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
