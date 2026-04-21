import cbor2

from python_thingset import ThingSetProtocol, ThingSetStatus, WireFormat


def _mk():
    return ThingSetProtocol(WireFormat.BINARY)


def test_empty_buffer_returns_none():
    resp, consumed = _mk().try_consume(b"")
    assert resp is None
    assert consumed == 0


def test_one_byte_needs_more_data():
    resp, consumed = _mk().try_consume(b"\x85")
    assert resp is None
    assert consumed == 0


def test_status_plus_null_marker_only():
    """status + 0xf6 with no further bytes is a complete status-only response."""
    buf = b"\x85\xf6"
    resp, consumed = _mk().try_consume(buf)
    assert resp is not None
    assert consumed == 2
    assert resp.status_code == ThingSetStatus.CONTENT
    assert resp.status_string == "CONTENT"
    assert resp.data is None


def test_status_plus_null_plus_cbor_payload():
    """status + 0xf6 + CBOR document — the f6 is a marker, payload follows."""
    payload = cbor2.dumps([0x40, 0x41], canonical=True)
    buf = b"\x85\xf6" + payload
    resp, consumed = _mk().try_consume(buf)
    assert resp is not None
    assert consumed == len(buf)
    assert resp.status_code == ThingSetStatus.CONTENT
    assert resp.data == [0x40, 0x41]


def test_status_plus_cbor_no_marker():
    """status + CBOR document directly (no 0xf6 marker)."""
    payload = cbor2.dumps({1: "hello"}, canonical=True)
    buf = b"\x84" + payload
    resp, consumed = _mk().try_consume(buf)
    assert resp is not None
    assert consumed == len(buf)
    assert resp.status_code == ThingSetStatus.CHANGED
    assert resp.data == {1: "hello"}


def test_partial_cbor_returns_none():
    """Truncated CBOR: we must wait for more bytes, not fail."""
    payload = cbor2.dumps([0x40, 0x41, 0x42, 0x43], canonical=True)
    buf = b"\x85\xf6" + payload[:-1]
    resp, consumed = _mk().try_consume(buf)
    assert resp is None
    assert consumed == 0


def test_two_concatenated_responses_extracted_in_sequence():
    """A buffer holding two responses should be consumed one call at a time."""
    p = _mk()
    payload_a = cbor2.dumps([1, 2, 3], canonical=True)
    payload_b = cbor2.dumps("ok", canonical=True)
    msg_a = b"\x85\xf6" + payload_a
    msg_b = b"\x84" + payload_b
    buf = msg_a + msg_b

    resp1, consumed1 = p.try_consume(buf)
    assert resp1 is not None
    assert consumed1 == len(msg_a)
    assert resp1.data == [1, 2, 3]

    resp2, consumed2 = p.try_consume(buf[consumed1:])
    assert resp2 is not None
    assert consumed2 == len(msg_b)
    assert resp2.data == "ok"


def test_malformed_cbor_drops_buffer_to_resync():
    """Malformed CBOR after the status byte drops the buffer — caller
    discards bytes up to consumed and moves on. 0x1c is a reserved
    unsigned-integer subtype and reliably raises CBORDecodeError."""
    buf = b"\x85\x1c\x00\x00"
    resp, consumed = _mk().try_consume(buf)
    assert resp is None
    assert consumed == len(buf)


def test_text_wire_format_rejects_try_consume():
    """try_consume is binary only; text transports use line framing."""
    p = ThingSetProtocol(WireFormat.TEXT)
    try:
        p.try_consume(b"something")
    except ValueError:
        return
    raise AssertionError("expected ValueError for text try_consume")


def test_parse_response_binary_end_to_end():
    p = _mk()
    payload = cbor2.dumps([0x40, 0x41], canonical=True)
    parsed = p.parse_response(b"\x85\xf6" + payload)
    assert parsed.status_code == ThingSetStatus.CONTENT
    assert parsed.status_string == "CONTENT"
    assert parsed.data == [0x40, 0x41]


def test_parse_response_text_end_to_end():
    p = ThingSetProtocol(WireFormat.TEXT)
    parsed = p.parse_response(':85 {"rVoltage":48.0}\r\n')
    assert parsed.status_code == ThingSetStatus.CONTENT
    assert parsed.status_string == "CONTENT"
    assert parsed.data == {"rVoltage": 48.0}
