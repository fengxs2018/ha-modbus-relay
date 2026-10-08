"""Switch platform: one switch entity per relay channel."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import CONF_CHANNELS, DOMAIN, MANUFACTURER
from .coordinator import RelayCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one switch entity for each configured relay channel."""
    coordinator: RelayCoordinator = hass.data[DOMAIN][entry.entry_id]
    channels: int = entry.data[CONF_CHANNELS]

    async_add_entities(
        RelaySwitch(coordinator, entry, channel) for channel in range(channels)
    )


class RelaySwitch(CoordinatorEntity[RelayCoordinator], SwitchEntity):
    """A single relay channel exposed as a switch."""

    _attr_device_class = SwitchDeviceClass.SWITCH
    _attr_has_entity_name = True

    def __init__(self, coordinator: RelayCoordinator, entry: ConfigEntry, channel: int) -> None:
        super().__init__(coordinator, context=channel)
        self._channel = channel
        self._attr_name = f"回路 {channel + 1}"
        self._attr_unique_id = f"{entry.entry_id}_ch{channel + 1}"
        # Chinese names slugify to an empty string, so fall back to the domain
        # to keep entity ids readable (e.g. switch.modbus_relay_ch1).
        prefix = slugify(entry.title) or DOMAIN
        self.entity_id = async_generate_entity_id(
            "switch.{}", f"{prefix}_ch{channel + 1}", hass=coordinator.hass
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=f"Modbus RTU 继电器 ({entry.data.get(CONF_CHANNELS)} 路)",
        )

    @property
    def is_on(self) -> bool | None:
        """Return True if the relay channel is energised."""
        return self.coordinator.get_state(self._channel)

    @property
    def icon(self) -> str:
        return "mdi:electric-switch-closed" if self.is_on else "mdi:electric-switch"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "channel": self._channel + 1,
            "modbus_coil_address": self._channel,
            "slave_id": self.coordinator.client.slave,
            "host": self.coordinator.client.host,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_channel(self._channel, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_set_channel(self._channel, False)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
