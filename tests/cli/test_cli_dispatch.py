"""Unit tests for the CLI's args.Namespace classifiers.

- ``_op_hint`` picks the right friendly-error string for silent-timeout
  responses based on what the user typed.
- ``_node_id_for`` extracts the CAN target address and returns None
  for TCP / serial invocations.
"""

import argparse

from python_thingset.cli import _node_id_for, _op_hint


def _ns(**overrides) -> argparse.Namespace:
    """Fixture with all the attributes the CLI sets post-parse."""
    defaults = dict(
        method=None,
        id=None,
        parent_id=None,
        value_ids=[],
        value_id=None,
        values=[],
        update_args=[],
        root_id="00",
        can_bus=None,
        target_address=None,
        port=None,
        baud_rate=115200,
        ip=None,
        target_eui=None,
    )
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ---------- _op_hint ----------

def test_op_hint_get_root_as_hex_zero():
    assert _op_hint(_ns(method="get", id="0")) == "get_root"


def test_op_hint_get_root_as_00():
    assert _op_hint(_ns(method="get", id="00")) == "get_root"


def test_op_hint_get_nonzero_id_is_none():
    assert _op_hint(_ns(method="get", id="f03")) is None


def test_op_hint_fetch_with_ids_flagged():
    assert _op_hint(_ns(method="fetch", value_ids=["f01", "f02"])) == "fetch_with_ids"


def test_op_hint_fetch_without_ids_is_none():
    # fetch(parent, []) — the working pattern; no hint needed
    assert _op_hint(_ns(method="fetch", value_ids=[])) is None


def test_op_hint_update_is_none():
    assert _op_hint(_ns(method="update")) is None


def test_op_hint_exec_is_none():
    assert _op_hint(_ns(method="exec")) is None


def test_op_hint_schema_is_none():
    assert _op_hint(_ns(method="schema")) is None


def test_op_hint_get_non_hex_id_is_none():
    # e.g. serial path where id is a string path like "Build/rBoard"
    assert _op_hint(_ns(method="get", id="Build/rBoard")) is None


# ---------- _node_id_for ----------

def test_node_id_for_can_parses_hex():
    assert _node_id_for(_ns(can_bus="vcan0", target_address="2F")) == 0x2F


def test_node_id_for_can_parses_with_zero_prefix():
    assert _node_id_for(_ns(can_bus="vcan0", target_address="10")) == 0x10


def test_node_id_for_tcp_is_none():
    assert _node_id_for(_ns(ip="192.168.1.1")) is None


def test_node_id_for_serial_is_none():
    assert _node_id_for(_ns(port="/dev/ttyACM0")) is None


def test_node_id_for_tcp_with_target_eui_is_still_none():
    # target_eui is handled at transport level, not via node_id
    assert (
        _node_id_for(_ns(ip="192.168.1.1", target_eui="badb1b0000000001"))
        is None
    )


def test_node_id_for_can_without_target_address_is_none():
    # Argparse would normally reject this, but defensive code should cope
    assert _node_id_for(_ns(can_bus="vcan0", target_address=None)) is None
