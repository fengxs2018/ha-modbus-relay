"""DataUpdateCoordinator for the Modbus RTU relay module."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .modbus_rtu import ModbusRtuClient, ModbusRtuError

_LOGGER = logging.getLogger(__name__)


class RelayCoordinator(DataUpdateCoordinator[dict[int, bool]]):
    """Poll the relay module for the state of every channel."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: ModbusRtuClient,
        channels: int,
        scan_interval: int,
        read_state: bool,
    ) -> None:
        self.client = client
        self.channels = channels
        self.read_state = read_state
        self._optimistic: dict[int, bool] = {}
        self._read_failures = 0

        update_interval = (
            timedelta(seconds=scan_interval) if (scan_interval and read_state) else None
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
        )

    async def _async_update_data(self) -> dict[int, bool]:
        if not self.read_state:
            return dict(self._optimistic)

        try:
            states = await self.client.read_coils(0, self.channels)
        except (ModbusRtuError, OSError, asyncio.TimeoutError) as err:
            self._read_failures += 1
            if self._read_failures == 1 or self._read_failures % 10 == 0:
                _LOGGER.warning(
                    "Failed to read relay states (%s) - failure #%s, "
                    "keeping last known state",
                    err,
                    self._read_failures,
                )
            raise UpdateFailed(f"Error reading relay state: {err}") from err

        self._read_failures = 0
        data = {index: states[index] for index in range(self.channels)}
        self._optimistic = dict(data)
        return data

    async def async_set_channel(self, channel: int, state: bool) -> None:
        """Turn a single relay channel on or off."""
        try:
            await self.client.write_coil(channel, state)
        except (ModbusRtuError, OSError, asyncio.TimeoutError) as err:
            raise HomeAssistantError(
                f"Failed to switch relay channel {channel + 1}: {err}"
            ) from err

        # Update the UI immediately instead of waiting for the next poll or
        # for the debounced refresh; the periodic read then confirms the
        # real hardware state.
        self._optimistic[channel] = state
        data = dict(self.data or {})
        data[channel] = state
        self.async_set_updated_data(data)

        if self.read_state:
            await self.async_request_refresh()

    async def async_turn_all(self, state: bool) -> None:
        """Turn every channel on or off."""
        for channel in range(self.channels):
            await self.async_set_channel(channel, state)

    def get_state(self, channel: int) -> bool | None:
        """Return the last known (or optimistic) state of a channel."""
        if self.data and channel in self.data:
            return self.data[channel]
        return self._optimistic.get(channel)
