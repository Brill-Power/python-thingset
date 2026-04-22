#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
from dataclasses import dataclass, fields
from typing import Any, List, Union


@dataclass
class ThingSetStatus:
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
        for field in fields(ThingSetStatus()):
            if getattr(ThingSetStatus(), field.name) == code:
                return field.name
        return None


@dataclass
class ThingSetRequest:
    GET: int = 0x01
    EXEC: int = 0x02
    DELETE: int = 0x04
    FETCH: int = 0x05
    CREATE: int = 0x06
    UPDATE: int = 0x07

    @staticmethod
    def request_name(req: int) -> Union[str, None]:
        for field in fields(ThingSetRequest()):
            if getattr(ThingSetRequest(), field.name) == req:
                return field.name
        return None


class ThingSetValue:
    ID_ROOT: int = 0x00

    def __init__(
        self,
        value_id: Union[int, None],
        value: Any,
        name: Union[str, None] = None,
    ):
        self.id = value_id
        self.name = name
        self.value = value

    def __str__(self) -> str:
        if self.id is not None:
            return f"{self.name} (0x{self.id:02X}): {self.value}"
        return f"{self.name}: {self.value}"


class ThingSetResponse:
    """User-facing response object returned by ThingSet client methods.

    Wraps the already-parsed fields emitted by the protocol layer, plus
    an optional list of ThingSetValue objects constructed by the client
    from the response payload.
    """

    def __init__(
        self,
        status_code: Union[int, None] = None,
        status_string: Union[str, None] = None,
        data: Any = None,
        values: Union[List[ThingSetValue], None] = None,
        raw: Union[bytes, str, None] = None,
    ):
        self.status_code = status_code
        self.status_string = status_string
        self.data = data
        self.values = values
        self.raw = raw

    def __str__(self) -> str:
        code = None
        if self.status_code is not None:
            code = f"0x{self.status_code:02X}"
        return f"{code} ({self.status_string}): {self.data}"
