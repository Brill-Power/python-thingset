#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
import queue
import socket
from typing import Union

from .transport import ThingSetTransport
from .._protocol import ParsedResponse, ThingSetProtocol, WireFormat
from ..client import ThingSetClient


class _TcpLink(ThingSetTransport):
    """TCP transport driver. Accumulates received bytes into a buffer
    and uses the protocol's streaming framer (try_consume) to split the
    stream into complete responses. Replaces the earlier one-response-
    per-recv assumption that failed on segment boundaries.
    """

    PORT = 9001
    RECV_BUFSIZE = 4096
    RECV_TIMEOUT_S = 1.0

    def __init__(self, address: str, protocol: ThingSetProtocol):
        super().__init__()
        self._address = address
        self._protocol = protocol
        self._queue: "queue.Queue[ParsedResponse]" = queue.Queue()
        self._rx_buffer = bytearray()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.RECV_TIMEOUT_S)

    def connect(self) -> None:
        self._sock.connect((self._address, self.PORT))
        self.start_receiving()

    def disconnect(self) -> None:
        self.stop_receiving()
        self._sock.close()

    def send(self, data: bytes) -> None:
        self._sock.sendall(data)

    def receive(self) -> Union[bytes, None]:
        try:
            return self._sock.recv(self.RECV_BUFSIZE)
        except TimeoutError:
            return None

    def _handle_message(self, data: bytes) -> None:
        self._rx_buffer.extend(data)
        while True:
            response, consumed = self._protocol.try_consume(bytes(self._rx_buffer))
            if response is None:
                break
            del self._rx_buffer[:consumed]
            self._queue.put(response)

    def get_response(self, timeout: float = 0.5) -> Union[ParsedResponse, None]:
        try:
            msg = self._queue.get(timeout=timeout)
            self._queue.task_done()
            return msg
        except queue.Empty:
            return None


class ThingSetTCP(ThingSetClient):
    def __init__(self, address: str = "192.0.2.1"):
        self._protocol = ThingSetProtocol(WireFormat.BINARY)
        self._link = _TcpLink(address, self._protocol)
        self._link.connect()
        self.is_connected = True

    def disconnect(self) -> None:
        self._link.disconnect()
        self.is_connected = False

    def _send(self, data: bytes, _: Union[int, None]) -> None:
        self._link.send(data)

    def _recv(self) -> Union[ParsedResponse, None]:
        return self._link.get_response()
