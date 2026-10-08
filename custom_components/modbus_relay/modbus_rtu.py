"""Minimal Modbus RTU client for a transparent RS485-to-TCP bridge.

The bridge works as a TCP server and forwards raw bytes, so the frames that
travel over the socket are plain Modbus RTU frames (slave + PDU + CRC16),
*without* the Modbus TCP MBAP header.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

_LOGGER = logging.getLogger(__name__)

READ_COILS = 0x01
WRITE_SINGLE_COIL = 0x05


class ModbusRtuError(Exception):
    """Raised when the relay module cannot be reached or answers with an error."""


def crc16(data: bytes) -> int:
    """Compute the Modbus CRC16 (polynomial 0xA001, reflected)."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def _frame(slave: int, pdu: bytes) -> bytes:
    body = bytes([slave]) + pdu
    crc = crc16(body)
    return body + bytes([crc & 0xFF, (crc >> 8) & 0xFF])


class ModbusRtuClient:
    """A tiny, dependency free Modbus RTU master over a persistent TCP link."""

    def __init__(self, host: str, port: int, slave: int, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self.slave = slave
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def _connect(self) -> None:
        if self.connected:
            return
        _LOGGER.debug("Connecting to %s:%s", self.host, self.port)
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(host=self.host, port=self.port),
            timeout=self.timeout,
        )

    def _disconnect(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:  # noqa: BLE001 - best effort cleanup
                pass
        self._reader = None
        self._writer = None

    async def close(self) -> None:
        """Close the underlying socket."""
        async with self._lock:
            self._disconnect()

    async def _transact(self, request: bytes) -> bytes:
        """Send one RTU frame and return the response payload (without CRC).

        Transparent bridges usually accept a single TCP client only and may
        silently drop an idle link, so a failed exchange is retried once on a
        freshly established connection.
        """
        async with self._lock:
            last_error: Exception | None = None
            for attempt in range(2):
                try:
                    await self._connect()
                    assert self._reader is not None
                    assert self._writer is not None

                    self._writer.write(request)
                    await asyncio.wait_for(self._writer.drain(), timeout=self.timeout)
                    return await self._read_response(request)
                except Exception as err:  # noqa: BLE001
                    last_error = err
                    # Any framing/timeout error leaves the stream in an unknown
                    # state, so drop it and rebuild on the next attempt.
                    self._disconnect()
                    if attempt == 0:
                        _LOGGER.debug(
                            "Relay exchange failed (%s), retrying on a new connection",
                            err,
                        )
            assert last_error is not None
            raise last_error

    async def _read_response(self, request: bytes) -> bytes:
        reader = self._reader
        assert reader is not None

        header = await asyncio.wait_for(reader.readexactly(3), timeout=self.timeout)
        slave, func, third = header[0], header[1], header[2]

        if slave != self.slave:
            raise ModbusRtuError(
                f"Unexpected slave address in response: {slave} (expected {self.slave})"
            )

        if func & 0x80:
            # Exception response: func, exception code, crc
            tail = await asyncio.wait_for(reader.readexactly(2), timeout=self.timeout)
            raise ModbusRtuError(
                f"Relay module returned Modbus exception 0x{func:02X} "
                f"(code {third}) for request {request.hex()}"
            )

        if func in (WRITE_SINGLE_COIL, 0x06, 0x0F, 0x10):
            tail_len = 5
        elif func in (READ_COILS, 0x02, 0x03, 0x04):
            tail_len = third + 2
        else:
            raise ModbusRtuError(f"Unsupported function code in response: 0x{func:02X}")

        tail = await asyncio.wait_for(reader.readexactly(tail_len), timeout=self.timeout)
        frame = header + tail

        received_crc = frame[-2] | (frame[-1] << 8)
        if crc16(frame[:-2]) != received_crc:
            raise ModbusRtuError("CRC check failed on response frame")

        return frame[1:-2]  # strip slave address and CRC

    async def read_coils(self, address: int, count: int) -> list[bool]:
        """Read `count` coils starting at `address` (function code 0x01)."""
        pdu = bytes(
            [
                READ_COILS,
                (address >> 8) & 0xFF,
                address & 0xFF,
                (count >> 8) & 0xFF,
                count & 0xFF,
            ]
        )
        payload = await self._transact(_frame(self.slave, pdu))
        if not payload or payload[0] != READ_COILS:
            raise ModbusRtuError("Malformed read-coils response")
        byte_count = payload[1]
        data = payload[2 : 2 + byte_count]
        if len(data) < byte_count:
            raise ModbusRtuError("Truncated read-coils response")

        states: list[bool] = []
        for index in range(count):
            states.append(bool(data[index // 8] & (1 << (index % 8))))
        return states

    async def write_coil(self, address: int, value: bool) -> None:
        """Write a single coil (function code 0x05)."""
        pdu = bytes(
            [
                WRITE_SINGLE_COIL,
                (address >> 8) & 0xFF,
                address & 0xFF,
                0xFF if value else 0x00,
                0x00,
            ]
        )
        payload = await self._transact(_frame(self.slave, pdu))
        if len(payload) < 4 or payload[0] != WRITE_SINGLE_COIL:
            raise ModbusRtuError("Malformed write-coil response")

    async def test_connection(self) -> None:
        """Verify the module answers a read-coils request."""
        await self.read_coils(0, 1)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<ModbusRtuClient {self.host}:{self.port} slave={self.slave}>"

    async def async_diagnostics(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "slave": self.slave,
            "connected": self.connected,
        }
