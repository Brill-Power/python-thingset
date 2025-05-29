#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
from typing import Any, List, Union

from .backends import ThingSetBackend, ThingSetCAN, ThingSetSerial, ThingSetSock
from .response import ThingSetResponse


class ThingSet(object):
    def __init__(
        self,
        backend: str = ThingSetBackend.Socket,
        can_bus: str = "vcan0",
        can_addr: int = 0x00,
        init_block: bool = True,
        source_bus: int = 0x00,
        target_bus: int = 0x00,
        port: str = "/dev/ttyACM0",
        baud: int = 115200,
        ip_addr: str = "127.0.0.1",
    ) -> "ThingSet":
        """Constructor for ThingSet object

        Args:
            backend: communications backend to use - one of `'can'` or `'serial'` or `'socket'`
            can_bus: physical (or virtual) CAN device to use if using CAN backend
            can_addr: intended node address of this ThingSet CAN instance if using CAN backend
            init_block: whether to block during instantation whilst backend connects
            source_bus: bus number of source bus if using CAN backend
            target_bus: bus number of target bus if using CAN backend
            port: serial port to connect over if using serial backend
            baud: serial baud rate if using serial backend
            ip_addr: ipv4 address to connect to if using socket backend

        Returns:
            instance of a `ThingSet` object
        """

        self.backend = None

        match backend.lower():
            case ThingSetBackend.CAN:
                self.backend = ThingSetCAN(
                    can_bus, can_addr, source_bus=source_bus, target_bus=target_bus
                )
            case ThingSetBackend.Serial:
                self.backend = ThingSetSerial(port, baud)
            case ThingSetBackend.Socket:
                self.backend = ThingSetSock(ip_addr)
            case _:
                raise ValueError(f"Invalid backend specified ({backend})")

        self._init_block = init_block

        if self._init_block:
            while not self.backend.is_connected:
                pass

    def disconnect(self) -> None:
        """Initiate disconnection from communications backend

        Args:
            None

        Returns:
            None
        """

        if self.backend is not None:
            return self.backend.disconnect()

    def fetch(
        self,
        parent_id: Union[int, str],
        ids: List[Union[int, str]],
        node_id: Union[int, None] = None,
    ) -> ThingSetResponse:
        """Perform a ThingSet fetch request

        Args:
            parent_id: id of (CAN), or path to (serial), parent group
            ids: list of ids (CAN), or paths (serial), of values to retrieve
            node_id: node address of target device (CAN)

        Returns:
            a `ThingSetResponse` object
        """

        if self.backend is not None:
            return self.backend.fetch(parent_id, ids, node_id)

    def get(
        self, value_id: Union[int, str], node_id: Union[int, None] = None
    ) -> ThingSetResponse:
        """Perform a ThingSet get request

        Args:
            value_id: id of (CAN), or path to (serial), value to retrieve
            node_id: node address of target device (CAN)

        Returns:
            a `ThingSetResponse` object
        """

        if self.backend is not None:
            return self.backend.get(value_id, node_id)

    def exec(
        self,
        value_id: Union[int, str],
        args: Union[List[Any], None],
        node_id: Union[int, None] = None,
    ) -> ThingSetResponse:
        """Perform a ThingSet exec request

        Args:
            value_id: id of (CAN), or path to (serial), function to execute
            args: `list` of arguments to function, or `None` if no arguments are required
            node_id: node address of target device (CAN)

        Returns:
            a `ThingSetResponse` object
        """

        if self.backend is not None:
            return self.backend.exec(value_id, args, node_id)

    def update(
        self,
        value_id: Union[int, str],
        value: Any,
        node_id: Union[int, None] = None,
        parent_id: Union[int, None] = None,
    ) -> ThingSetResponse:
        """Perform a ThingSet update request

        Args:
            value_id: id of (CAN), or path to (serial), value to update
            value: value to which to set `value_id`
            node_id: node address of target device (CAN)
            parent_id: id of parent group (CAN)

        Returns:
            a `ThingSetResponse` object
        """

        if self.backend is not None:
            return self.backend.update(value_id, value, node_id, parent_id)

    def __enter__(self) -> "ThingSet":
        if self._init_block:
            """ spin while we wait for backend to connect so that 'with' statements
            always have a valid, usable backend
            """
            while not self.backend.is_connected:
                pass

        return self

    def __exit__(self, type, val, trace):
        self.__del__()

    def __del__(self):
        if self.backend is not None:
            self.disconnect()
