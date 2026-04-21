"""Byte-level tests for ThingSetProtocol.wrap_forward.

The wire contract (from Brill-Power/ThingSet.Net analysis):
    [0x1C][CBOR text string of EUI as 16 lowercase hex chars][inner]

The gateway strips the first two CBOR items and routes the inner
request to the module whose EUI matches.
"""

import io

import cbor2
import pytest

from python_thingset import ThingSetProtocol, WireFormat


_protocol = ThingSetProtocol(WireFormat.BINARY)


def test_wrap_forward_byte_shape():
    inner = bytes([0x01, 0x19, 0x0F, 0x03])  # get(0xF03)
    wrapped = _protocol.wrap_forward(inner, 0xBADB1B0000000001)
    # CBOR text string of length 16: initial byte 0x70, then the 16 chars
    expected_prefix = bytes([0x1C, 0x70]) + b"badb1b0000000001"
    assert wrapped.startswith(expected_prefix)
    assert wrapped[len(expected_prefix):] == inner


def test_wrap_forward_round_trip_via_cbor():
    inner = b"inner request bytes"
    wrapped = _protocol.wrap_forward(inner, 0xDEADBEEF12345678)
    assert wrapped[0] == 0x1C
    stream = io.BytesIO(wrapped[1:])
    eui_str = cbor2.load(stream)
    assert eui_str == "deadbeef12345678"
    assert stream.read() == inner


def test_wrap_forward_eui_is_zero_padded():
    wrapped = _protocol.wrap_forward(b"x", 0x01)
    stream = io.BytesIO(wrapped[1:])
    eui_str = cbor2.load(stream)
    assert eui_str == "0000000000000001"
    assert len(eui_str) == 16


def test_wrap_forward_eui_uses_lowercase_hex():
    wrapped = _protocol.wrap_forward(b"x", 0xAABBCCDDEEFF0011)
    stream = io.BytesIO(wrapped[1:])
    eui_str = cbor2.load(stream)
    assert eui_str == "aabbccddeeff0011"


def test_wrap_forward_preserves_inner_bytes_exactly():
    inner = bytes(range(256))  # arbitrary byte pattern
    wrapped = _protocol.wrap_forward(inner, 0x1234567890ABCDEF)
    stream = io.BytesIO(wrapped[1:])
    cbor2.load(stream)  # consume the EUI string
    assert stream.read() == inner


def test_wrap_forward_text_wire_format_raises():
    text = ThingSetProtocol(WireFormat.TEXT)
    with pytest.raises(ValueError, match="binary only"):
        text.wrap_forward(b"x", 0x1234)
