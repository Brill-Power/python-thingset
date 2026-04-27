"""Resilience contract for ThingSetTransport._receive_loop.

A single bad frame from the wire (kernel ISO-TP rejecting a malformed
PDU, isotp.recv raising EILSEQ, a CBOR decode blowup in a handler,
etc.) must not kill the receive thread — the surrounding RPC layer
relies on get_response()'s timeout to surface failures, and a dead
thread leaves the next reconnect racing against a still-running one.
"""

import threading
import time
from typing import Any, List

import pytest

from python_thingset.transport.transport import ThingSetTransport


class _FakeTransport(ThingSetTransport):
    """Transport whose receive() can be programmed to raise then return."""

    def __init__(self, behaviours: List):
        super().__init__()
        self._behaviours = list(behaviours)
        self._handled: List[Any] = []
        self._handle_raises = False

    def receive(self) -> Any:
        if not self._behaviours:
            time.sleep(0.01)
            return None
        item = self._behaviours.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def _handle_message(self, message: Any) -> None:
        if self._handle_raises:
            raise RuntimeError("handler boom")
        self._handled.append(message)

    def connect(self) -> None:  # pragma: no cover - unused
        pass

    def disconnect(self) -> None:  # pragma: no cover - unused
        pass

    def send(self, data: Any) -> None:  # pragma: no cover - unused
        pass


def _wait_until(predicate, timeout: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_receive_exception_does_not_kill_thread():
    """receive() raising must be logged-and-continued, not propagated."""
    t = _FakeTransport([
        OSError(84, "Invalid or incomplete multibyte or wide character"),
        b"after-error",
    ])
    t.start_receiving()
    try:
        assert _wait_until(lambda: b"after-error" in t._handled), (
            "thread died on exception instead of swallowing it"
        )
        assert t._thread is not None and t._thread.is_alive()
    finally:
        t.stop_receiving()


def test_handle_message_exception_does_not_kill_thread():
    """A handler that raises also must not stop the loop."""
    t = _FakeTransport([b"first", b"second"])
    t._handle_raises = True

    seen = threading.Event()
    original_handle = t._handle_message

    call_count = {"n": 0}

    def counting_handle(msg):
        call_count["n"] += 1
        if call_count["n"] == 2:
            seen.set()
        original_handle(msg)

    t._handle_message = counting_handle  # type: ignore[assignment]
    t.start_receiving()
    try:
        assert seen.wait(timeout=1.0), "second message never reached handler"
        assert t._thread is not None and t._thread.is_alive()
    finally:
        t.stop_receiving()


def test_stop_receiving_is_idempotent():
    """stop_receiving() must be safe to call after the thread already
    exited or was never started."""
    t = _FakeTransport([])
    t.stop_receiving()  # never started
    t.start_receiving()
    t.stop_receiving()
    t.stop_receiving()  # already stopped
