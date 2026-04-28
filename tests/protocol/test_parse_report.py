"""Edge-case coverage for ThingSetProtocol.parse_report.

parse_report is called on every reassembled UDP payload the sniffer
receives — any silently-malformed report risks a crash in user code,
so the "return None on bad input" contract needs to actually hold.
"""

import cbor2
import pytest

from python_thingset import ThingSetProtocol, WireFormat


_protocol = ThingSetProtocol(WireFormat.BINARY)


def _standard(subset_id, values) -> bytes:
    return (
        bytes([0x1F])
        + cbor2.dumps(subset_id, canonical=True)
        + cbor2.dumps(values, canonical=True)
    )


def _enhanced(eui, subset_id, values) -> bytes:
    return (
        bytes([0x1E])
        + cbor2.dumps(eui, canonical=True)
        + cbor2.dumps(subset_id, canonical=True)
        + cbor2.dumps(values, canonical=True)
    )


def test_empty_payload():
    assert _protocol.parse_report(b"") is None


def test_unknown_type_byte():
    assert _protocol.parse_report(bytes([0x42]) + cbor2.dumps({0x1: 1})) is None


def test_standard_round_trip():
    payload = _standard(0x400, {0x1001: 1.23, 0x1002: 4.56})
    report = _protocol.parse_report(payload)
    assert report is not None
    assert report.subset_id == 0x400
    assert report.values == {0x1001: 1.23, 0x1002: 4.56}
    assert report.eui is None


def test_enhanced_round_trip_preserves_eui():
    payload = _enhanced(0xDEADBEEFC0FFEEEE, 0x400, {0x1001: 42})
    report = _protocol.parse_report(payload)
    assert report is not None
    assert report.eui == 0xDEADBEEFC0FFEEEE
    assert report.subset_id == 0x400
    assert report.values == {0x1001: 42}


def test_subset_id_must_be_int():
    # Swap subset with a string — parse_report should refuse
    payload = (
        bytes([0x1F])
        + cbor2.dumps("not-an-int", canonical=True)
        + cbor2.dumps({0x1: 1}, canonical=True)
    )
    assert _protocol.parse_report(payload) is None


def test_values_must_be_dict():
    # Put a list where the map should be
    payload = (
        bytes([0x1F])
        + cbor2.dumps(0x400, canonical=True)
        + cbor2.dumps([1, 2, 3], canonical=True)
    )
    assert _protocol.parse_report(payload) is None


def test_enhanced_with_non_int_eui():
    # Put a string where the EUI uint should be
    payload = (
        bytes([0x1E])
        + cbor2.dumps("not-a-uint", canonical=True)
        + cbor2.dumps(0x400, canonical=True)
        + cbor2.dumps({0x1: 1}, canonical=True)
    )
    assert _protocol.parse_report(payload) is None


def test_truncated_payload():
    # Start of a standard report but with the map truncated
    good = _standard(0x400, {0x1001: 42, 0x1002: 99})
    # Drop the last two bytes — CBOR decode should fail mid-map
    assert _protocol.parse_report(good[:-2]) is None


def test_enhanced_truncated_before_values():
    # 0x1E header + EUI + subset_id but map is missing entirely
    payload = (
        bytes([0x1E])
        + cbor2.dumps(0xCAFE, canonical=True)
        + cbor2.dumps(0x400, canonical=True)
    )
    assert _protocol.parse_report(payload) is None


def test_malformed_cbor_after_type_byte():
    # Reserved CBOR subtype 0x1c — unconditionally errors
    payload = bytes([0x1F, 0x1C, 0x00, 0x00])
    assert _protocol.parse_report(payload) is None


def test_text_wire_format_raises():
    text_protocol = ThingSetProtocol(WireFormat.TEXT)
    with pytest.raises(ValueError, match="binary only"):
        text_protocol.parse_report(b"anything")


def test_values_empty_dict_is_valid():
    # Empty map is still a valid report (e.g. heartbeat with no measurements)
    payload = _standard(0x400, {})
    report = _protocol.parse_report(payload)
    assert report is not None
    assert report.values == {}
    assert report.subset_id == 0x400


# --- build_single_frame_report (CAN single-frame publishes) -----------

def test_single_frame_round_trip_int():
    payload = cbor2.dumps(42, canonical=True)
    report = _protocol.build_single_frame_report(0x1001, payload)
    assert report is not None
    assert report.subset_id is None
    assert report.eui is None
    assert report.values == {0x1001: 42}


def test_single_frame_round_trip_float():
    payload = cbor2.dumps(3.14, canonical=True)
    report = _protocol.build_single_frame_report(0x602, payload)
    assert report.values == {0x602: 3.14}


def test_single_frame_round_trip_string():
    payload = cbor2.dumps("native_sim", canonical=True)
    report = _protocol.build_single_frame_report(0xF03, payload)
    assert report.values == {0xF03: "native_sim"}


def test_single_frame_round_trip_array():
    payload = cbor2.dumps([1, 2, 3, 4], canonical=True)
    report = _protocol.build_single_frame_report(0xF05, payload)
    assert report.values == {0xF05: [1, 2, 3, 4]}


def test_single_frame_empty_payload_returns_none():
    assert _protocol.build_single_frame_report(0x100, b"") is None


def test_single_frame_malformed_cbor_returns_none():
    assert _protocol.build_single_frame_report(0x100, bytes([0x1C])) is None


def test_single_frame_text_wire_format_raises():
    text = ThingSetProtocol(WireFormat.TEXT)
    with pytest.raises(ValueError, match="binary only"):
        text.build_single_frame_report(0x100, b"\x01")
