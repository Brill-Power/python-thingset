#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
import queue
from typing import Any, List, Union

from serial import Serial as PySerial

try:
    from .backend import ThingSetBackend
    from .client import ThingSetClient
    from .log import get_logger
    from .response import ThingSetResponse, ThingSetStatus, ThingSetValue
except ImportError:
    from backend import ThingSetBackend
    from client import ThingSetClient
    from log import get_logger
    from response import ThingSetResponse, ThingSetStatus, ThingSetValue


logger = get_logger()

class Serial(ThingSetBackend):
    def __init__(self, port: str="/dev/pts/5", baud=115200):
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

    def get_message(self, timeout: float) -> Union[str, None]:
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

        """ if you want to print everything that happens on the shell, uncomment below """
        logger.debug(decoded)

        if not decoded.startswith("thingset") and not decoded.startswith("uart") and not decoded.startswith("\x1b"):
            self._queue.put(decoded)

    def connect(self) -> None:
        if not self._serial:
            self._serial = PySerial(self.port, self.baud, timeout=.1)
            self.is_connected = True
            self.start_receiving()

    def disconnect(self) -> None:
        if self._serial:
            self.stop_receiving()
            self._serial.close()
            self.is_connected = False

    def send(self, _data: bytes) -> None:
        self._serial.write(_data)

    def receive(self) -> bytes:
        return self._serial.read_until("\n".encode())


class ThingSetSerial(ThingSetClient):
    def __init__(self, port: str="/dev/pts/5", baud=115200):
        self.port = port
        self.baud = baud

        self._serial = Serial(port, baud)
        self._serial.connect()
        self.is_connected = True

    def disconnect(self) -> None:
        self._serial.disconnect()
        self.is_connected = False

    def fetch(self, parent_id: Union[int, str], ids: List[Union[int, str]], node_id: Union[int, None]=None) -> ThingSetResponse:
        children = "null"

        if len(ids) > 0:
            children = "["

            for i in ids:
                children += f'\\"{i}\\",'

            children += "]"

        message = f"thingset ?{parent_id} {children}\n".encode()

        self._serial.send(message)
        msg = self._serial.get_message(.5)

        tmp = ThingSetResponse(ThingSetBackend.Serial, msg)

        values = []

        if tmp.status_code is not None:
            if tmp.status_code <= ThingSetStatus.CONTENT:

                if len(ids) == 0:
                    values.append(ThingSetValue(None, tmp.data, parent_id))
                else:
                    for idx, i in enumerate(ids):
                        values.append(ThingSetValue(None, tmp.data[idx], i))

        return ThingSetResponse(ThingSetBackend.Serial, msg, values)

    def get(self, value_id: Union[int, str], node_id: Union[int, None]=None) -> ThingSetResponse:
        message = f"thingset ?{value_id}\n".encode()

        self._serial.send(message)
        msg = self._serial.get_message(.5)

        tmp = ThingSetResponse(ThingSetBackend.Serial, msg)

        values = []

        if tmp.status_code is not None:
            if tmp.status_code <= ThingSetStatus.CONTENT:
                values.append(ThingSetValue(None, tmp.data, value_id))

        return ThingSetResponse(ThingSetBackend.Serial, msg, values)

    def update(self, value_id: Union[int, str], value: Any, node_id: Union[int, None]=None, parent_id: Union[int, None]=None) -> ThingSetResponse:
        """ properly format strings for transmission, add args to stringified list """
        value = value[0]

        val = None

        try:
            val = int(value)
        except ValueError:
            pass

        if val is None:
            try:
                val = float(value)
            except ValueError:
                pass

        if val is None:
            val = f'\\"{value}\\"'

        path = " "
        value_name = None

        path_split = value_id.split("/")

        if len(path_split) > 1:
            path = "/".join(path_split[:-1]) + " "
            value_name = path_split[-1]
        else:
            value_name = path_split[0]

        value_path = f'{path}£\\"{value_name}\\":{val}$'
        value_path = value_path.replace("£", "{").replace("$", "}")

        message = f"""thingset ={value_path}\n""".encode()

        self._serial.send(message)
        msg = self._serial.get_message(0.5)

        return ThingSetResponse(ThingSetBackend.Serial, msg)

    def exec(self, value_id: Union[int, str], args: Union[Any, None], node_id: Union[int, None]=None) -> ThingSetResponse:
        """ properly format strings for transmission, add args to stringified list """
        processed_args = "["

        """ leave numeric values as is, surround strings with escape chars """
        for a in args:
            try:
                int(a)
                processed_args += f"{a},"
                continue
            except ValueError:
                pass

            try:
                float(a)
                processed_args += f"{a},"
                continue
            except ValueError:
                pass

            processed_args += f'\\"{a}\\",'

        processed_args += "]"

        message = f"""thingset !{value_id} {processed_args}\n""".encode()

        self._serial.send(message)
        msg = self._serial.get_message(.5)

        return ThingSetResponse(ThingSetBackend.Serial, msg)

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

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @is_connected.setter
    def is_connected(self, _is_connected: bool) -> None:
        self._is_connected = _is_connected
