#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
"""Structured ThingSet schema — the result of walking a device's object tree.

A :class:`SchemaTree` holds the discovered hierarchy plus flat
``by_id`` and ``by_path`` lookups. Build one with
:meth:`python_thingset.ThingSetClient.discover_schema`.
"""

from dataclasses import dataclass, field
from typing import Dict, Iterator, List


@dataclass
class SchemaNode:
    id: int
    name: str
    type: str
    access: int
    path: str
    children: List["SchemaNode"] = field(default_factory=list)

    def __str__(self) -> str:
        return f"0x{self.id:04X}  {self.path}  ({self.type})"


@dataclass
class SchemaTree:
    root: List[SchemaNode]
    by_id: Dict[int, SchemaNode]
    by_path: Dict[str, SchemaNode]

    def __iter__(self) -> Iterator[SchemaNode]:
        """Flat depth-first iteration in discovery order."""
        def walk(nodes: List[SchemaNode]) -> Iterator[SchemaNode]:
            for node in nodes:
                yield node
                yield from walk(node.children)
        yield from walk(self.root)

    def __len__(self) -> int:
        return len(self.by_id)
