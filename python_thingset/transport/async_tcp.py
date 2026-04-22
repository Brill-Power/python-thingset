#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
"""Async TCP transport — asyncio-native ThingSet client for the Device
Bridge and other async consumers.

A single background reader task pulls bytes off the stream and runs
them through :meth:`ThingSetProtocol.try_consume`, pushing each
complete :class:`ParsedResponse` onto an :class:`asyncio.Queue`. Each
RPC acquires a per-client :class:`asyncio.Lock`, drains any stale
queued responses, sends the request, and awaits the next queued
response with :func:`asyncio.wait_for`.

ThingSet has no wire-level correlation ID, so the lock keeps one
request in flight at a time. That still releases the event loop
during I/O — the whole point of running async.
"""

import asyncio
from typing import Union

from .._protocol import ParsedResponse, ThingSetProtocol, WireFormat
from ..async_client import AsyncThingSetClient


class AsyncThingSetTCP(AsyncThingSetClient):
    DEFAULT_PORT = 9001
    RECV_BUFSIZE = 4096
    DEFAULT_TIMEOUT_S = 0.5

    def __init__(
        self,
        address: str,
        port: int = DEFAULT_PORT,
        timeout: float = DEFAULT_TIMEOUT_S,
        *,
        target_eui: Union[int, None] = None,
    ):
        """Connect to a ThingSet device over TCP with asyncio.

        When ``target_eui`` is given, every outgoing request is wrapped
        in a gateway-forward envelope so the peer (expected to be an
        IP↔CAN gateway such as an HMCU) routes it to the CAN-side
        module with that EUI-64. Responses come back unwrapped; the
        caller API is unchanged.
        """
        self._protocol = ThingSetProtocol(WireFormat.BINARY)
        self._address = address
        self._port = port
        self._timeout = timeout
        self._target_eui = target_eui
        self._reader: Union[asyncio.StreamReader, None] = None
        self._writer: Union[asyncio.StreamWriter, None] = None
        self._rx_queue: "asyncio.Queue[ParsedResponse]" = asyncio.Queue()
        self._reader_task: Union[asyncio.Task, None] = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def connect(self) -> None:
        if self._writer is not None:
            return
        self._reader, self._writer = await asyncio.open_connection(
            self._address, self._port
        )
        self._reader_task = asyncio.create_task(
            self._reader_loop(), name=f"thingset-rx-{self._address}"
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        task, self._reader_task = self._reader_task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        writer, self._writer = self._writer, None
        if writer is not None:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _reader_loop(self) -> None:
        buffer = bytearray()
        assert self._reader is not None
        try:
            while True:
                chunk = await self._reader.read(self.RECV_BUFSIZE)
                if not chunk:
                    return  # peer closed the connection
                buffer.extend(chunk)
                while True:
                    resp, consumed = self._protocol.try_consume(bytes(buffer))
                    if resp is None:
                        break
                    del buffer[:consumed]
                    await self._rx_queue.put(resp)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Connection broken; subsequent _rpc calls will time out.
            return

    async def _rpc(
        self, request: bytes, node_id: Union[int, None]
    ) -> Union[ParsedResponse, None]:
        if self._closed or self._writer is None:
            raise RuntimeError(
                "AsyncThingSetTCP is not connected; use `async with` "
                "or call connect() first"
            )
        if self._target_eui is not None:
            request = self._protocol.wrap_forward(request, self._target_eui)
        async with self._lock:
            # Drain responses left over from a prior call that timed
            # out and whose reply arrived late — without correlation
            # IDs we can't tell them from fresh ones.
            while not self._rx_queue.empty():
                try:
                    self._rx_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

            self._writer.write(request)
            await self._writer.drain()

            try:
                return await asyncio.wait_for(
                    self._rx_queue.get(), timeout=self._timeout
                )
            except asyncio.TimeoutError:
                return None

    async def __aenter__(self) -> "AsyncThingSetTCP":
        await self.connect()
        return self
