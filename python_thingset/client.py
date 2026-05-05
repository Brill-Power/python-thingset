#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Union

from ._protocol import ParsedResponse, ThingSetProtocol, WireFormat
from .response import ThingSetResponse, ThingSetStatus, ThingSetValue
from .schema import SchemaNode, SchemaTree


# Binary ThingSet metadata overlay (used by discover_schema)
_METADATA_OVERLAY = 0x19
_METADATA_KEY_NAME = 26  # 0x1A
_METADATA_KEY_TYPE = 27  # 0x1B
_METADATA_KEY_ACCESS = 28  # 0x1C
# Types whose metadata advertises a parent node we can descend into.
# "group" is the conventional namespace; "record"/"record[]" appear when
# a property exposes a struct or array-of-struct (see TS++ ThingSetType.hpp:
# the ThingSetType default is "record" and array suffixes append "[]"),
# and the inner record members are registered as parent-scoped children.
_RECURSIVE_TYPES = {"group", "record", "record[]"}


class ThingSetClient(ABC):
    """Abstract client: templates the fetch/get/exec/update flow over
    an encoded request followed by a parsed response. Subclasses provide
    the transport by implementing _send and _recv, and set self._protocol.
    """

    _protocol: ThingSetProtocol

    @property
    def wire_format(self) -> WireFormat:
        return self._protocol.wire_format

    def fetch(
        self,
        parent_id: Union[int, str],
        ids: List[Union[int, str]],
        node_id: Union[int, None] = None,
    ) -> ThingSetResponse:
        self._send(self._protocol.encode_fetch(parent_id, ids), node_id)
        parsed = self._recv()

        values: List[ThingSetValue] = []
        if (
            parsed is not None
            and parsed.status_code is not None
            and parsed.status_code <= ThingSetStatus.CONTENT
        ):
            if len(ids) == 0:
                values.append(self._build_value(parent_id, parsed.data))
            else:
                for idx, vid in enumerate(ids):
                    values.append(self._build_value(vid, parsed.data[idx]))

        return self._to_response(parsed, values)

    def get(
        self,
        value_id: Union[int, str],
        node_id: Union[int, None] = None,
    ) -> ThingSetResponse:
        self._send(self._protocol.encode_get(value_id), node_id)
        parsed = self._recv()

        values: List[ThingSetValue] = []
        if (
            parsed is not None
            and parsed.status_code is not None
            and parsed.status_code <= ThingSetStatus.CONTENT
        ):
            values.append(self._build_value(value_id, parsed.data))

        return self._to_response(parsed, values)

    def update(
        self,
        value_id: Union[int, str],
        value: Any,
        node_id: Union[int, None] = None,
        parent_id: Union[int, None] = None,
    ) -> ThingSetResponse:
        self._send(self._protocol.encode_update(parent_id, value_id, value), node_id)
        return self._to_response(self._recv())

    def exec(
        self,
        value_id: Union[int, str],
        args: Union[List[Any], None],
        node_id: Union[int, None] = None,
    ) -> ThingSetResponse:
        self._send(self._protocol.encode_exec(value_id, args), node_id)
        return self._to_response(self._recv())

    def discover_schema(
        self,
        root_id: int = 0,
        node_id: Union[int, None] = None,
    ) -> SchemaTree:
        """Walk the device's object tree and build a structured schema.

        Issues two fetches per group: one for child IDs, one for the
        metadata overlay (which carries name, type and access for every
        child in a single round-trip). Recursion is bounded by type:
        only children whose type is ``"group"`` are walked further;
        records, functions and primitives are terminal.

        Binary wire format only — raises ``ValueError`` on text
        transports, which lack the metadata overlay.
        """
        if self.wire_format is not WireFormat.BINARY:
            raise ValueError(
                "discover_schema requires a binary wire format (TCP or CAN)"
            )
        by_id: Dict[int, SchemaNode] = {}
        by_path: Dict[str, SchemaNode] = {}
        root = self._walk_schema(root_id, "", node_id, by_id, by_path)
        return SchemaTree(root=root, by_id=by_id, by_path=by_path)

    def _walk_schema(
        self,
        group_id: int,
        path_prefix: str,
        node_id: Union[int, None],
        by_id: Dict[int, SchemaNode],
        by_path: Dict[str, SchemaNode],
    ) -> List[SchemaNode]:
        fresp = self.fetch(group_id, [], node_id)
        if not fresp.values:
            return []
        child_ids = fresp.values[0].value
        if not isinstance(child_ids, list) or not child_ids:
            return []

        mresp = self.fetch(_METADATA_OVERLAY, child_ids, node_id)
        if mresp.status_code != ThingSetStatus.CONTENT or not mresp.values:
            return []

        nodes: List[SchemaNode] = []
        for idx, cid in enumerate(child_ids):
            md = mresp.values[idx].value if idx < len(mresp.values) else None
            if not isinstance(md, dict):
                continue
            name = md.get(_METADATA_KEY_NAME, "")
            type_str = md.get(_METADATA_KEY_TYPE, "")
            access = md.get(_METADATA_KEY_ACCESS, 0)
            full_path = f"{path_prefix}/{name}" if path_prefix else name

            children: List[SchemaNode] = []
            if type_str in _RECURSIVE_TYPES:
                children = self._walk_schema(
                    cid, full_path, node_id, by_id, by_path
                )

            node = SchemaNode(
                id=cid,
                name=name,
                type=type_str,
                access=access,
                path=full_path,
                children=children,
            )
            nodes.append(node)
            by_id[cid] = node
            by_path[full_path] = node

        return nodes

    def _build_value(
        self,
        value_id: Union[int, str],
        value: Any,
    ) -> ThingSetValue:
        if self.wire_format is WireFormat.TEXT:
            # Text (serial) addresses values by path; the "id" IS the path
            return ThingSetValue(None, value, value_id)
        return ThingSetValue(value_id, value, None)

    @staticmethod
    def _to_response(
        parsed: Union[ParsedResponse, None],
        values: Union[List[ThingSetValue], None] = None,
    ) -> ThingSetResponse:
        if parsed is None:
            return ThingSetResponse(values=values)
        return ThingSetResponse(
            status_code=parsed.status_code,
            status_string=parsed.status_string,
            data=parsed.data,
            values=values,
            raw=parsed.raw,
        )

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def _send(self, data: bytes, node_id: Union[int, None]) -> None:
        pass

    @abstractmethod
    def _recv(self) -> Union[ParsedResponse, None]:
        pass

    def __enter__(self) -> "ThingSetClient":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()
