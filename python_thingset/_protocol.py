#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
"""Sans-io ThingSet protocol core.

Encodes requests into bytes, parses response bytes into structured
ParsedResponse objects, and provides streaming framing for binary
transports via try_consume(). This module performs no I/O; transports
feed it bytes and pull parsed responses.
"""

import io
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Tuple, Union

import cbor2

from .encoders import ThingSetBinaryEncoder, ThingSetTextEncoder
from .report import ThingSetReport
from .response import ThingSetStatus


class WireFormat(Enum):
    BINARY = 1
    TEXT = 2


@dataclass
class ParsedResponse:
    status_code: Union[int, None]
    status_string: Union[str, None]
    data: Any
    raw: Union[bytes, str]


CBOR_NULL = 0xF6
REPORT_TYPE_STANDARD = 0x1F
REPORT_TYPE_ENHANCED = 0x1E
REQUEST_FORWARD = 0x1C


class ThingSetProtocol:
    def __init__(self, wire_format: WireFormat):
        self.wire_format = wire_format
        if wire_format is WireFormat.BINARY:
            self._encoder = ThingSetBinaryEncoder()
        elif wire_format is WireFormat.TEXT:
            self._encoder = ThingSetTextEncoder()
        else:
            raise ValueError(f"Unknown wire format: {wire_format}")

    def encode_get(self, value_id) -> bytes:
        return self._encoder.encode_get(value_id)

    def encode_fetch(self, parent_id, ids) -> bytes:
        return self._encoder.encode_fetch(parent_id, ids)

    def encode_exec(self, value_id, args) -> bytes:
        return self._encoder.encode_exec(value_id, args)

    def encode_update(self, parent_id, value_id, value) -> bytes:
        return self._encoder.encode_update(parent_id, value_id, value)

    def wrap_forward(self, inner: bytes, target_eui: int) -> bytes:
        """Wrap ``inner`` in a gateway-forward envelope targeting
        ``target_eui``.

        The wire shape is ``[0x1C][CBOR text string of EUI as 16 lowercase
        hex chars][inner request bytes]``. The gateway (e.g. an HMCU
        bridging TCP↔CAN) strips the first two CBOR items and routes
        the remaining bytes to the module with the matching EUI. The
        response comes back unwrapped.

        Binary only — gateway forwarding isn't a concept on text
        (serial) transports.
        """
        if self.wire_format is not WireFormat.BINARY:
            raise ValueError("wrap_forward is binary only")
        eui_str = f"{target_eui:016x}"
        return bytes([REQUEST_FORWARD]) + cbor2.dumps(eui_str, canonical=True) + inner

    def parse_response(self, data: Union[bytes, str]) -> ParsedResponse:
        if self.wire_format is WireFormat.BINARY:
            return self._parse_binary(data)
        return self._parse_text(data)

    def parse_report(self, payload: bytes) -> Union[ThingSetReport, None]:
        """Parse a reassembled report payload (no UDP framing header).

        Returns ``None`` if the payload is empty, of an unknown type,
        or contains malformed CBOR. Expected layout:

        - ``[0x1F][CBOR uint: subset_id][CBOR map: {id: value}]``
        - ``[0x1E][CBOR uint64: eui][CBOR uint: subset_id][CBOR map: {id: value}]``

        Binary only; the publish/subscribe path doesn't exist on text
        transports.
        """
        if self.wire_format is not WireFormat.BINARY:
            raise ValueError("parse_report is binary only")
        if not payload:
            return None
        type_byte = payload[0]
        if type_byte not in (REPORT_TYPE_STANDARD, REPORT_TYPE_ENHANCED):
            return None

        stream = io.BytesIO(payload[1:])
        try:
            eui: Union[int, None] = None
            if type_byte == REPORT_TYPE_ENHANCED:
                eui = cbor2.load(stream)
            subset_id = cbor2.load(stream)
            values = cbor2.load(stream)
        except (cbor2.CBORDecodeError, cbor2.CBORDecodeEOF):
            return None

        if not isinstance(subset_id, int) or not isinstance(values, dict):
            return None
        if eui is not None and not isinstance(eui, int):
            return None
        return ThingSetReport(subset_id=subset_id, values=values, eui=eui)

    def build_single_frame_report(
        self, data_id: int, payload: bytes
    ) -> Union[ThingSetReport, None]:
        """Synthesize a report from a CAN single-frame publish.

        On CAN, single-frame reports carry a single data ID in the
        CAN arbitration ID and the bare CBOR-encoded value as payload
        — no envelope byte, no subset id. We surface this through the
        same ``ThingSetReport`` shape with ``subset_id=None`` and a
        one-entry ``values`` map, so consumers can treat all reports
        uniformly.

        Returns ``None`` if the payload doesn't decode as a valid
        single CBOR document.
        """
        if self.wire_format is not WireFormat.BINARY:
            raise ValueError("build_single_frame_report is binary only")
        if not payload:
            return None
        try:
            value = cbor2.loads(payload)
        except (cbor2.CBORDecodeError, cbor2.CBORDecodeEOF):
            return None
        return ThingSetReport(subset_id=None, values={data_id: value}, eui=None)

    def try_consume(self, buffer: bytes) -> Tuple[Union[ParsedResponse, None], int]:
        """Extract one complete binary response from the start of ``buffer``.

        Returns ``(response, consumed)`` — ``consumed`` is the number of
        leading bytes the caller should drop. If the buffer does not yet
        hold a complete message, returns ``(None, 0)``. On malformed CBOR
        the whole buffer is consumed to resync.

        Binary only; text transports should call parse_response() with a
        complete newline-framed line.
        """
        if self.wire_format is not WireFormat.BINARY:
            raise ValueError("try_consume is binary only")
        if len(buffer) < 2:
            return None, 0

        offset = 1  # status byte
        if buffer[offset] == CBOR_NULL:
            offset += 1
            if offset == len(buffer):
                return self._parse_binary(buffer[:offset]), offset

        stream = io.BytesIO(buffer[offset:])
        try:
            cbor2.load(stream)
        except cbor2.CBORDecodeEOF:
            return None, 0
        except cbor2.CBORDecodeError:
            return None, len(buffer)

        consumed = offset + stream.tell()
        return self._parse_binary(buffer[:consumed]), consumed

    def _parse_binary(self, data: bytes) -> ParsedResponse:
        status_code = data[0] if len(data) > 0 else None
        status_string = (
            ThingSetStatus.status_code_name(status_code)
            if status_code is not None
            else None
        )
        payload = data[1:].replace(b"\xf6", b"", 1)
        parsed: Any = None
        if len(payload) > 0:
            try:
                parsed = cbor2.loads(payload)
            except cbor2.CBORDecodeEOF as e:
                parsed = e
        return ParsedResponse(status_code, status_string, parsed, data)

    def _parse_text(self, data: Union[bytes, str]) -> ParsedResponse:
        if isinstance(data, bytes):
            data = data.decode()
        line = data.split("\r\n")[0]
        try:
            status_code = int(line[1:3], 16)
        except (ValueError, IndexError):
            status_code = None
        status_string = (
            ThingSetStatus.status_code_name(status_code)
            if status_code is not None
            else None
        )
        payload_str = line[4:]
        parsed: Any = None
        if len(payload_str) > 0:
            try:
                parsed = json.loads(payload_str)
            except json.decoder.JSONDecodeError:
                pass
        return ParsedResponse(status_code, status_string, parsed, data)
