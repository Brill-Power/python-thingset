#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
"""Async ThingSet client base class.

Mirrors the sync :class:`ThingSetClient` surface with ``async def``
RPCs suitable for an asyncio event loop. Subclasses implement
:meth:`_rpc` to perform a single request/response exchange.

ThingSet's wire protocol has no correlation ID, so a single transport
can only carry one RPC at a time. Concrete subclasses MUST serialize
concurrent callers internally (typically via an ``asyncio.Lock``).
Serialization still yields the event loop during I/O, which is the
whole point — the Device Bridge keeps running other coroutines while
a ThingSet RPC is in flight.
"""

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
_RECURSIVE_TYPE = "group"


class AsyncThingSetClient(ABC):
    _protocol: ThingSetProtocol

    @property
    def wire_format(self) -> WireFormat:
        return self._protocol.wire_format

    async def fetch(
        self,
        parent_id: Union[int, str],
        ids: List[Union[int, str]],
        node_id: Union[int, None] = None,
    ) -> ThingSetResponse:
        parsed = await self._rpc(
            self._protocol.encode_fetch(parent_id, ids), node_id
        )
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

    async def get(
        self,
        value_id: Union[int, str],
        node_id: Union[int, None] = None,
    ) -> ThingSetResponse:
        parsed = await self._rpc(self._protocol.encode_get(value_id), node_id)
        values: List[ThingSetValue] = []
        if (
            parsed is not None
            and parsed.status_code is not None
            and parsed.status_code <= ThingSetStatus.CONTENT
        ):
            values.append(self._build_value(value_id, parsed.data))
        return self._to_response(parsed, values)

    async def update(
        self,
        value_id: Union[int, str],
        value: Any,
        node_id: Union[int, None] = None,
        parent_id: Union[int, None] = None,
    ) -> ThingSetResponse:
        parsed = await self._rpc(
            self._protocol.encode_update(parent_id, value_id, value), node_id
        )
        return self._to_response(parsed)

    async def exec(
        self,
        value_id: Union[int, str],
        args: Union[List[Any], None],
        node_id: Union[int, None] = None,
    ) -> ThingSetResponse:
        parsed = await self._rpc(
            self._protocol.encode_exec(value_id, args), node_id
        )
        return self._to_response(parsed)

    async def discover_schema(
        self,
        root_id: int = 0,
        node_id: Union[int, None] = None,
    ) -> SchemaTree:
        if self.wire_format is not WireFormat.BINARY:
            raise ValueError(
                "discover_schema requires a binary wire format (TCP or CAN)"
            )
        by_id: Dict[int, SchemaNode] = {}
        by_path: Dict[str, SchemaNode] = {}
        root = await self._walk_schema(root_id, "", node_id, by_id, by_path)
        return SchemaTree(root=root, by_id=by_id, by_path=by_path)

    async def _walk_schema(
        self,
        group_id: int,
        path_prefix: str,
        node_id: Union[int, None],
        by_id: Dict[int, SchemaNode],
        by_path: Dict[str, SchemaNode],
    ) -> List[SchemaNode]:
        fresp = await self.fetch(group_id, [], node_id)
        if not fresp.values:
            return []
        child_ids = fresp.values[0].value
        if not isinstance(child_ids, list) or not child_ids:
            return []

        mresp = await self.fetch(_METADATA_OVERLAY, child_ids, node_id)
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
            if type_str == _RECURSIVE_TYPE:
                children = await self._walk_schema(
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
    async def close(self) -> None:
        pass

    @abstractmethod
    async def _rpc(
        self, request: bytes, node_id: Union[int, None]
    ) -> Union[ParsedResponse, None]:
        pass

    async def __aenter__(self) -> "AsyncThingSetClient":
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()
