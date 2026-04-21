"""End-to-end tests for the sync ThingSetTCP client against a
threaded in-process canned-response server. Exercises the transport's
background-receive-thread + queue + try_consume framing path that the
real CLI depends on — the 34 encoder tests don't touch any of this.
"""

import socket
import threading
import time
from contextlib import contextmanager
from typing import Dict

import cbor2

from python_thingset import (
    ThingSetProtocol,
    ThingSetStatus,
    ThingSetTCP,
    WireFormat,
)
from python_thingset.transport.tcp import _TcpLink


_protocol = ThingSetProtocol(WireFormat.BINARY)


def _bin_response(status: int, data=None) -> bytes:
    if data is None:
        return bytes([status, 0xF6])
    return bytes([status, 0xF6]) + cbor2.dumps(data, canonical=True)


class _SyncCannedServer:
    """Blocking-socket canned server run on a background thread."""

    def __init__(
        self,
        responses: Dict[bytes, bytes],
        chunked_response: bool = False,
        concat_responses: bool = False,
    ):
        self._responses = responses
        self._chunked = chunked_response
        self._concat = concat_responses
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(2)
        self._sock.settimeout(0.1)
        self.port = self._sock.getsockname()[1]
        self._running = True
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        while self._running:
            try:
                conn, _ = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            t = threading.Thread(target=self._handle, args=(conn,), daemon=True)
            t.start()

    def _handle(self, conn: socket.socket) -> None:
        conn.settimeout(0.1)
        try:
            while self._running:
                try:
                    data = conn.recv(4096)
                except TimeoutError:
                    continue
                except OSError:
                    return
                if not data:
                    return
                response = self._responses.get(bytes(data))
                if response is None:
                    continue
                if self._chunked and len(response) > 1:
                    mid = len(response) // 2
                    conn.sendall(response[:mid])
                    time.sleep(0.02)
                    conn.sendall(response[mid:])
                elif self._concat and isinstance(response, list):
                    # Send all pieces back-to-back in one TCP write so
                    # the client's buffer holds two responses and
                    # try_consume has to chop them
                    conn.sendall(b"".join(response))
                else:
                    conn.sendall(response)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def close(self) -> None:
        self._running = False
        try:
            self._sock.close()
        except Exception:
            pass
        self._accept_thread.join(timeout=1.0)

    def __enter__(self) -> "_SyncCannedServer":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()


@contextmanager
def _port_override(port: int):
    """Patch _TcpLink.PORT so ThingSetTCP connects to the test server."""
    original = _TcpLink.PORT
    _TcpLink.PORT = port
    try:
        yield
    finally:
        _TcpLink.PORT = original


def test_get_round_trip():
    request = _protocol.encode_get(0xF03)
    response = _bin_response(ThingSetStatus.CONTENT, "native_sim")
    with _SyncCannedServer({request: response}) as server, _port_override(server.port):
        with ThingSetTCP("127.0.0.1") as client:
            r = client.get(0xF03)
    assert r.status_code == ThingSetStatus.CONTENT
    assert r.data == "native_sim"
    assert r.values[0].value == "native_sim"


def test_fetch_multi_ids():
    request = _protocol.encode_fetch(0x00, [0x0E, 0x0F])
    response = _bin_response(ThingSetStatus.CONTENT, ["dsm", "meta"])
    with _SyncCannedServer({request: response}) as server, _port_override(server.port):
        with ThingSetTCP("127.0.0.1") as client:
            r = client.fetch(0x00, [0x0E, 0x0F])
    assert r.status_code == ThingSetStatus.CONTENT
    assert [v.value for v in r.values] == ["dsm", "meta"]


def test_update_and_exec():
    update_req = _protocol.encode_update(0x03, 0x300, 42)
    exec_req = _protocol.encode_exec(0x67, [])
    responses = {
        update_req: _bin_response(ThingSetStatus.CHANGED),
        exec_req: _bin_response(ThingSetStatus.CHANGED),
    }
    with _SyncCannedServer(responses) as server, _port_override(server.port):
        with ThingSetTCP("127.0.0.1") as client:
            u = client.update(0x300, 42, parent_id=0x03)
            e = client.exec(0x67, [])
    assert u.status_code == ThingSetStatus.CHANGED
    assert e.status_code == ThingSetStatus.CHANGED


def test_response_split_across_recvs():
    """Chunked response — the sync transport's receive thread must
    accumulate bytes until try_consume frames one complete message."""
    request = _protocol.encode_fetch(0x19, [0xF03])
    response = _bin_response(
        ThingSetStatus.CONTENT,
        [{26: "rBoard" * 10, 27: "string" * 10, 28: 7}],
    )
    with _SyncCannedServer(
        {request: response}, chunked_response=True
    ) as server, _port_override(server.port):
        with ThingSetTCP("127.0.0.1") as client:
            r = client.fetch(0x19, [0xF03])
    assert r.status_code == ThingSetStatus.CONTENT
    assert r.values[0].value[26] == "rBoard" * 10


def test_timeout_returns_none_status_on_silent_server():
    """Server is up but has no canned reply for this request — caller
    should see None/None after the ~500ms queue timeout rather than
    hanging indefinitely."""
    with _SyncCannedServer({}) as server, _port_override(server.port):
        with ThingSetTCP("127.0.0.1") as client:
            t0 = time.perf_counter()
            r = client.get(0xF03)
            elapsed = time.perf_counter() - t0
    assert r.status_code is None
    assert r.data is None
    # Should have returned promptly (~0.5s), not hung for many seconds
    assert elapsed < 2.0


def test_two_concatenated_responses_in_one_recv():
    """If the server writes two responses back-to-back, the receive
    buffer holds both and try_consume must extract them one at a time."""
    # Prime request A: get(0xF03) -> "native_sim"
    req_a = _protocol.encode_get(0xF03)
    resp_a = _bin_response(ThingSetStatus.CONTENT, "native_sim")
    # The server replies with BOTH responses to the first request, so
    # the second request's response is already waiting in the queue.
    req_b = _protocol.encode_get(0xF02)
    resp_b = _bin_response(ThingSetStatus.CONTENT, "user")
    responses = {req_a: [resp_a, resp_b], req_b: _bin_response(ThingSetStatus.CONTENT)}
    with _SyncCannedServer(
        responses, concat_responses=True
    ) as server, _port_override(server.port):
        with ThingSetTCP("127.0.0.1") as client:
            r1 = client.get(0xF03)
            r2 = client.get(0xF02)
    assert r1.status_code == ThingSetStatus.CONTENT
    assert r1.data == "native_sim"
    assert r2.status_code == ThingSetStatus.CONTENT
    assert r2.data == "user"


def test_context_manager_cleans_up_connection():
    request = _protocol.encode_get(0xF03)
    response = _bin_response(ThingSetStatus.CONTENT, "native_sim")
    with _SyncCannedServer({request: response}) as server, _port_override(server.port):
        with ThingSetTCP("127.0.0.1") as client:
            r = client.get(0xF03)
            assert client.is_connected is True
        # After __exit__ disconnect should have run
        assert client.is_connected is False
    assert r.status_code == ThingSetStatus.CONTENT
