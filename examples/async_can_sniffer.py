"""Listen for ThingSet reports on a CAN bus and print each one.

Single-frame and multi-frame reports both surface as
:class:`ThingSetReport`. Single-frame ones synthesise from the CAN-ID
data field (``subset_id is None``, single-entry ``values`` map);
multi-frame reports carry ``subset_id`` and optionally ``eui`` in the
usual envelope.

Usage:
    python examples/async_can_sniffer.py [-i can0|vcan0|...] [--source HEX]
                                         [-v|--verbose] [--no-fd]
                                         [--decorate] [--record-fields PATH]

Stop with Ctrl+C.
"""

import argparse
import asyncio
import json
import logging
import time

from python_thingset import (
    AsyncThingSetCANReportReceiver,
    SchemaNode,
    SchemaTree,
    ThingSetCAN,
    ThingSetStatus,
)


def _fmt(v) -> str:
    """Dict keys (ThingSet IDs) as uppercase hex; values as plain repr."""
    if isinstance(v, dict):
        parts = []
        for k, val in v.items():
            if isinstance(k, int) and not isinstance(k, bool):
                key = f"0x{k:X}"
            else:
                key = repr(k)
            parts.append(f"{key}: {_fmt(val)}")
        return "{" + ", ".join(parts) + "}"
    if isinstance(v, list):
        return "[" + ", ".join(_fmt(i) for i in v) + "]"
    return repr(v)


def _decorate_id(obj_id: int, tree: SchemaTree | None) -> str:
    label = f"{obj_id:#06X}"
    if tree is not None:
        node = tree.by_id.get(obj_id)
        if node is not None:
            label += f"  {node.path}"
    return label


def _print_decorated(
    indent: str,
    label: str,
    value,
    tree: SchemaTree | None,
    schema_cache: "_SchemaCache | None",
    source: int | None,
) -> None:
    """Recursively print (label, value) with schema decoration. Mirrors
    the UDP sniffer: dicts expand one inner key per line, lists of dicts
    expand per-entry. Unknown inner IDs get scheduled for metadata
    resolution so the *next* report displays them with names."""
    if isinstance(value, dict):
        if schema_cache is not None and source is not None:
            schema_cache.maybe_resolve_unknowns(source, value.keys())
        print(f"{indent}{label}:")
        for k, v in value.items():
            inner_label = (
                _decorate_id(k, tree) if isinstance(k, int) else repr(k)
            )
            _print_decorated(
                indent + "    ", inner_label, v, tree, schema_cache, source
            )
        return

    if (
        isinstance(value, list)
        and value
        and all(isinstance(i, dict) for i in value)
    ):
        print(f"{indent}{label}: (list of {len(value)})")
        for idx, entry in enumerate(value):
            _print_decorated(
                indent + "    ", f"[{idx}]", entry, tree, schema_cache, source
            )
        return

    print(f"{indent}{label} -> {_fmt(value)}")


_METADATA_OVERLAY = 0x19
_METADATA_KEY_NAME = 26
_METADATA_KEY_TYPE = 27
_METADATA_KEY_ACCESS = 28


class _SchemaCache:
    """Lazily fetches the schema for each newly-seen source node.

    Unlike the UDP variant there's no gateway-forwarding model on CAN —
    each source node has exactly one schema, keyed on the 8-bit source
    address. All fetches share a single underlying ``ThingSetCAN``
    client (constructed lazily on first need) and run in a worker
    thread to keep the asyncio loop responsive. An ``asyncio.Lock``
    serialises overlapping fetches because ``ThingSetCAN`` re-binds
    its ISO-TP socket per request and is not concurrent-safe.
    """

    SCHEMA_FETCH_TIMEOUT_S = 30.0
    METADATA_FETCH_TIMEOUT_S = 5.0

    def __init__(
        self,
        bus: str,
        static_fields: dict[int, str] | None = None,
    ) -> None:
        self._bus = bus
        self._trees: dict[int, SchemaTree | None] = {}
        self._fetching: set[int] = set()
        self._resolved_ids: dict[int, set[int]] = {}
        self._tasks: set[asyncio.Task] = set()
        self._static_fields = static_fields or {}
        self._client: ThingSetCAN | None = None
        self._client_lock = asyncio.Lock()

    def get(self, source: int) -> SchemaTree | None:
        return self._trees.get(source)

    def has_entry(self, source: int) -> bool:
        return source in self._trees or source in self._fetching

    def maybe_start_fetch(self, source: int) -> None:
        if self.has_entry(source):
            return
        self._fetching.add(source)
        self._spawn(self._fetch(source))

    def maybe_resolve_unknowns(self, source: int, ids) -> None:
        tree = self._trees.get(source)
        if tree is None:
            return
        seen = self._resolved_ids.setdefault(source, set())
        to_resolve = [
            i for i in ids
            if isinstance(i, int) and i not in tree.by_id and i not in seen
        ]
        if not to_resolve:
            return
        seen.update(to_resolve)
        self._spawn(self._resolve(source, to_resolve))

    async def close(self) -> None:
        # Cancel outstanding background work first so to_thread calls
        # don't wake up after we've torn the client down.
        for t in list(self._tasks):
            t.cancel()
        for t in list(self._tasks):
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        if self._client is not None:
            await asyncio.to_thread(self._client.disconnect)
            self._client = None

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _ensure_client(self) -> ThingSetCAN:
        if self._client is not None:
            return self._client
        # ThingSetCAN's constructor blocks for up to ~500 ms during
        # address-claim negotiation; offload to a thread.
        self._client = await asyncio.to_thread(ThingSetCAN, self._bus)
        return self._client

    async def _fetch(self, source: int) -> None:
        label = f"0x{source:02X}"
        try:
            async with self._client_lock:
                client = await self._ensure_client()
                tree = await asyncio.wait_for(
                    asyncio.to_thread(client.discover_schema, 0, source),
                    timeout=self.SCHEMA_FETCH_TIMEOUT_S,
                )
            self._merge_static_fields(tree)
            self._trees[source] = tree
            static_note = (
                f" (+{len(self._static_fields)} static field names)"
                if self._static_fields
                else ""
            )
            print(f"    [schema] {label}: {len(tree)} nodes cached{static_note}")
        except Exception as e:
            self._trees[source] = None
            print(
                f"    [schema] {label}: fetch failed "
                f"({e.__class__.__name__}: {e})"
            )
        finally:
            self._fetching.discard(source)

    def _merge_static_fields(self, tree: SchemaTree) -> None:
        for obj_id, name in self._static_fields.items():
            if obj_id in tree.by_id:
                continue
            node = SchemaNode(
                id=obj_id, name=name, type="", access=0, path=name, children=[]
            )
            tree.by_id[obj_id] = node
            tree.by_path.setdefault(name, node)

    async def _resolve(self, source: int, ids: list[int]) -> None:
        label = f"0x{source:02X}"
        id_list = ", ".join(f"{i:#x}" for i in ids)
        try:
            async with self._client_lock:
                client = await self._ensure_client()
                resp = await asyncio.wait_for(
                    asyncio.to_thread(
                        client.fetch, _METADATA_OVERLAY, ids, source
                    ),
                    timeout=self.METADATA_FETCH_TIMEOUT_S,
                )
        except Exception as e:
            print(
                f"    [schema] {label}: metadata fetch failed "
                f"({e.__class__.__name__}) for [{id_list}]"
            )
            return
        tree = self._trees.get(source)
        if tree is None:
            return
        if resp.status_code != ThingSetStatus.CONTENT:
            status = (
                f"{resp.status_code:#x} ({resp.status_string})"
                if resp.status_code is not None
                else "TIMEOUT"
            )
            print(
                f"    [schema] {label}: metadata rejected {status} "
                f"for [{id_list}] — device doesn't expose these at top level"
            )
            return
        resolved = []
        missing = []
        for idx, obj_id in enumerate(ids):
            md = (
                resp.values[idx].value
                if idx < len(resp.values)
                else None
            )
            if not isinstance(md, dict):
                missing.append(obj_id)
                continue
            name = md.get(_METADATA_KEY_NAME, "")
            if not name:
                missing.append(obj_id)
                continue
            node = SchemaNode(
                id=obj_id,
                name=name,
                type=md.get(_METADATA_KEY_TYPE, ""),
                access=md.get(_METADATA_KEY_ACCESS, 0),
                path=name,
                children=[],
            )
            tree.by_id[obj_id] = node
            if name not in tree.by_path:
                tree.by_path[name] = node
            resolved.append(obj_id)
        if resolved:
            names = ", ".join(
                f"{i:#x}->{tree.by_id[i].name}" for i in resolved
            )
            print(f"    [schema] {label}: resolved {len(resolved)} ({names})")
        if missing:
            miss_list = ", ".join(f"{i:#x}" for i in missing)
            print(
                f"    [schema] {label}: no metadata for [{miss_list}] "
                f"(likely record-internal fields)"
            )


async def main(
    bus: str,
    fd: bool,
    source_filter: int | None,
    verbose: bool,
    decorate: bool,
    static_fields: dict[int, str] | None,
) -> None:
    src_str = (
        f", source=0x{source_filter:02X}" if source_filter is not None else ""
    )
    fd_str = "FD" if fd else "classic"
    decorate_str = ", decorate" if decorate else ""
    print(
        f"Listening for ThingSet reports on {bus} ({fd_str}{src_str}"
        f"{decorate_str}) — Ctrl+C to stop\n"
    )
    count = 0
    started = time.perf_counter()
    schema_cache = (
        _SchemaCache(bus=bus, static_fields=static_fields) if decorate else None
    )
    try:
        async with AsyncThingSetCANReportReceiver(bus=bus, fd=fd) as receiver:
            async for (source, _bus_name), report in receiver:
                if source_filter is not None and source != source_filter:
                    continue
                count += 1
                elapsed = time.perf_counter() - started

                if schema_cache is not None:
                    schema_cache.maybe_start_fetch(source)
                    schema_cache.maybe_resolve_unknowns(
                        source, list(report.values.keys())
                    )
                tree = schema_cache.get(source) if schema_cache else None

                shape = "single" if report.subset_id is None else "multi"
                subset = (
                    f"subset={report.subset_id:#x}"
                    if report.subset_id is not None
                    else "subset=none"
                )
                eui = (
                    f" header_eui={report.eui:#018x}"
                    if report.eui is not None
                    else ""
                )
                print(
                    f"#{count:<4}  t={elapsed:6.2f}s  src=0x{source:02X}  "
                    f"{shape}  {subset}{eui}  values={len(report.values)}"
                )

                items = list(report.values.items())
                shown = items if verbose else items[:5]
                for k, v in shown:
                    label = (
                        _decorate_id(k, tree) if isinstance(k, int) else repr(k)
                    )
                    nested = isinstance(v, dict) or (
                        isinstance(v, list)
                        and v
                        and all(isinstance(i, dict) for i in v)
                    )
                    if schema_cache is not None and nested:
                        _print_decorated(
                            "        ", label, v, tree, schema_cache, source
                        )
                    else:
                        vs = _fmt(v)
                        if not verbose and len(vs) > 60:
                            vs = vs[:57] + "..."
                        print(f"        {label} -> {vs}")
                if not verbose and len(items) > 5:
                    print(f"        ... and {len(items) - 5} more")
    finally:
        if schema_cache is not None:
            await schema_cache.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "-i",
        "--bus",
        default="can0",
        help="CAN interface to bind (default: can0; use vcan0 for testing)",
    )
    parser.add_argument(
        "--no-fd",
        action="store_true",
        help="Disable CAN FD mode (use classic CAN with 8-byte frames)",
    )
    parser.add_argument(
        "--source",
        type=lambda s: int(s, 16),
        default=None,
        metavar="HEX",
        help="Only show reports whose source node address matches "
        "(8-bit hex, e.g. 10 or 0x10)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print every value in each report without truncation",
    )
    parser.add_argument(
        "--decorate",
        action="store_true",
        help=(
            "On first sighting of each source node, fetch the device "
            "schema over CAN (ISO-TP) in the background and annotate "
            "printed IDs with their schema path (e.g. `Metadata/rBoard`)"
        ),
    )
    parser.add_argument(
        "--record-fields",
        type=str,
        default=None,
        metavar="PATH",
        help=(
            "Path to a JSON file supplying names for record[] internal "
            "field IDs that the device doesn't expose via the metadata "
            "overlay. Format: {\"0x6451\": \"mCellVoltage\", ...}. "
            "Only used when --decorate is active."
        ),
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG-level logging of every received frame (very noisy)",
    )
    args = parser.parse_args()
    if args.debug:
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s.%(msecs)03d %(name)s %(levelname)s %(message)s",
            datefmt="%H:%M:%S",
        )

    static_fields: dict[int, str] | None = None
    if args.record_fields:
        with open(args.record_fields) as f:
            raw = json.load(f)
        static_fields = {int(k, 16): v for k, v in raw.items()}

    try:
        asyncio.run(
            main(
                bus=args.bus,
                fd=not args.no_fd,
                source_filter=args.source,
                verbose=args.verbose,
                decorate=args.decorate,
                static_fields=static_fields,
            )
        )
    except KeyboardInterrupt:
        print("\nstopped.")
