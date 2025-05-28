#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
import queue
import socket
from typing import Union

from .backend import ThingSetBackend
from ..client import ThingSetClient
from ..encoders import ThingSetBinaryEncoder


class Sock(ThingSetBackend):
    PORT = 9001

    def __init__(self, address: str):
        super().__init__()

        self.address = address

        self._queue = queue.Queue()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(0.1)

    @property
    def address(self) -> str:
        return self._address

    @address.setter
    def address(self, _address) -> None:
        self._address = _address

    def get_message(self, timeout: float = 0.5) -> Union[bytes, None]:
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
        self._queue.put(message)

    def connect(self) -> None:
        self._sock.connect((self.address, self.PORT))
        self.start_receiving()

    def disconnect(self) -> None:
        self.stop_receiving()
        self._sock.close()

    def send(self, _data: bytes) -> None:
        self._sock.sendall(_data)

    def receive(self) -> bytes:
        try:
            return self._sock.recv(1024)
        except TimeoutError:
            pass


class ThingSetSock(ThingSetClient, ThingSetBinaryEncoder):
    def __init__(self, address: str = "192.0.2.1"):
        super().__init__()

        self.backend = ThingSetBackend.Socket
        self.address = address

        self._sock = Sock(address)
        self._sock.connect()
        self.is_connected = True

    def disconnect(self) -> None:
        self._sock.disconnect()
        self.is_connected = False

    def _send(self, data: bytes, _: Union[int, None]) -> None:
        self._sock.send(data)

    def _recv(self) -> bytes:
        return self._sock.get_message()

    @property
    def address(self) -> str:
        return self._address

    @address.setter
    def address(self, _address) -> None:
        self._address = _address
