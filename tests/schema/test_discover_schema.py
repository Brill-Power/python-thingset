"""Unit tests for ThingSetClient.discover_schema using a fake client.

The fake client replays canned responses keyed by (parent_id, tuple_of_ids).
It covers just enough of the wire contract to exercise the schema walker
without any real transport.
"""

import io
from typing import Any, Dict, Tuple, Union

import cbor2
import pytest

from python_thingset import (
    ParsedResponse,
    SchemaTree,
    ThingSetProtocol,
    ThingSetStatus,
    WireFormat,
)
from python_thingset.client import ThingSetClient


# (parent_id, tuple_of_child_ids) -> data payload the device would return
CannedMap = Dict[Tuple[Any, Tuple[int, ...]], Any]


class _FakeBinaryClient(ThingSetClient):
    def __init__(self, canned: CannedMap):
        self._protocol = ThingSetProtocol(WireFormat.BINARY)
        self._canned = canned
        self._pending: Union[ParsedResponse, None] = None

    def _send(self, data: bytes, node_id):
        # data is a binary ThingSet FETCH: [0x05][cbor parent_id][0xf6 | cbor list]
        stream = io.BytesIO(data[1:])
        parent = cbor2.load(stream)
        remaining = stream.read()
        if remaining == b"\xf6":
            ids: Tuple[int, ...] = ()
        elif remaining:
            ids = tuple(cbor2.loads(remaining))
        else:
            ids = ()
        data_payload = self._canned.get((parent, ids))
        self._pending = ParsedResponse(
            status_code=ThingSetStatus.CONTENT,
            status_string="CONTENT",
            data=data_payload,
            raw=b"",
        )

    def _recv(self):
        resp, self._pending = self._pending, None
        return resp

    def disconnect(self):
        pass


class _FakeTextClient(ThingSetClient):
    def __init__(self):
        self._protocol = ThingSetProtocol(WireFormat.TEXT)

    def _send(self, data, node_id):
        pass

    def _recv(self):
        return None

    def disconnect(self):
        pass


# Minimal three-level tree exercising group/leaf/function/record terminations
# and nested groups — mirrors native_sim's shape.
CANNED: CannedMap = {
    # Root: DSM (group), Metadata (group), Modules (record[]), xRebootDFU (fn)
    (0, ()): [0x0E, 0x0F, 0x09, 0x67],
    (0x19, (0x0E, 0x0F, 0x09, 0x67)): [
        {26: "DSM", 27: "group", 28: 7},
        {26: "Metadata", 27: "group", 28: 7},
        {26: "Modules", 27: "record[]", 28: 7},
        {26: "xRebootDFU", 27: "()->(i32)", 28: 112},
    ],
    # DSM: one function + one primitive leaf
    (0x0E, ()): [0xE00, 0xE04],
    (0x19, (0xE00, 0xE04)): [
        {26: "xOff", 27: "()->(i32)", 28: 112},
        {26: "rDFUState", 27: "u8", 28: 7},
    ],
    # Metadata: one nested group + one primitive leaf
    (0x0F, ()): [0xFFF, 0xF03],
    (0x19, (0xFFF, 0xF03)): [
        {26: "Nested", 27: "group", 28: 7},
        {26: "rBoard", 27: "string", 28: 7},
    ],
    # Nested group (under Metadata) with a single leaf
    (0xFFF, ()): [0xFF0],
    (0x19, (0xFF0,)): [
        {26: "rDeep", 27: "u32", 28: 7},
    ],
}


@pytest.fixture
def tree() -> SchemaTree:
    return _FakeBinaryClient(CANNED).discover_schema()


def test_all_expected_ids_discovered(tree: SchemaTree):
    assert set(tree.by_id.keys()) == {
        0x0E, 0x0F, 0x09, 0x67,
        0xE00, 0xE04,
        0xFFF, 0xF03,
        0xFF0,
    }


def test_by_path_lookup(tree: SchemaTree):
    assert tree.by_path["DSM"].id == 0x0E
    assert tree.by_path["DSM/rDFUState"].id == 0xE04
    assert tree.by_path["Metadata/rBoard"].id == 0xF03
    assert tree.by_path["Metadata/Nested/rDeep"].id == 0xFF0


def test_node_fields_populated(tree: SchemaTree):
    node = tree.by_id[0xE04]
    assert node.name == "rDFUState"
    assert node.type == "u8"
    assert node.access == 7
    assert node.path == "DSM/rDFUState"
    assert node.children == []


def test_group_has_children(tree: SchemaTree):
    dsm = tree.by_id[0x0E]
    assert dsm.type == "group"
    assert [c.id for c in dsm.children] == [0xE00, 0xE04]


def test_record_and_function_not_recursed(tree: SchemaTree):
    """record[] and function types are terminal — no children walked even if the device would have returned some."""
    assert tree.by_id[0x09].type == "record[]"
    assert tree.by_id[0x09].children == []
    assert tree.by_id[0x67].type == "()->(i32)"
    assert tree.by_id[0x67].children == []


def test_nested_group_recursed(tree: SchemaTree):
    nested = tree.by_path["Metadata/Nested"]
    assert nested.type == "group"
    assert [c.name for c in nested.children] == ["rDeep"]


def test_flat_iteration_in_discovery_order(tree: SchemaTree):
    ids_in_order = [n.id for n in tree]
    # Depth-first: DSM, xOff, rDFUState, Metadata, Nested, rDeep, rBoard, Modules, xRebootDFU
    assert ids_in_order == [
        0x0E, 0xE00, 0xE04,
        0x0F, 0xFFF, 0xFF0, 0xF03,
        0x09, 0x67,
    ]


def test_len_matches_by_id(tree: SchemaTree):
    assert len(tree) == len(tree.by_id)


def test_root_list_only_top_level(tree: SchemaTree):
    assert [n.id for n in tree.root] == [0x0E, 0x0F, 0x09, 0x67]


def test_node_str_repr(tree: SchemaTree):
    assert str(tree.by_id[0xE04]) == "0x0E04  DSM/rDFUState  (u8)"


def test_text_wire_format_raises():
    with pytest.raises(ValueError, match="binary"):
        _FakeTextClient().discover_schema()


def test_empty_response_yields_empty_tree():
    empty: CannedMap = {(0, ()): []}
    tree = _FakeBinaryClient(empty).discover_schema()
    assert tree.root == []
    assert tree.by_id == {}
    assert tree.by_path == {}
