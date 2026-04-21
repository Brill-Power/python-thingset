"""Async TCP tests via an in-process asyncio canned-response server.

No hardware needed — each test spins up ``asyncio.start_server`` on an
ephemeral port, binds a lookup table of request→response bytes, and
drives AsyncThingSetTCP against it.
"""

import asyncio
from typing import Dict, Optional

import cbor2
import pytest

from python_thingset import (
    AsyncThingSetTCP,
    ThingSetProtocol,
    ThingSetStatus,
    WireFormat,
)


_protocol = ThingSetProtocol(WireFormat.BINARY)


def _bin_response(status: int, data=None) -> bytes:
    """Build a binary ThingSet response frame: status byte, 0xf6, CBOR payload."""
    if data is None:
        return bytes([status, 0xF6])
    return bytes([status, 0xF6]) + cbor2.dumps(data, canonical=True)


class _CannedServer:
    """Asyncio server that maps known request bytes to canned responses.

    Assumes one client write = one read, which holds on loopback for
    the small frames ThingSet uses. Unknown requests get no reply (the
    client will time out, which is the intended behaviour in those
    tests).
    """

    def __init__(
        self,
        responses: Dict[bytes, bytes],
        response_delay: float = 0.0,
        chunked_response: bool = False,
    ):
        self._responses = responses
        self._response_delay = response_delay
        self._chunked = chunked_response
        self._server: Optional[asyncio.Server] = None
        self.port = 0

    async def __aenter__(self) -> "_CannedServer":
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        assert self._server.sockets is not None
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, exc_type, exc, tb):
        assert self._server is not None
        self._server.close()
        await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    return
                response = self._responses.get(bytes(data))
                if response is None:
                    continue
                if self._response_delay:
                    await asyncio.sleep(self._response_delay)
                if self._chunked and len(response) > 1:
                    # Split across two writes with a tiny gap to exercise
                    # the streaming framer (try_consume) on the client side.
                    mid = len(response) // 2
                    writer.write(response[:mid])
                    await writer.drain()
                    await asyncio.sleep(0.01)
                    writer.write(response[mid:])
                else:
                    writer.write(response)
                await writer.drain()
        except (asyncio.CancelledError, ConnectionError):
            pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


async def test_get_round_trip():
    request = _protocol.encode_get(0xF03)
    response = _bin_response(ThingSetStatus.CONTENT, "native_sim")
    async with _CannedServer({request: response}) as server:
        async with AsyncThingSetTCP("127.0.0.1", port=server.port) as client:
            r = await client.get(0xF03)
    assert r.status_code == ThingSetStatus.CONTENT
    assert r.data == "native_sim"
    assert r.values[0].value == "native_sim"


async def test_fetch_multi_ids():
    request = _protocol.encode_fetch(0x00, [0x0E, 0x0F])
    response = _bin_response(ThingSetStatus.CONTENT, ["dsm_value", "meta_value"])
    async with _CannedServer({request: response}) as server:
        async with AsyncThingSetTCP("127.0.0.1", port=server.port) as client:
            r = await client.fetch(0x00, [0x0E, 0x0F])
    assert r.status_code == ThingSetStatus.CONTENT
    assert [v.value for v in r.values] == ["dsm_value", "meta_value"]


async def test_update_and_exec():
    update_req = _protocol.encode_update(0x03, 0x300, 42)
    exec_req = _protocol.encode_exec(0x67, [])
    async with _CannedServer({
        update_req: _bin_response(ThingSetStatus.CHANGED),
        exec_req: _bin_response(ThingSetStatus.CHANGED),
    }) as server:
        async with AsyncThingSetTCP("127.0.0.1", port=server.port) as client:
            u = await client.update(0x300, 42, parent_id=0x03)
            e = await client.exec(0x67, [])
    assert u.status_code == ThingSetStatus.CHANGED
    assert e.status_code == ThingSetStatus.CHANGED


async def test_context_manager_cleans_up():
    async with _CannedServer({}) as server:
        client = AsyncThingSetTCP("127.0.0.1", port=server.port)
        async with client:
            assert not client._closed
            assert client._writer is not None
        assert client._closed
        assert client._writer is None


async def test_timeout_returns_none_status():
    # Server is running but has no canned reply for this request
    async with _CannedServer({}) as server:
        async with AsyncThingSetTCP(
            "127.0.0.1", port=server.port, timeout=0.1
        ) as client:
            r = await client.get(0xF03)
    assert r.status_code is None
    assert r.data is None


async def test_concurrent_callers_serialize():
    """Two asyncio.gather'd calls should both resolve — the internal
    lock serializes them end-to-end."""
    request = _protocol.encode_get(0xF03)
    response = _bin_response(ThingSetStatus.CONTENT, "native_sim")
    async with _CannedServer({request: response}, response_delay=0.02) as server:
        async with AsyncThingSetTCP("127.0.0.1", port=server.port) as client:
            r1, r2, r3 = await asyncio.gather(
                client.get(0xF03), client.get(0xF03), client.get(0xF03)
            )
    for r in (r1, r2, r3):
        assert r.status_code == ThingSetStatus.CONTENT
        assert r.data == "native_sim"


async def test_response_split_across_chunks():
    """Client's streaming framer must reassemble a response that
    arrives in multiple TCP segments."""
    request = _protocol.encode_fetch(0x19, [0xF03])
    # Bigger response so the mid-split cuts through the CBOR body
    response = _bin_response(
        ThingSetStatus.CONTENT,
        [{26: "rBoard" * 10, 27: "string" * 10, 28: 7}],
    )
    async with _CannedServer({request: response}, chunked_response=True) as server:
        async with AsyncThingSetTCP("127.0.0.1", port=server.port) as client:
            r = await client.fetch(0x19, [0xF03])
    assert r.status_code == ThingSetStatus.CONTENT
    assert r.values[0].value[26] == "rBoard" * 10


async def test_discover_schema_end_to_end():
    responses = {
        _protocol.encode_fetch(0x00, []):
            _bin_response(ThingSetStatus.CONTENT, [0x0E, 0x0F]),
        _protocol.encode_fetch(0x19, [0x0E, 0x0F]):
            _bin_response(ThingSetStatus.CONTENT, [
                {26: "DSM", 27: "group", 28: 7},
                {26: "Metadata", 27: "group", 28: 7},
            ]),
        _protocol.encode_fetch(0x0E, []):
            _bin_response(ThingSetStatus.CONTENT, [0xE04]),
        _protocol.encode_fetch(0x19, [0xE04]):
            _bin_response(ThingSetStatus.CONTENT, [
                {26: "rDFUState", 27: "u8", 28: 7},
            ]),
        _protocol.encode_fetch(0x0F, []):
            _bin_response(ThingSetStatus.CONTENT, [0xF03]),
        _protocol.encode_fetch(0x19, [0xF03]):
            _bin_response(ThingSetStatus.CONTENT, [
                {26: "rBoard", 27: "string", 28: 7},
            ]),
    }
    async with _CannedServer(responses) as server:
        async with AsyncThingSetTCP("127.0.0.1", port=server.port) as client:
            tree = await client.discover_schema()

    assert set(tree.by_id.keys()) == {0x0E, 0xE04, 0x0F, 0xF03}
    assert tree.by_path["DSM/rDFUState"].id == 0xE04
    assert tree.by_path["Metadata/rBoard"].id == 0xF03
    assert tree.by_path["Metadata/rBoard"].type == "string"


async def test_rpc_before_connect_raises():
    client = AsyncThingSetTCP("127.0.0.1", port=1)
    with pytest.raises(RuntimeError, match="not connected"):
        await client.get(0xF03)


async def test_close_idempotent():
    async with _CannedServer({}) as server:
        client = AsyncThingSetTCP("127.0.0.1", port=server.port)
        await client.connect()
        await client.close()
        await client.close()  # second close must not raise


async def test_async_with_discover_schema_loop_friendly():
    """Regression guard: other coroutines must keep running while an
    RPC is in flight — proves we're not blocking the event loop."""
    request = _protocol.encode_get(0xF03)
    response = _bin_response(ThingSetStatus.CONTENT, "native_sim")
    other_task_ran = False

    async def parallel_worker():
        nonlocal other_task_ran
        await asyncio.sleep(0.01)
        other_task_ran = True

    async with _CannedServer({request: response}, response_delay=0.05) as server:
        async with AsyncThingSetTCP("127.0.0.1", port=server.port) as client:
            r, _ = await asyncio.gather(client.get(0xF03), parallel_worker())

    assert r.status_code == ThingSetStatus.CONTENT
    assert other_task_ran
