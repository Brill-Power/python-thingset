"""Tests for AsyncThingSetUDPReceiver — fragmentation framing,
per-sender reassembly, report type handling.

Receiver binds to 127.0.0.1 on an ephemeral port; canned datagrams
are sent from a plain blocking socket so the framing is entirely
explicit in the test.
"""

import asyncio
import socket
from typing import Tuple

import cbor2

from python_thingset import AsyncThingSetUDPReceiver, ThingSetReport


# Framing constants — duplicated from async_udp.py so that tests document
# the wire format rather than trust the implementation's constants.
_MSG_TYPE_FIRST = 0x00
_MSG_TYPE_CONSECUTIVE = 0x10
_MSG_TYPE_LAST = 0x20
_MSG_TYPE_SINGLE = 0x30

_REPORT_STANDARD = 0x1F
_REPORT_ENHANCED = 0x1E


def _frame(payload: bytes, msg_type: int, seq: int, msg_num: int) -> bytes:
    return bytes([msg_type | (seq & 0x0F), msg_num & 0xFF]) + payload


def _standard_report_body(subset_id: int, values: dict) -> bytes:
    return (
        bytes([_REPORT_STANDARD])
        + cbor2.dumps(subset_id, canonical=True)
        + cbor2.dumps(values, canonical=True)
    )


def _enhanced_report_body(eui: int, subset_id: int, values: dict) -> bytes:
    return (
        bytes([_REPORT_ENHANCED])
        + cbor2.dumps(eui, canonical=True)
        + cbor2.dumps(subset_id, canonical=True)
        + cbor2.dumps(values, canonical=True)
    )


async def _start_receiver() -> Tuple[AsyncThingSetUDPReceiver, int]:
    receiver = AsyncThingSetUDPReceiver(bind="127.0.0.1", port=0)
    await receiver.start()
    sockname = receiver._transport.get_extra_info("sockname")
    return receiver, sockname[1]


def _send(sock: socket.socket, port: int, data: bytes) -> None:
    sock.sendto(data, ("127.0.0.1", port))


async def _next_with_timeout(
    receiver: AsyncThingSetUDPReceiver, timeout: float = 1.0
) -> Tuple[Tuple[str, int], ThingSetReport]:
    return await asyncio.wait_for(receiver.__anext__(), timeout=timeout)


async def test_single_frame_standard_report():
    receiver, port = await _start_receiver()
    try:
        body = _standard_report_body(0x400, {0x1001: 42, 0x1002: "hi"})
        datagram = _frame(body, _MSG_TYPE_SINGLE, 0, 7)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            _send(s, port, datagram)

        addr, report = await _next_with_timeout(receiver)
        assert addr[0] == "127.0.0.1"
        assert report.subset_id == 0x400
        assert report.values == {0x1001: 42, 0x1002: "hi"}
        assert report.eui is None
    finally:
        await receiver.close()


async def test_single_frame_enhanced_report_preserves_eui():
    receiver, port = await _start_receiver()
    try:
        body = _enhanced_report_body(
            eui=0xDEADBEEFC0FFEEEE, subset_id=0x400, values={0x1001: 1.23}
        )
        datagram = _frame(body, _MSG_TYPE_SINGLE, 0, 0)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            _send(s, port, datagram)

        _, report = await _next_with_timeout(receiver)
        assert report.eui == 0xDEADBEEFC0FFEEEE
        assert report.subset_id == 0x400
        assert report.values == {0x1001: 1.23}
    finally:
        await receiver.close()


async def test_multi_frame_reassembly():
    receiver, port = await _start_receiver()
    try:
        # Construct a report body too large for any single frame assumption
        values = {k: f"value_{k}" * 10 for k in range(30)}
        body = _standard_report_body(0x400, values)

        # Split into three chunks
        chunk = len(body) // 3
        frames = [
            _frame(body[:chunk], _MSG_TYPE_FIRST, 0, 42),
            _frame(body[chunk : 2 * chunk], _MSG_TYPE_CONSECUTIVE, 1, 42),
            _frame(body[2 * chunk :], _MSG_TYPE_LAST, 2, 42),
        ]
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            for f in frames:
                _send(s, port, f)

        _, report = await _next_with_timeout(receiver)
        assert report.subset_id == 0x400
        assert report.values == values
    finally:
        await receiver.close()


async def test_middle_fragment_wrong_msg_num_drops_report():
    receiver, port = await _start_receiver()
    try:
        body = _standard_report_body(0x400, {0x01: 1, 0x02: 2, 0x03: 3})
        half = len(body) // 2
        frames = [
            _frame(body[:half], _MSG_TYPE_FIRST, 0, 5),
            _frame(body[half:], _MSG_TYPE_LAST, 1, 99),  # wrong msg_num
        ]
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            for f in frames:
                _send(s, port, f)
            # Follow with a good single-frame report; it should come through
            good = _frame(
                _standard_report_body(0x401, {0xFF: 42}), _MSG_TYPE_SINGLE, 0, 6
            )
            _send(s, port, good)

        _, report = await _next_with_timeout(receiver)
        # The bad multi-frame report was dropped; we see the good single
        assert report.subset_id == 0x401
        assert report.values == {0xFF: 42}
    finally:
        await receiver.close()


async def test_middle_without_first_is_ignored():
    receiver, port = await _start_receiver()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Sequence starts with CONSECUTIVE — no First — must be dropped
            _send(s, port, _frame(b"garbage", _MSG_TYPE_CONSECUTIVE, 0, 1))
            _send(s, port, _frame(b"more garbage", _MSG_TYPE_LAST, 1, 1))
            # Then a valid single-frame
            good = _frame(
                _standard_report_body(0x400, {0x01: 1}), _MSG_TYPE_SINGLE, 0, 2
            )
            _send(s, port, good)

        _, report = await _next_with_timeout(receiver)
        assert report.subset_id == 0x400
    finally:
        await receiver.close()


async def test_two_concurrent_senders_have_separate_buffers():
    """Two senders interleaving multi-frame reports must not corrupt
    each other's reassembly buffers."""
    receiver, port = await _start_receiver()
    try:
        body_a = _standard_report_body(0xA, {0x01: "A"})
        body_b = _standard_report_body(0xB, {0x02: "B"})
        half_a = len(body_a) // 2
        half_b = len(body_b) // 2

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sa, \
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sb:
            sa.bind(("127.0.0.1", 0))
            sb.bind(("127.0.0.1", 0))
            # Interleaved: A-first, B-first, A-last, B-last
            _send(sa, port, _frame(body_a[:half_a], _MSG_TYPE_FIRST, 0, 1))
            _send(sb, port, _frame(body_b[:half_b], _MSG_TYPE_FIRST, 0, 1))
            _send(sa, port, _frame(body_a[half_a:], _MSG_TYPE_LAST, 1, 1))
            _send(sb, port, _frame(body_b[half_b:], _MSG_TYPE_LAST, 1, 1))

        got = []
        for _ in range(2):
            addr, report = await _next_with_timeout(receiver)
            got.append((addr, report))

        subsets = {r.subset_id for _, r in got}
        assert subsets == {0xA, 0xB}
    finally:
        await receiver.close()


async def test_unknown_type_byte_is_ignored():
    receiver, port = await _start_receiver()
    try:
        # Type byte 0x42 is not 0x1F or 0x1E
        datagram = _frame(
            bytes([0x42]) + cbor2.dumps({0x01: 1}, canonical=True),
            _MSG_TYPE_SINGLE,
            0,
            0,
        )
        good = _frame(
            _standard_report_body(0x400, {0x01: 1}), _MSG_TYPE_SINGLE, 0, 1
        )
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            _send(s, port, datagram)
            _send(s, port, good)

        _, report = await _next_with_timeout(receiver)
        assert report.subset_id == 0x400
    finally:
        await receiver.close()


async def test_async_context_manager():
    async with AsyncThingSetUDPReceiver(bind="127.0.0.1", port=0) as receiver:
        port = receiver._transport.get_extra_info("sockname")[1]
        datagram = _frame(
            _standard_report_body(0x400, {0x01: 1}), _MSG_TYPE_SINGLE, 0, 0
        )
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            _send(s, port, datagram)
        _, report = await _next_with_timeout(receiver)
        assert report.subset_id == 0x400
    # After exit, transport is gone
    assert receiver._transport is None


async def test_short_datagram_ignored():
    receiver, port = await _start_receiver()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            _send(s, port, b"\x30")  # only 1 byte — below header size
            _send(s, port, b"\x30\x00")  # 2 bytes — header only, no payload
            good = _frame(
                _standard_report_body(0x400, {0x01: 1}), _MSG_TYPE_SINGLE, 0, 0
            )
            _send(s, port, good)

        _, report = await _next_with_timeout(receiver)
        assert report.subset_id == 0x400
    finally:
        await receiver.close()


async def test_queue_full_drops_overflow():
    """Bounded queue: once full, further reports are dropped rather
    than backpressuring the datagram protocol."""
    receiver = AsyncThingSetUDPReceiver(bind="127.0.0.1", port=0, queue_size=2)
    await receiver.start()
    try:
        port = receiver._transport.get_extra_info("sockname")[1]
        # Send more than the queue can hold
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            for i in range(5):
                datagram = _frame(
                    _standard_report_body(i, {}), _MSG_TYPE_SINGLE, 0, i
                )
                _send(s, port, datagram)

        # Let datagrams settle
        await asyncio.sleep(0.05)
        # Exactly queue_size should be readable without a fresh send
        got = []
        for _ in range(2):
            got.append(await _next_with_timeout(receiver, 0.5))
        # No third one should arrive
        try:
            await _next_with_timeout(receiver, 0.1)
            raise AssertionError("expected no more reports after queue fill")
        except asyncio.TimeoutError:
            pass
        assert {r.subset_id for _, r in got} <= {0, 1, 2, 3, 4}
    finally:
        await receiver.close()


async def test_receiver_enlarges_rcvbuf():
    """The receiver requests a large SO_RCVBUF so bursts of big reports from a
    fleet of gateways aren't dropped before they're drained. We can't guarantee
    the full request (the kernel caps at net.core.rmem_max without CAP_NET_ADMIN),
    but it must be at least as large as an untuned socket's default."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as baseline:
        default_rcvbuf = baseline.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)

    receiver = AsyncThingSetUDPReceiver(bind="127.0.0.1", port=0)
    await receiver.start()
    try:
        sock = receiver._transport.get_extra_info("socket")
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF) >= default_rcvbuf
    finally:
        await receiver.close()


async def test_rcvbuf_zero_leaves_default():
    """rcvbuf_bytes=0 opts out of the resize (keeps the system default)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as baseline:
        default_rcvbuf = baseline.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)

    receiver = AsyncThingSetUDPReceiver(bind="127.0.0.1", port=0, rcvbuf_bytes=0)
    await receiver.start()
    try:
        sock = receiver._transport.get_extra_info("socket")
        assert sock.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF) == default_rcvbuf
    finally:
        await receiver.close()
