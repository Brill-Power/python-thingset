"""Async CAN receiver tests via python-can's virtual bus.

Two ``can.Bus`` instances on the same ``virtual`` channel talk to
each other in-process — no hardware needed. The sender constructs
arbitration IDs by hand to mirror the wire format documented in
``ThingSet.Net/CanID.cs``.
"""

import asyncio
from typing import List

import cbor2
import can
import pytest

from python_thingset import AsyncThingSetCANReportReceiver


# --- CAN-ID layout helpers (kept independent of the implementation
#     constants so tests document the wire format).
_PRIORITY_REPORT_LOW = 0x7 << 26
_TYPE_MULTI_FRAME = 0x1 << 24
_TYPE_SINGLE_FRAME = 0x2 << 24

_MFT_FIRST = 0x0 << 12
_MFT_CONSECUTIVE = 0x1 << 12
_MFT_LAST = 0x2 << 12
_MFT_SINGLE = 0x3 << 12


def _single_frame_id(source: int, data_id: int, priority: int = _PRIORITY_REPORT_LOW) -> int:
    return priority | _TYPE_SINGLE_FRAME | (data_id << 8) | source


def _multi_frame_id(source: int, msg_num: int, mft: int, seq: int) -> int:
    return (
        _PRIORITY_REPORT_LOW
        | _TYPE_MULTI_FRAME
        | ((msg_num & 0x3) << 14)
        | mft
        | ((seq & 0xF) << 8)
        | (source & 0xFF)
    )


def _send_can(sender: can.BusABC, can_id: int, data: bytes) -> None:
    sender.send(
        can.Message(
            arbitration_id=can_id,
            is_extended_id=True,
            data=data,
            is_fd=True,
        )
    )


@pytest.fixture
def virtual_channel(request):
    """Per-test virtual channel name so tests don't cross-talk."""
    return f"virt-{request.node.name}"


async def _open_pair(channel: str):
    """Open a receiver bound to the channel and return a sender bus
    on the same channel. Caller closes the sender."""
    receiver = AsyncThingSetCANReportReceiver(
        bus=channel, interface="virtual", fd=True
    )
    await receiver.start()
    sender = can.Bus(channel=channel, interface="virtual", fd=True)
    return receiver, sender


async def _next(receiver, timeout: float = 1.0):
    return await asyncio.wait_for(receiver.__anext__(), timeout=timeout)


async def test_single_frame_int_value(virtual_channel):
    receiver, sender = await _open_pair(virtual_channel)
    try:
        _send_can(
            sender,
            _single_frame_id(source=0x10, data_id=0x602),
            cbor2.dumps(42, canonical=True),
        )
        (src, bus), report = await _next(receiver)
        assert src == 0x10
        assert bus == virtual_channel
        assert report.subset_id is None
        assert report.eui is None
        assert report.values == {0x602: 42}
    finally:
        sender.shutdown()
        await receiver.close()


async def test_single_frame_string_value(virtual_channel):
    receiver, sender = await _open_pair(virtual_channel)
    try:
        _send_can(
            sender,
            _single_frame_id(source=0x10, data_id=0xF03),
            cbor2.dumps("native_sim", canonical=True),
        )
        _, report = await _next(receiver)
        assert report.values == {0xF03: "native_sim"}
    finally:
        sender.shutdown()
        await receiver.close()


async def test_single_frame_high_priority_also_received(virtual_channel):
    """Priority-bits don't matter for filtering — any report-typed
    frame should be received regardless of priority class."""
    receiver, sender = await _open_pair(virtual_channel)
    try:
        # Priority 5 = ReportHigh
        can_id = (0x5 << 26) | _TYPE_SINGLE_FRAME | (0x100 << 8) | 0x21
        _send_can(sender, can_id, cbor2.dumps(7, canonical=True))
        (src, _), report = await _next(receiver)
        assert src == 0x21
        assert report.values == {0x100: 7}
    finally:
        sender.shutdown()
        await receiver.close()


async def test_multi_frame_single_type(virtual_channel):
    """MFT=Single (0x3): a multi-frame-typed report that fits in
    one frame. C# treats this as the same as First+Last."""
    receiver, sender = await _open_pair(virtual_channel)
    try:
        body = (
            bytes([0x1F])
            + cbor2.dumps(0x400, canonical=True)
            + cbor2.dumps({0x6E: 1, 0x6F: 2}, canonical=True)
        )
        _send_can(
            sender,
            _multi_frame_id(source=0x10, msg_num=0, mft=_MFT_SINGLE, seq=0),
            body,
        )
        (src, _), report = await _next(receiver)
        assert src == 0x10
        assert report.subset_id == 0x400
        assert report.values == {0x6E: 1, 0x6F: 2}
    finally:
        sender.shutdown()
        await receiver.close()


async def test_multi_frame_three_chunks_reassemble(virtual_channel):
    receiver, sender = await _open_pair(virtual_channel)
    try:
        # Construct a body too big for one frame — many keys
        values = {k: f"v{k}" * 3 for k in range(20)}
        body = (
            bytes([0x1F])
            + cbor2.dumps(0x400, canonical=True)
            + cbor2.dumps(values, canonical=True)
        )
        chunk = len(body) // 3
        frames = [
            (body[:chunk], _MFT_FIRST, 0),
            (body[chunk : 2 * chunk], _MFT_CONSECUTIVE, 1),
            (body[2 * chunk :], _MFT_LAST, 2),
        ]
        for data, mft, seq in frames:
            _send_can(
                sender,
                _multi_frame_id(source=0x10, msg_num=1, mft=mft, seq=seq),
                data,
            )
        (src, _), report = await _next(receiver)
        assert src == 0x10
        assert report.subset_id == 0x400
        assert report.values == values
    finally:
        sender.shutdown()
        await receiver.close()


async def test_multi_frame_enhanced_with_eui(virtual_channel):
    receiver, sender = await _open_pair(virtual_channel)
    try:
        body = (
            bytes([0x1E])
            + cbor2.dumps(0xBADB1B0000000001, canonical=True)
            + cbor2.dumps(0x400, canonical=True)
            + cbor2.dumps({0x1: 1}, canonical=True)
        )
        _send_can(
            sender,
            _multi_frame_id(source=0x10, msg_num=0, mft=_MFT_SINGLE, seq=0),
            body,
        )
        _, report = await _next(receiver)
        assert report.eui == 0xBADB1B0000000001
        assert report.subset_id == 0x400
        assert report.values == {0x1: 1}
    finally:
        sender.shutdown()
        await receiver.close()


async def test_multi_frame_msg_num_mismatch_drops_buffer(virtual_channel):
    receiver, sender = await _open_pair(virtual_channel)
    try:
        body = bytes([0x1F]) + cbor2.dumps(0x400, canonical=True) + cbor2.dumps({0x1: 1}, canonical=True)
        half = len(body) // 2
        _send_can(
            sender,
            _multi_frame_id(source=0x10, msg_num=1, mft=_MFT_FIRST, seq=0),
            body[:half],
        )
        # Wrong msg_num on the next frame — should drop the buffer
        _send_can(
            sender,
            _multi_frame_id(source=0x10, msg_num=2, mft=_MFT_LAST, seq=1),
            body[half:],
        )
        # Then send a clean Single-type to confirm receiver still works
        clean = (
            bytes([0x1F])
            + cbor2.dumps(0x500, canonical=True)
            + cbor2.dumps({0x99: 99}, canonical=True)
        )
        _send_can(
            sender,
            _multi_frame_id(source=0x10, msg_num=3, mft=_MFT_SINGLE, seq=0),
            clean,
        )
        _, report = await _next(receiver)
        assert report.subset_id == 0x500  # the bad multi-frame was dropped
    finally:
        sender.shutdown()
        await receiver.close()


async def test_multi_frame_two_streams_same_msg_num_interleaved(virtual_channel):
    """Firmware quirk seen in the wild: two concurrent multi-frame
    publishes from the same source share msg#, with frames interleaved
    on the wire. The second FIRST resets state, latching onto the
    second stream; the first stream's leftover frames must be skipped
    without poisoning reassembly."""
    receiver, sender = await _open_pair(virtual_channel)
    try:
        body_a = (
            bytes([0x1F])
            + cbor2.dumps(0xA00, canonical=True)
            + cbor2.dumps({0xA1: "A" * 60}, canonical=True)
        )
        body_b = (
            bytes([0x1F])
            + cbor2.dumps(0xB00, canonical=True)
            + cbor2.dumps({0xB1: "B" * 60}, canonical=True)
        )
        # Split each so we get FIRST + 1 CONSEC + LAST (3 frames each).
        def split3(b: bytes):
            n = len(b) // 3
            return [b[:n], b[n : 2 * n], b[2 * n :]]

        a0, a1, a2 = split3(body_a)
        b0, b1, b2 = split3(body_b)

        # Wire order: A starts → A's CONSEC → B's FIRST (resets state) →
        # A's LAST (mismatch, skipped) → B's CONSEC → B's LAST.
        _send_can(sender, _multi_frame_id(0x10, 0, _MFT_FIRST, 0), a0)
        _send_can(sender, _multi_frame_id(0x10, 0, _MFT_CONSECUTIVE, 1), a1)
        _send_can(sender, _multi_frame_id(0x10, 0, _MFT_FIRST, 0), b0)
        _send_can(sender, _multi_frame_id(0x10, 0, _MFT_LAST, 2), a2)   # mismatch — skip
        _send_can(sender, _multi_frame_id(0x10, 0, _MFT_CONSECUTIVE, 1), b1)
        _send_can(sender, _multi_frame_id(0x10, 0, _MFT_LAST, 2), b2)
        _, report = await _next(receiver, timeout=2.0)
        assert report.subset_id == 0xB00
        assert report.values == {0xB1: "B" * 60}
    finally:
        sender.shutdown()
        await receiver.close()


async def test_multi_frame_consecutive_without_first_dropped(virtual_channel):
    receiver, sender = await _open_pair(virtual_channel)
    try:
        # Send a CONSECUTIVE frame with no preceding FIRST — must be discarded
        _send_can(
            sender,
            _multi_frame_id(source=0x10, msg_num=0, mft=_MFT_CONSECUTIVE, seq=0),
            b"garbage",
        )
        # Then send a clean message
        body = (
            bytes([0x1F])
            + cbor2.dumps(0x400, canonical=True)
            + cbor2.dumps({0x1: 1}, canonical=True)
        )
        _send_can(
            sender,
            _multi_frame_id(source=0x10, msg_num=1, mft=_MFT_SINGLE, seq=0),
            body,
        )
        _, report = await _next(receiver)
        assert report.subset_id == 0x400
    finally:
        sender.shutdown()
        await receiver.close()


async def test_per_sender_buffers_independent(virtual_channel):
    """Two senders interleaving multi-frame reports must not corrupt
    each other's reassembly buffers."""
    receiver, sender = await _open_pair(virtual_channel)
    try:
        body_a = bytes([0x1F]) + cbor2.dumps(0xA, canonical=True) + cbor2.dumps({0x1: "A"}, canonical=True)
        body_b = bytes([0x1F]) + cbor2.dumps(0xB, canonical=True) + cbor2.dumps({0x2: "B"}, canonical=True)
        ha = len(body_a) // 2
        hb = len(body_b) // 2
        _send_can(sender, _multi_frame_id(0xA1, 0, _MFT_FIRST, 0), body_a[:ha])
        _send_can(sender, _multi_frame_id(0xB2, 0, _MFT_FIRST, 0), body_b[:hb])
        _send_can(sender, _multi_frame_id(0xA1, 0, _MFT_LAST, 1), body_a[ha:])
        _send_can(sender, _multi_frame_id(0xB2, 0, _MFT_LAST, 1), body_b[hb:])

        got: List = []
        for _ in range(2):
            got.append(await _next(receiver, timeout=2.0))

        sources = {addr[0] for addr, _ in got}
        subsets = {r.subset_id for _, r in got}
        assert sources == {0xA1, 0xB2}
        assert subsets == {0xA, 0xB}
    finally:
        sender.shutdown()
        await receiver.close()


async def test_async_context_manager_cleans_up(virtual_channel):
    async with AsyncThingSetCANReportReceiver(
        bus=virtual_channel, interface="virtual", fd=True
    ) as receiver:
        sender = can.Bus(channel=virtual_channel, interface="virtual", fd=True)
        try:
            _send_can(
                sender,
                _single_frame_id(source=0x10, data_id=0xF03),
                cbor2.dumps("ok", canonical=True),
            )
            _, report = await _next(receiver)
            assert report.values == {0xF03: "ok"}
        finally:
            sender.shutdown()
    # After exit, internal state cleared
    assert receiver._can_bus is None
    assert receiver._task is None


async def test_close_idempotent(virtual_channel):
    receiver = AsyncThingSetCANReportReceiver(
        bus=virtual_channel, interface="virtual", fd=True
    )
    await receiver.start()
    await receiver.close()
    await receiver.close()  # second close must not raise


async def test_short_payload_single_frame_decodes_zero(virtual_channel):
    """Single-frame with just the int 0 (one CBOR byte 0x00)."""
    receiver, sender = await _open_pair(virtual_channel)
    try:
        _send_can(
            sender,
            _single_frame_id(source=0x10, data_id=0xE05),
            bytes([0x00]),
        )
        _, report = await _next(receiver)
        assert report.values == {0xE05: 0}
    finally:
        sender.shutdown()
        await receiver.close()


async def test_malformed_single_frame_payload_silently_dropped(virtual_channel):
    receiver, sender = await _open_pair(virtual_channel)
    try:
        # 0x1c is a reserved CBOR initial byte — malformed
        _send_can(
            sender,
            _single_frame_id(source=0x10, data_id=0xE05),
            bytes([0x1C, 0x00, 0x00, 0x00]),
        )
        # Then a valid one — receiver should still work
        _send_can(
            sender,
            _single_frame_id(source=0x10, data_id=0xE05),
            cbor2.dumps(7, canonical=True),
        )
        _, report = await _next(receiver, timeout=2.0)
        assert report.values == {0xE05: 7}
    finally:
        sender.shutdown()
        await receiver.close()
