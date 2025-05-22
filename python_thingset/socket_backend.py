#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
import json
import queue
import socket
import struct
from typing import Any, List, Union

import cbor2

try:
    from .backend import ThingSetBackend
    from .client import ThingSetClient
    from .log import get_logger
    from .response import ThingSetResponse, ThingSetRequest, ThingSetStatus, ThingSetValue
except:
    from backend import ThingSetBackend
    from client import ThingSetClient
    from log import get_logger
    from response import ThingSetResponse, ThingSetRequest, ThingSetStatus, ThingSetValue

logger = get_logger()

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
            # self.disconnect()
            return message

    def _handle_message(self, message: bytes) -> None:
        self._queue.put(message)

    def connect(self) -> None:
        self._sock.connect((self.address, self.PORT))
        self.is_connected = True
        self.start_receiving()

    def disconnect(self) -> None:
        self.stop_receiving()
        self._sock.close()
        self.is_connected = False

    def send(self, _data: bytes) -> None:
        self._sock.sendall(_data)

    def receive(self) -> bytes:
        try:
            return self._sock.recv(1024)
        except TimeoutError:
            pass


class ThingSetSock(ThingSetClient):
    def __init__(self, address: str="192.0.2.1"):
        self.address = address

        self._sock = Sock(address)
        self._sock.connect()
        self.is_connected = True

    def disconnect(self) -> None:
        self._sock.disconnect()
        self.is_connected = False

    def fetch(self, parent_id: Union[int, str], ids: List[Union[int, str]], node_id: Union[int, None]=None, get_paths: bool=True) -> ThingSetResponse:
        req = bytearray()
        req.append(ThingSetRequest.FETCH)
        req += cbor2.dumps(parent_id, canonical=True)

        if (len(ids) == 0):
            req.append(0xF6) # null
        else:
            req += cbor2.dumps(ids, canonical=True)

        self._sock.send(req)
        msg = self._sock.get_message()

        tmp = ThingSetResponse(ThingSetBackend.Socket, msg)

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

        return ThingSetResponse(ThingSetBackend.Socket, msg, values)

    def get(self, value_id: Union[int, str], node_id: Union[int, None]=None) -> ThingSetResponse:
        payload = bytes([ThingSetRequest.GET] + list(cbor2.dumps(value_id)))

        self._sock.send(payload)
        msg = self._sock.get_message()

        tmp = ThingSetResponse(ThingSetBackend.Socket, msg)

        values = []

        if tmp.status_code is not None:
            if tmp.status_code <= ThingSetStatus.CONTENT:
                values.append(ThingSetValue(None, tmp.data, value_id))

        return ThingSetResponse(ThingSetBackend.Socket, msg, values)

    def exec(self, value_id: Union[int, str], args: Union[Any, None], node_id: Union[int, None]=None) -> ThingSetResponse:
        p_args = list()

        for a in args:
            if isinstance(a, float):
                p_args.append(self._to_f32(a))
            elif isinstance(a, str):
                if "true" == a.lower() or "false" == a.lower():
                    p_args.append(json.loads(a.lower()))
                else:
                    p_args.append(a)
            else:
                p_args.append(a)

        payload = bytes([ThingSetRequest.EXEC] + list(cbor2.dumps(value_id)) + list(cbor2.dumps(p_args, canonical=True)))

        self._sock.send(payload)
        msg = self._sock.get_message()

        return ThingSetResponse(ThingSetBackend.Socket, msg)

    def update(self, value_id: Union[int, str], value: Any, node_id: Union[int, None]=None, parent_id: Union[int, None]=None) -> ThingSetResponse:
        if isinstance(value, float):
            value = self._to_f32(value)
        if isinstance(value, str):
            if "true" == value.lower() or "false" == value.lower():
                value = json.loads(value.lower())

        payload = bytes([ThingSetRequest.UPDATE] + list(cbor2.dumps(parent_id)) + list(cbor2.dumps({value_id:value}, canonical=True)))

        self._sock.send(payload)
        msg = self._sock.get_message()

        return ThingSetResponse(ThingSetBackend.Socket, msg)

    def _to_f32(self, value: float) -> float:
        """ In Python, all floats are actually doubles. This does not map well to embedded targets where
        there is a clear distinction between the two.

        This function forces the provided floating point argument, value, to its closest 32-bit
        representation so that the resultant encoded (CBOR) value is actually a float (not a double)
        and can be properly parsed by ThingSet running on an embedded target when expecting a float
        """
        return struct.unpack('f', struct.pack('f', value))[0]

    def _create_value(self, value_id: int, value: Any, get_paths: bool=True) -> ThingSetValue:
        path = None

        if get_paths:
            path = self._get_path(value_id)

        return ThingSetValue(value_id, value, path)

    def _get_path(self, value_id: int) -> str:
        if value_id == ThingSetValue.ID_ROOT:
            return "Root"

        payload = bytearray([ThingSetRequest.FETCH, 0x17])
        payload.extend(cbor2.dumps([value_id]))

        self._sock.send(payload)

        return ThingSetResponse(ThingSetBackend.Socket, self._sock.get_message).data[0]

    @property
    def address(self) -> str:
        return self._address
    
    @address.setter
    def address(self, _address) -> None:
        self._address = _address

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @is_connected.setter
    def is_connected(self, _is_connected: bool) -> None:
        self._is_connected = _is_connected


if __name__ == "__main__":
    s = ThingSetSock("192.0.2.1")

    print(s.get(0x300))
    print(s.update(0x300, [77.8], parent_id=0x0))
    print(s.get(0x300))
    print(s.fetch(0, []))
    print(s.exec(0x1000, [4, 5]))

    s.disconnect()
