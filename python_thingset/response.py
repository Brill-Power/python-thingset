#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
import json
from dataclasses import dataclass, fields
from typing import Any, List, Union

import cbor2

from .backends import ThingSetBackend


@dataclass
class ThingSetStatus(object):
    """Dataclass to contain ThingSet status codes
    and their names plus utility functions
    """

    CREATED: int = 0x81
    DELETED: int = 0x82
    CHANGED: int = 0x84
    CONTENT: int = 0x85
    BAD_REQUEST: int = 0xA0
    UNAUTHORISED: int = 0xA1
    FORBIDDEN: int = 0xA3
    NOT_FOUND: int = 0xA4
    NOT_ALLOWED: int = 0xA5
    REQUEST_INCOMPLETE: int = 0xA8
    CONFLICT: int = 0xA9
    REQUEST_TOO_LARGE: int = 0xAD
    UNSUPPORTED_FORMAT: int = 0xAF
    INTERNAL_ERROR: int = 0xC0
    NOT_IMPLEMENTED: int = 0xC1
    GATEWAY_TIMEOUT: int = 0xC4
    NOT_GATEWAY: int = 0xC5

    @staticmethod
    def status_code_name(code: int) -> Union[str, None]:
        """Get status code name from status code integer

        Args:
            code: an integer corresponding to a `ThingSetStatus` attribute

        Returns:
            string that corresponds to the given status code
        """

        for field in fields(ThingSetStatus()):
            if getattr(ThingSetStatus(), field.name) == code:
                return field.name

        return None


@dataclass
class ThingSetRequest(object):
    """Dataclass to contain ThingSet request codes
    and their names plus utility functions
    """

    GET: int = 0x01
    EXEC: int = 0x02
    DELETE: int = 0x04
    FETCH: int = 0x05
    CREATE: int = 0x06
    UPDATE: int = 0x07

    @staticmethod
    def request_name(req: int) -> Union[str, None]:
        """Get request name from request integer

        Args:
            req: an integer corresponding to a `ThingSetRequest` attribute

        Returns:
            string that corresponds to the given request integer
        """

        for field in fields(ThingSetRequest()):
            if getattr(ThingSetRequest(), field.name) == req:
                return field.name

        return None


class ThingSetValue(object):
    ID_ROOT: int = 0x00

    def __init__(self, value_id: int, value: Any, name: Union[str, None] = None):
        self.id = value_id
        self.name = name
        self.value = value

    def __str__(self) -> str:
        if self.id is not None:
            return f"{self.name} (0x{self.id:02X}): {self.value}"
        else:
            return f"{self.name}: {self.value}"

    @property
    def id(self) -> int:
        """

        Args:
            None

        Returns:
            the identifier of the ThingSet parameter
        """

        return self._id

    @id.setter
    def id(self, _id) -> None:
        self._id = _id

    @property
    def name(self) -> str:
        """

        Args:
            None

        Returns:
            the name of the ThingSet parameter
        """

        return self._name

    @name.setter
    def name(self, _name) -> None:
        self._name = _name

    @property
    def value(self) -> Any:
        """

        Args:
            None

        Returns:
            the value of the ThingSet parameter
        """

        return self._value

    @value.setter
    def value(self, _value) -> None:
        self._value = _value


class ThingSetResponse(object):
    MODE_BIN = 0x1
    MODE_TXT = 0x2

    def __init__(
        self,
        backend: str,
        data: Union[bytes, str, None],
        values: Union[List[ThingSetValue], None] = None,
    ):
        """mode is set based on type of backend; binary for CAN or sockets or text for serial"""
        self.mode = backend

        self.status_code = None
        self.status_string = None
        self.data = None
        self.values = values

        if data is not None:
            match self.mode:
                case self.MODE_BIN:
                    self._process_bin(data)
                case self.MODE_TXT:
                    self._process_txt(data)
                case _:
                    raise ValueError(f"Invalid mode ({self.mode}) specified")

    def __str__(self) -> str:
        code = None

        if self.status_code is not None:
            code = f"0x{self.status_code:02X}"

        return f"{code} ({self.status_string}): {self.data}"

    def _process_txt(self, data: str) -> None:
        self._raw_data = data
        self._processed_data = data.split("\r\n")[0][4:]

        self.status_code = self._get_status_byte(self._raw_data)
        self.status_string = ThingSetStatus.status_code_name(self.status_code)

        if len(self._processed_data) > 0:
            try:
                self.data = json.loads(self._processed_data)
            except json.decoder.JSONDecodeError:
                pass

    def _process_bin(self, data: bytes) -> None:
        self._raw_data = data
        self._processed_data = self._strip_null(self._raw_data)

        self.status_code = self._get_status_byte(self._raw_data)
        self.status_string = ThingSetStatus.status_code_name(self.status_code)

        if len(self._processed_data) > 0:
            try:
                self.data = cbor2.loads(self._processed_data)
            except cbor2.CBORDecodeEOF as e:
                self.data = e

    def _get_status_byte(self, data: bytes) -> int:
        match self.mode:
            case self.MODE_BIN:
                return data[0]
            case self.MODE_TXT:
                try:
                    return int(data[1:3], 16)
                except ValueError:
                    return None

    def _strip_null(self, data: bytes) -> bytes:
        return data[1:].replace(b"\xf6", b"", 1)

    @property
    def mode(self) -> int:
        return self._mode

    @mode.setter
    def mode(self, _backend) -> None:
        match _backend:
            case ThingSetBackend.CAN | ThingSetBackend.Socket:
                self._mode = self.MODE_BIN
            case ThingSetBackend.Serial:
                self._mode = self.MODE_TXT

    @property
    def status_code(self) -> int:
        """

        Args:
            None

        Returns:
            a status code corresponding to an attribute of `ThingSetStatus` that indicates whether the operation was succesful
        """

        return self._status_code

    @status_code.setter
    def status_code(self, _status) -> None:
        self._status_code = _status

    @property
    def status_string(self) -> str:
        """

        Args:
            None

        Returns:
            a status code name corresponding to an attribute of `ThingSetStatus` that indicates whether the operation was successful
        """

        return self._status_string

    @status_string.setter
    def status_string(self, _status) -> None:
        self._status_string = _status

    @property
    def data(self) -> Union[Any, None]:
        """

        Args:
            None

        Returns:
            data returned by device that was queried
        """

        return self._data

    @data.setter
    def data(self, _data) -> None:
        self._data = _data
