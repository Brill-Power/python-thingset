#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
import queue
from typing import Union

from serial import Serial as PySerial

from .transport import ThingSetTransport
from .._protocol import ParsedResponse, ThingSetProtocol, WireFormat
from ..client import ThingSetClient
from ..log import get_logger


logger = get_logger()


class _SerialLink(ThingSetTransport):
    def __init__(self, port: str, baud: int, protocol: ThingSetProtocol):
        super().__init__()
        self._port = port
        self._baud = baud
        self._protocol = protocol
        self._queue: "queue.Queue[ParsedResponse]" = queue.Queue()
        self._serial = None

    def connect(self) -> None:
        if not self._serial:
            self._serial = PySerial(self._port, self._baud, timeout=0.1)
            self.start_receiving()

    def disconnect(self) -> None:
        if self._serial:
            self.stop_receiving()
            self._serial.close()

    def send(self, data: bytes) -> None:
        self._serial.write(data)

    def receive(self) -> bytes:
        return self._serial.read_until("\n".encode())

    def _handle_message(self, message: bytes) -> None:
        decoded = message.decode()
        logger.debug(decoded)
        # Filter Zephyr shell/log noise that isn't a ThingSet response
        if (
            decoded.startswith("thingset")
            or decoded.startswith("uart")
            or decoded.startswith("\x1b")
        ):
            return
        self._queue.put(self._protocol.parse_response(decoded))

    def get_response(self, timeout: float = 0.5) -> Union[ParsedResponse, None]:
        try:
            msg = self._queue.get(timeout=timeout)
            self._queue.task_done()
            return msg
        except queue.Empty:
            return None


class ThingSetSerial(ThingSetClient):
    def __init__(self, port: str = "/dev/pts/5", baud: int = 115200):
        self._protocol = ThingSetProtocol(WireFormat.TEXT)
        self._link = _SerialLink(port, baud, self._protocol)
        self._link.connect()
        self.is_connected = True

    def disconnect(self) -> None:
        self._link.disconnect()
        self.is_connected = False

    def _send(self, data: bytes, _: Union[int, None]) -> None:
        self._link.send(data)

    def _recv(self) -> Union[ParsedResponse, None]:
        return self._link.get_response()
