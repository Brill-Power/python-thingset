#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
import queue
from typing import Union

from serial import Serial as PySerial

from .backend import ThingSetBackend
from ..client import ThingSetClient
from ..encoders import ThingSetTextEncoder
from ..log import get_logger


logger = get_logger()


class Serial(ThingSetBackend):
    def __init__(self, port: str = "/dev/pts/5", baud=115200):
        super().__init__()

        self.port = port
        self.baud = baud

        self._serial = None
        self._queue = queue.Queue()

    @property
    def port(self) -> str:
        return self._port

    @port.setter
    def port(self, _port) -> None:
        self._port = _port

    @property
    def baud(self) -> int:
        return self._baud

    @baud.setter
    def baud(self, _baud) -> None:
        self._baud = _baud

    def get_message(self, timeout: float = 0.5) -> Union[str, None]:
        message = None

        try:
            message = self._queue.get(timeout=timeout)
        except queue.Empty:
            pass
        finally:
            if message is not None:
                self._queue.task_done()

            return message

    def _handle_message(self, message: bytes) -> None:
        decoded = message.decode()

        logger.debug(decoded)

        if (
            not decoded.startswith("thingset")
            and not decoded.startswith("uart")
            and not decoded.startswith("\x1b")
        ):
            self._queue.put(decoded)

    def connect(self) -> None:
        if not self._serial:
            self._serial = PySerial(self.port, self.baud, timeout=0.1)
            self.start_receiving()

    def disconnect(self) -> None:
        if self._serial:
            self.stop_receiving()
            self._serial.close()

    def send(self, _data: bytes) -> None:
        self._serial.write(_data)

    def receive(self) -> bytes:
        return self._serial.read_until("\n".encode())


class ThingSetSerial(ThingSetClient, ThingSetTextEncoder):
    def __init__(self, port: str = "/dev/pts/5", baud=115200):
        super().__init__()

        self.backend = ThingSetBackend.Serial
        self.port = port
        self.baud = baud

        self._serial = Serial(port, baud)
        self._serial.connect()
        self.is_connected = True

    def disconnect(self) -> None:
        self._serial.disconnect()
        self.is_connected = False

    def _send(self, data: bytes, _: Union[int, None]) -> None:
        self._serial.send(data)

    def _recv(self) -> bytes:
        return self._serial.get_message()

    @property
    def port(self) -> str:
        return self._port

    @port.setter
    def port(self, _port) -> None:
        self._port = _port

    @property
    def baud(self) -> int:
        return self._baud

    @baud.setter
    def baud(self, _baud) -> None:
        self._baud = _baud
