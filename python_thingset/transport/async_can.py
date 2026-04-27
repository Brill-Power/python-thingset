#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
"""Async CAN report receiver for ThingSet publish/subscribe.

ThingSet devices broadcast reports onto the CAN bus in two distinct
shapes (see ``ThingSet.Net/CanID.cs``):

  * **Single-frame report** (``type=0x2``): the 16-bit data ID is
    embedded in the CAN-ID itself; the payload is the bare
    CBOR-encoded value. We synthesise these into a ``ThingSetReport``
    with ``subset_id=None`` and a one-entry ``values`` map so consumers
    can treat all reports uniformly.

  * **Multi-frame report** (``type=0x1``): chunks reassemble per-sender
    using ``msg#`` (2 bits) + ``msgtype`` (2 bits) + ``seq#`` (4 bits)
    in the CAN-ID. The reassembled buffer matches the UDP envelope
    (``[0x1F][cbor subset][cbor map]`` or
    ``[0x1E][cbor eui][cbor subset][cbor map]``) and runs through the
    existing ``ThingSetProtocol.parse_report``.

Public API mirrors :class:`AsyncThingSetUDPReceiver` — async iterator
yielding ``((source_addr, bus_name), ThingSetReport)``.
"""

import asyncio
import logging
from typing import Dict, Tuple, Union

import can

from .._protocol import ThingSetProtocol, WireFormat
from ..report import ThingSetReport


logger = logging.getLogger(__name__)


# ----- CAN-ID bitfield layout (29-bit extended ID) -----

_PRIORITY_POS = 26
_PRIORITY_MASK = 0x7 << _PRIORITY_POS  # not currently used; kept for clarity

_TYPE_POS = 24
_TYPE_MASK = 0x3 << _TYPE_POS

_TYPE_REQ_RESP = 0x0 << _TYPE_POS
_TYPE_MULTI_FRAME_REPORT = 0x1 << _TYPE_POS
_TYPE_SINGLE_FRAME_REPORT = 0x2 << _TYPE_POS
_TYPE_NETWORK = 0x3 << _TYPE_POS

# Source addr is bits 0-7
_SOURCE_MASK = 0xFF

# Single-frame report layout: data ID at bits 8-23
_DATA_ID_POS = 8
_DATA_ID_MASK = 0xFFFF << _DATA_ID_POS

# Multi-frame report layout
_SEQ_POS = 8
_SEQ_MASK = 0xF << _SEQ_POS  # 4 bits

_MULTIFRAME_TYPE_POS = 12
_MULTIFRAME_TYPE_MASK = 0x3 << _MULTIFRAME_TYPE_POS  # 2 bits

_MSG_NUM_POS = 14
_MSG_NUM_MASK = 0x3 << _MSG_NUM_POS  # 2 bits

# MultiFrameMessageType values (already shifted into position)
_MFT_FIRST = 0x0 << _MULTIFRAME_TYPE_POS
_MFT_CONSECUTIVE = 0x1 << _MULTIFRAME_TYPE_POS
_MFT_LAST = 0x2 << _MULTIFRAME_TYPE_POS
_MFT_SINGLE = 0x3 << _MULTIFRAME_TYPE_POS


def _is_first(mft: int) -> bool:
    """A frame that starts a new message buffer."""
    return mft == _MFT_FIRST or mft == _MFT_SINGLE


def _is_last(mft: int) -> bool:
    """A frame that completes a message buffer."""
    return mft == _MFT_LAST or mft == _MFT_SINGLE


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


class AsyncThingSetCANReportReceiver:
    """Listen for ThingSet publish frames on a CAN bus.

    Use as an async context manager. Iterate with
    ``async for ((source_addr, bus_name), report) in receiver``.
    """

    DEFAULT_QUEUE_SIZE = 1024

    def __init__(
        self,
        bus: str = "can0",
        interface: str = "socketcan",
        fd: bool = True,
        queue_size: int = DEFAULT_QUEUE_SIZE,
    ) -> None:
        self._bus_name = bus
        self._interface = interface
        self._fd = fd
        self._queue_size = queue_size
        self._protocol = ThingSetProtocol(WireFormat.BINARY)
        self._queue: "asyncio.Queue[Tuple[Tuple[int, str], ThingSetReport]]" = (
            asyncio.Queue(maxsize=queue_size)
        )
        self._buffers: Dict[int, _ReassemblyBuffer] = {}
        self._can_bus: Union[can.BusABC, None] = None
        self._reader: Union[can.AsyncBufferedReader, None] = None
        self._notifier: Union[can.Notifier, None] = None
        self._task: Union[asyncio.Task, None] = None

    async def start(self) -> None:
        if self._can_bus is not None:
            return
        loop = asyncio.get_running_loop()
        # Hardware-level filter: only receive frames whose type field
        # is single-frame (0x2) or multi-frame (0x1) report. Two
        # filters because the bitmask doesn't allow OR'ing of two
        # disjoint values — but the kernel accepts a list and ORs
        # the matches.
        filters = [
            {
                "can_id": _TYPE_SINGLE_FRAME_REPORT,
                "can_mask": _TYPE_MASK,
                "extended": True,
            },
            {
                "can_id": _TYPE_MULTI_FRAME_REPORT,
                "can_mask": _TYPE_MASK,
                "extended": True,
            },
        ]
        self._can_bus = can.Bus(
            channel=self._bus_name,
            interface=self._interface,
            fd=self._fd,
            can_filters=filters,
        )
        self._reader = can.AsyncBufferedReader()
        self._notifier = can.Notifier(self._can_bus, [self._reader], loop=loop)
        self._task = asyncio.create_task(
            self._consume_frames(),
            name=f"thingset-can-rx-{self._bus_name}",
        )

    async def close(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self._notifier is not None:
            try:
                self._notifier.stop()
            except Exception:
                pass
            self._notifier = None
        if self._can_bus is not None:
            try:
                self._can_bus.shutdown()
            except Exception:
                pass
            self._can_bus = None
        self._reader = None

    async def _consume_frames(self) -> None:
        assert self._reader is not None
        try:
            while True:
                msg = await self._reader.get_message()
                self._handle_message(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("CAN receiver loop terminated unexpectedly")

    def _handle_message(self, msg: can.Message) -> None:
        if not msg.is_extended_id:
            return  # ThingSet uses 29-bit IDs exclusively

        can_id = msg.arbitration_id
        msg_type = can_id & _TYPE_MASK
        source = can_id & _SOURCE_MASK

        if msg_type == _TYPE_SINGLE_FRAME_REPORT:
            data_id = (can_id & _DATA_ID_MASK) >> _DATA_ID_POS
            payload = bytes(msg.data[: msg.dlc])
            report = self._protocol.build_single_frame_report(data_id, payload)
            if report is not None:
                self._enqueue(source, report)
            return

        if msg_type == _TYPE_MULTI_FRAME_REPORT:
            self._handle_multi_frame(source, can_id, bytes(msg.data[: msg.dlc]))
            return

    def _handle_multi_frame(
        self, source: int, can_id: int, data: bytes
    ) -> None:
        mft = can_id & _MULTIFRAME_TYPE_MASK
        seq = (can_id & _SEQ_MASK) >> _SEQ_POS
        msg_num = (can_id & _MSG_NUM_MASK) >> _MSG_NUM_POS

        if logger.isEnabledFor(logging.DEBUG):
            mft_name = {
                _MFT_FIRST: "FIRST",
                _MFT_CONSECUTIVE: "CONSEC",
                _MFT_LAST: "LAST",
                _MFT_SINGLE: "SINGLE",
            }.get(mft, f"?({mft >> _MULTIFRAME_TYPE_POS})")
            logger.debug(
                "rx mf src=0x%02X msg#=%d mft=%s seq=%d len=%d id=0x%08X",
                source, msg_num, mft_name, seq, len(data), can_id,
            )

        buf = self._buffers.setdefault(source, _ReassemblyBuffer())

        if _is_first(mft):
            buf.reset()
            buf.started = True
            buf.message_number = msg_num
        elif not buf.started or buf.message_number != msg_num:
            buf.reset()
            return

        # Sequence mismatch: skip the frame but keep buffer state
        # intact. Two scenarios where this matters:
        #   1. We joined mid-stream — every frame mismatches until the
        #      next FIRST resets us cleanly.
        #   2. The publisher interleaves two concurrent multi-frame
        #      reports onto the wire with a shared msg# (firmware quirk
        #      observed on bpux ACMU). One stream's frames match the
        #      expected sequence; the other's miss. Skipping the misses
        #      without advancing state lets the matching stream
        #      reassemble correctly. This mirrors the C# HMCU's
        #      ReportBuffer, which returns error on mismatch without
        #      touching its sequence counter.
        if seq != (buf.expected_seq & 0xF):
            logger.debug(
                "ThingSet CAN multi-frame seq skip from 0x%02X: "
                "expected %d, got %d (msg#=%d can_id=0x%08X)",
                source,
                buf.expected_seq & 0xF,
                seq,
                msg_num,
                can_id,
            )
            return

        buf.data.extend(data)
        buf.expected_seq += 1

        if _is_last(mft):
            payload = bytes(buf.data)
            buf.reset()
            report = self._protocol.parse_report(payload)
            if report is not None:
                self._enqueue(source, report)

    def _enqueue(self, source: int, report: ThingSetReport) -> None:
        try:
            self._queue.put_nowait(((source, self._bus_name), report))
        except asyncio.QueueFull:
            logger.warning(
                "ThingSet CAN report queue full; dropping report from 0x%02X",
                source,
            )

    def __aiter__(self) -> "AsyncThingSetCANReportReceiver":
        return self

    async def __anext__(self) -> Tuple[Tuple[int, str], ThingSetReport]:
        return await self._queue.get()

    async def __aenter__(self) -> "AsyncThingSetCANReportReceiver":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
