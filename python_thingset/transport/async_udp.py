#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
"""Async UDP receiver for ThingSet broadcast reports.

ThingSet devices broadcast publish/subscribe messages to
``255.255.255.255:9002`` on their own schedule — there is no subscribe
handshake. This module binds a UDP socket, reassembles the 2-byte
fragmentation framing used by the IP transport
(``Brill-Power/ThingSet.Net: IpServerTransport.cs``), decodes each
complete payload through :meth:`ThingSetProtocol.parse_report`, and
exposes the stream as an async iterator::

    async with AsyncThingSetUDPReceiver(port=9002) as receiver:
        async for (addr, report) in receiver:
            ...

Reassembly is per-sender: multiple publishers sharing the subnet each
get their own buffer keyed on ``(ip, port)``. A lost middle fragment
silently truncates the buffer on that sender — matching the C#
reference behaviour — but we log a warning so it's at least visible.

Graceful shutdown is via task cancellation (the usual asyncio
pattern); an external ``close()`` call will close the socket but will
not wake up a pending ``__anext__``.
"""

import asyncio
import socket
from typing import Dict, Tuple, Union

from .._protocol import ThingSetProtocol, WireFormat
from ..log import get_logger
from ..report import ThingSetReport


logger = get_logger()


# UDP fragmentation framing (per ThingSet.Net/Protocol.cs)
_MSG_TYPE_FIRST = 0x00
_MSG_TYPE_CONSECUTIVE = 0x10
_MSG_TYPE_LAST = 0x20
_MSG_TYPE_SINGLE = 0x30
_MSG_TYPE_MASK = 0xF0
_SEQ_MASK = 0x0F
_HEADER_SIZE = 2


class _ReassemblyBuffer:
    __slots__ = ("data", "expected_seq", "message_number", "started")

    def __init__(self) -> None:
        self.data = bytearray()
        self.expected_seq = 0
        self.message_number: int = -1
        self.started = False

    def reset(self) -> None:
        self.data.clear()
        self.expected_seq = 0
        self.started = False


class _UdpReceiverProtocol(asyncio.DatagramProtocol):
    def __init__(
        self,
        queue: "asyncio.Queue[Tuple[Tuple[str, int], ThingSetReport]]",
        protocol: ThingSetProtocol,
    ) -> None:
        self._queue = queue
        self._protocol = protocol
        self._buffers: Dict[Tuple[str, int], _ReassemblyBuffer] = {}

    def datagram_received(
        self, data: bytes, addr: Tuple[str, int]
    ) -> None:
        if len(data) < _HEADER_SIZE + 1:
            return

        msg_type = data[0] & _MSG_TYPE_MASK
        seq = data[0] & _SEQ_MASK
        msg_num = data[1]
        fragment = data[_HEADER_SIZE:]

        buf = self._buffers.setdefault(addr, _ReassemblyBuffer())

        if msg_type in (_MSG_TYPE_FIRST, _MSG_TYPE_SINGLE):
            buf.reset()
            buf.started = True
            buf.message_number = msg_num
        elif not buf.started or buf.message_number != msg_num:
            # Middle/last fragment without a matching First: drop.
            buf.reset()
            return

        if seq == (buf.expected_seq & _SEQ_MASK):
            buf.data.extend(fragment)
        else:
            logger.warning(
                "ThingSet UDP fragment sequence mismatch from %s: "
                "expected %d, got %d (report will be truncated)",
                addr,
                buf.expected_seq & _SEQ_MASK,
                seq,
            )
        buf.expected_seq += 1

        if msg_type in (_MSG_TYPE_LAST, _MSG_TYPE_SINGLE):
            payload = bytes(buf.data)
            buf.reset()
            report = self._protocol.parse_report(payload)
            if report is None:
                return
            try:
                self._queue.put_nowait((addr, report))
            except asyncio.QueueFull:
                logger.warning(
                    "ThingSet UDP queue full; dropping report from %s", addr
                )


class AsyncThingSetUDPReceiver:
    """Binds a UDP socket on :attr:`port` and yields parsed reports.

    Use as an async context manager or call :meth:`start` / :meth:`close`
    directly. Iterate with ``async for (addr, report) in receiver`` —
    ``addr`` is the source ``(ip, port)``, ``report`` is a
    :class:`ThingSetReport`.
    """

    DEFAULT_PORT = 9002
    DEFAULT_QUEUE_SIZE = 1024

    def __init__(
        self,
        bind: str = "0.0.0.0",
        port: int = DEFAULT_PORT,
        queue_size: int = DEFAULT_QUEUE_SIZE,
    ) -> None:
        self._bind = bind
        self._port = port
        self._queue_size = queue_size
        self._protocol = ThingSetProtocol(WireFormat.BINARY)
        self._queue: "asyncio.Queue[Tuple[Tuple[str, int], ThingSetReport]]" = (
            asyncio.Queue(maxsize=queue_size)
        )
        self._transport: Union[asyncio.DatagramTransport, None] = None

    async def start(self) -> None:
        if self._transport is not None:
            return
        loop = asyncio.get_running_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        # Allow multiple processes on one host to listen together; not
        # available on every platform, so best-effort.
        reuseport = getattr(socket, "SO_REUSEPORT", None)
        if reuseport is not None:
            try:
                sock.setsockopt(socket.SOL_SOCKET, reuseport, 1)
            except OSError:
                pass
        sock.bind((self._bind, self._port))
        sock.setblocking(False)
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: _UdpReceiverProtocol(self._queue, self._protocol),
            sock=sock,
        )

    async def close(self) -> None:
        if self._transport is None:
            return
        self._transport.close()
        self._transport = None

    def __aiter__(self) -> "AsyncThingSetUDPReceiver":
        return self

    async def __anext__(self) -> Tuple[Tuple[str, int], ThingSetReport]:
        return await self._queue.get()

    async def __aenter__(self) -> "AsyncThingSetUDPReceiver":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
