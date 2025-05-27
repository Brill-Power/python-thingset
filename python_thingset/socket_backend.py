#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
import queue
import socket
from typing import Any, List, Union

try:
    from .backend import ThingSetBackend
    from .binary_encoder import ThingSetBinaryEncoder
    from .client import ThingSetClient
    from .response import ThingSetResponse, ThingSetStatus, ThingSetValue
except:
    from backend import ThingSetBackend
    from binary_encoder import ThingSetBinaryEncoder
    from client import ThingSetClient
    from response import ThingSetResponse, ThingSetStatus, ThingSetValue


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

    def get_message(self, timeout: float=0.5) -> Union[bytes, None]:
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
    def __init__(self, address: str="192.0.2.1"):
        super().__init__()

        self.backend = ThingSetBackend.Socket

        self.address = address

        self._sock = Sock(address)
        self._sock.connect()
        self.is_connected = True

    def disconnect(self) -> None:
        self._sock.disconnect()
        self.is_connected = False

    def fetch(self, parent_id: Union[int, str], ids: List[Union[int, str]], node_id: Union[int, None]=None, get_paths: bool=True) -> ThingSetResponse:
        self._sock.send(self.encode_fetch(parent_id, ids))
        msg = self._sock.get_message()

        tmp = ThingSetResponse(self.backend, msg)

        values = []

        if tmp.status_code is not None:
            if tmp.status_code <= ThingSetStatus.CONTENT:
                """ create ThingSetValue for parent_id if we're getting its children, otherwise
                create ThingSetValue for each id in ids
                """
                if len(ids) == 0:
                    values.append(self._create_value(parent_id, tmp.data, get_paths))
                else:
                    for idx, id in enumerate(ids):
                        values.append(self._create_value(id, tmp.data[idx], get_paths))

        return ThingSetResponse(self.backend, msg, values)

    def get(self, value_id: Union[int, str], node_id: Union[int, None]=None) -> ThingSetResponse:
        self._sock.send(self.encode_get(value_id))
        msg = self._sock.get_message()

        tmp = ThingSetResponse(self.backend, msg)

        values = []

        if tmp.status_code is not None:
            if tmp.status_code <= ThingSetStatus.CONTENT:
                values.append(ThingSetValue(None, tmp.data, value_id))

        return ThingSetResponse(self.backend, msg, values)

    def exec(self, value_id: Union[int, str], args: Union[Any, None], node_id: Union[int, None]=None) -> ThingSetResponse:
        self._sock.send(self.encode_exec(value_id, args))
        msg = self._sock.get_message()

        return ThingSetResponse(self.backend, msg)

    def update(self, value_id: Union[int, str], value: Any, node_id: Union[int, None]=None, parent_id: Union[int, None]=None) -> ThingSetResponse:
        self._sock.send(self.encode_update(parent_id, value_id, value))
        msg = self._sock.get_message()

        return ThingSetResponse(self.backend, msg)

    def _create_value(self, value_id: int, value: Any, get_paths: bool=True) -> ThingSetValue:
        return ThingSetValue(value_id, value, self._get_path(value_id) if get_paths else None)

    def _get_path(self, value_id: int) -> str:
        if value_id == ThingSetValue.ID_ROOT:
            return "Root"

        self._sock.send(self.encode_get_path(value_id))

        return ThingSetResponse(self.backend, self._sock.get_message()).data[0]

    @property
    def address(self) -> str:
        return self._address
    
    @address.setter
    def address(self, _address) -> None:
        self._address = _address
