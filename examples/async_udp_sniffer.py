"""Listen for ThingSet UDP reports and print every one that arrives.

ThingSet devices broadcast to 255.255.255.255:9002 on their own
schedule (no subscribe handshake). Bind on the same subnet and you
should see reports land as the device publishes them.

Usage:  python examples/async_udp_sniffer.py [-v | --verbose] [--port 9002]
Stop with Ctrl+C.
"""

import argparse
import asyncio
import json
import time

from python_thingset import (
    AsyncThingSetTCP,
    AsyncThingSetUDPReceiver,
    SchemaNode,
    SchemaTree,
    ThingSetStatus,
)


# Value ID the device uses to publish its EUI — can appear at the top
# level of a report, or nested one level down inside a record[] entry
# (e.g. inside the Modules record, one EUI per module).
_EUI_FIELD_ID = 0x6E


def _format_eui_field(value) -> str:
    """The EUI lands as CBOR bytes, a hex string, or an int depending on firmware."""
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    if isinstance(value, int):
        return f"{value:016x}"
    return str(value)


def _fmt(v) -> str:
    """Render dict keys as uppercase hex (they're ThingSet IDs) but leave
    values and list elements as their plain repr — those are measured
    data, not IDs."""
    if isinstance(v, dict):
        parts = []
        for k, val in v.items():
            key = f"0x{k:X}" if isinstance(k, int) and not isinstance(k, bool) else repr(k)
            parts.append(f"{key}: {_fmt(val)}")
        return "{" + ", ".join(parts) + "}"
    if isinstance(v, list):
        return "[" + ", ".join(_fmt(i) for i in v) + "]"
    return repr(v)


def _collect_euis(values: dict) -> list:
    """Return [(where, raw_value, formatted)] for every 0x6E key at the
    top level or inside record[] entries one level down."""
    found = []
    if _EUI_FIELD_ID in values:
        raw = values[_EUI_FIELD_ID]
        found.append(("top", raw, _format_eui_field(raw)))
    for parent_id, val in values.items():
        if isinstance(val, list):
            for idx, entry in enumerate(val):
                if isinstance(entry, dict) and _EUI_FIELD_ID in entry:
                    raw = entry[_EUI_FIELD_ID]
                    found.append(
                        (
                            f"{parent_id:#06X}[{idx}]",
                            raw,
                            _format_eui_field(raw),
                        )
                    )
    return found


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
    key: "_SchemaKey | None",
) -> None:
    """Recursively print (label, value) with schema decoration.

    - Dict values expand to one line per inner key (each decorated).
    - Lists of dicts expand to one line per entry with its index, then
      each entry recurses as a dict.
    - Scalars and simple lists render on one line.
    Unknown inner IDs get scheduled for metadata resolution so the
    *next* report displays them with names.
    """
    if isinstance(value, dict):
        if schema_cache is not None and key is not None:
            schema_cache.maybe_resolve_unknowns(key, value.keys())
        print(f"{indent}{label}:")
        for k, v in value.items():
            inner_label = (
                _decorate_id(k, tree) if isinstance(k, int) else repr(k)
            )
            _print_decorated(indent + "    ", inner_label, v, tree, schema_cache, key)
        return

    if (
        isinstance(value, list)
        and value
        and all(isinstance(i, dict) for i in value)
    ):
        print(f"{indent}{label}: (list of {len(value)})")
        for idx, entry in enumerate(value):
            _print_decorated(
                indent + "    ", f"[{idx}]", entry, tree, schema_cache, key
            )
        return

    print(f"{indent}{label} -> {_fmt(value)}")


def _display_items(values: dict, filter_eui: int | None) -> list:
    """Return [(id, label, value)] triples for printing. When filter_eui
    is set, any record[] that has EUI-keyed entries is narrowed to just
    the ones matching (original indices preserved in the label). The
    raw ``id`` is returned alongside so the caller can look it up in a
    schema for decoration."""
    out = []
    for k, v in values.items():
        if filter_eui is not None and isinstance(v, list):
            has_eui = any(
                isinstance(e, dict) and _EUI_FIELD_ID in e for e in v
            )
            if has_eui:
                for i, entry in enumerate(v):
                    if (
                        isinstance(entry, dict)
                        and _eui_as_int(entry.get(_EUI_FIELD_ID)) == filter_eui
                    ):
                        out.append((k, f"{k:#06X}[{i}]", entry))
                continue
        out.append((k, f"{k:#06X}", v))
    return out


_METADATA_OVERLAY = 0x19
_METADATA_KEY_NAME = 26
_METADATA_KEY_TYPE = 27
_METADATA_KEY_ACCESS = 28

# Schema cache key. `eui` is None for 0x1F direct reports; for 0x1E
# enhanced reports it's the originating module's EUI-64, used to fetch
# that module's schema *through* the reporting gateway via a forward-
# wrapped TCP connection.
_SchemaKey = tuple[str, "int | None"]


def _key_label(key: _SchemaKey) -> str:
    ip, eui = key
    if eui is None:
        return ip
    return f"{ip} via EUI {eui:016x}"


class _SchemaCache:
    """Lazily fetches the schema for each newly-seen (IP, EUI) pair.

    Most reports have no EUI (plain 0x1F) — they're keyed on IP alone
    and the fetch talks directly to the reporting device. Enhanced
    (0x1E) reports carry the originating module's EUI; those get
    keyed on (IP, EUI) and the fetch uses a ``target_eui`` forward
    envelope so the gateway routes the schema walk to the right
    module. Without this distinction the sniffer would decorate a
    gateway-republished module report using the *gateway's* schema,
    mis-labelling everything.
    """

    SCHEMA_FETCH_TIMEOUT_S = 10.0
    METADATA_FETCH_TIMEOUT_S = 2.0

    def __init__(self, static_fields: dict[int, str] | None = None) -> None:
        self._trees: dict[_SchemaKey, SchemaTree | None] = {}
        self._fetching: set[_SchemaKey] = set()
        self._resolved_ids: dict[_SchemaKey, set[int]] = {}
        self._tasks: set[asyncio.Task] = set()
        self._static_fields = static_fields or {}

    def get(self, key: _SchemaKey) -> SchemaTree | None:
        return self._trees.get(key)

    def has_entry(self, key: _SchemaKey) -> bool:
        return key in self._trees or key in self._fetching

    def maybe_start_fetch(self, key: _SchemaKey) -> None:
        if self.has_entry(key):
            return
        self._fetching.add(key)
        self._spawn(self._fetch(key))

    def maybe_resolve_unknowns(self, key: _SchemaKey, ids) -> None:
        tree = self._trees.get(key)
        if tree is None:
            return  # no schema yet or fetch failed
        seen = self._resolved_ids.setdefault(key, set())
        to_resolve = [
            i for i in ids
            if isinstance(i, int) and i not in tree.by_id and i not in seen
        ]
        if not to_resolve:
            return
        seen.update(to_resolve)
        self._spawn(self._resolve(key, to_resolve))

    def _spawn(self, coro) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _fetch(self, key: _SchemaKey) -> None:
        ip, eui = key
        label = _key_label(key)
        try:
            tree = await asyncio.wait_for(
                self._discover(ip, eui), timeout=self.SCHEMA_FETCH_TIMEOUT_S
            )
            self._merge_static_fields(tree)
            self._trees[key] = tree
            static_note = (
                f" (+{len(self._static_fields)} static field names)"
                if self._static_fields
                else ""
            )
            print(f"    [schema] {label}: {len(tree)} nodes cached{static_note}")
        except Exception as e:
            self._trees[key] = None
            print(f"    [schema] {label}: fetch failed ({e.__class__.__name__}: {e})")
        finally:
            self._fetching.discard(key)

    def _merge_static_fields(self, tree: SchemaTree) -> None:
        for obj_id, name in self._static_fields.items():
            if obj_id in tree.by_id:
                continue
            node = SchemaNode(
                id=obj_id, name=name, type="", access=0, path=name, children=[]
            )
            tree.by_id[obj_id] = node
            tree.by_path.setdefault(name, node)

    async def _resolve(self, key: _SchemaKey, ids: list[int]) -> None:
        ip, eui = key
        label = _key_label(key)
        id_list = ", ".join(f"{i:#x}" for i in ids)
        try:
            resp = await asyncio.wait_for(
                self._fetch_metadata(ip, eui, ids),
                timeout=self.METADATA_FETCH_TIMEOUT_S,
            )
        except Exception as e:
            print(
                f"    [schema] {label}: metadata fetch failed "
                f"({e.__class__.__name__}) for [{id_list}]"
            )
            return
        tree = self._trees.get(key)
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

    @staticmethod
    async def _discover(ip: str, target_eui: int | None) -> SchemaTree:
        async with AsyncThingSetTCP(ip, target_eui=target_eui) as client:
            return await client.discover_schema()

    @staticmethod
    async def _fetch_metadata(ip: str, target_eui: int | None, ids: list[int]):
        async with AsyncThingSetTCP(ip, target_eui=target_eui) as client:
            return await client.fetch(_METADATA_OVERLAY, ids)


def _eui_as_int(value) -> int | None:
    """Best-effort normalisation of the various wire shapes an EUI can
    take (int, hex string, or raw big-endian bytes) into a single int
    for comparison."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, (bytes, bytearray)):
        return int.from_bytes(value, "big")
    if isinstance(value, str):
        try:
            return int(value, 16)
        except ValueError:
            return None
    return None


def _report_matches_eui(report, target: int) -> bool:
    """True if any of {header EUI, top-level 0x6E, any record[].*.0x6E}
    equals ``target``."""
    if _eui_as_int(report.eui) == target:
        return True
    if _eui_as_int(report.values.get(_EUI_FIELD_ID)) == target:
        return True
    for val in report.values.values():
        if isinstance(val, list):
            for entry in val:
                if (
                    isinstance(entry, dict)
                    and _eui_as_int(entry.get(_EUI_FIELD_ID)) == target
                ):
                    return True
    return False


async def main(
    port: int,
    verbose: bool,
    filter_eui: int | None,
    decorate: bool,
    static_fields: dict[int, str] | None,
) -> None:
    mode = "verbose" if verbose else "summary"
    eui_str = f", filter EUI={filter_eui:016x}" if filter_eui is not None else ""
    decorate_str = ", decorate" if decorate else ""
    print(
        f"Listening for ThingSet reports on 0.0.0.0:{port} "
        f"({mode}{eui_str}{decorate_str}) — Ctrl+C to stop\n"
    )
    count = 0
    started = time.perf_counter()
    schema_cache = _SchemaCache(static_fields=static_fields) if decorate else None
    async with AsyncThingSetUDPReceiver(port=port) as receiver:
        async for addr, report in receiver:
            if filter_eui is not None and not _report_matches_eui(report, filter_eui):
                continue
            count += 1
            elapsed = time.perf_counter() - started
            # Key on (ip, eui) so that gateway-republished reports
            # (0x1E with module EUI) fetch the module's own schema
            # via a target_eui-wrapped connection, not the gateway's.
            cache_key: _SchemaKey = (addr[0], report.eui)
            if schema_cache is not None:
                schema_cache.maybe_start_fetch(cache_key)
                schema_cache.maybe_resolve_unknowns(
                    cache_key, list(report.values.keys())
                )
            tree = (
                schema_cache.get(cache_key) if schema_cache is not None else None
            )

            # Header-level EUI (only present in 0x1E enhanced reports)
            header_eui = (
                f" header_eui={report.eui:#018x}" if report.eui is not None else ""
            )

            print(
                f"#{count:<4}  t={elapsed:6.2f}s  from {addr[0]}:{addr[1]}  "
                f"subset={report.subset_id:#x}{header_eui}  "
                f"values={len(report.values)}"
            )
            for where, raw, fmt in _collect_euis(report.values):
                if filter_eui is None or _eui_as_int(raw) == filter_eui:
                    print(f"        EUI @ {where}: {fmt}")

            items = _display_items(report.values, filter_eui)
            shown = items if verbose else items[:5]
            for obj_id, label, v in shown:
                if tree is not None:
                    node = tree.by_id.get(obj_id)
                    if node is not None:
                        label += f"  {node.path}"
                nested = isinstance(v, dict) or (
                    isinstance(v, list)
                    and v
                    and all(isinstance(i, dict) for i in v)
                )
                if schema_cache is not None and nested:
                    _print_decorated(
                        "        ", label, v, tree, schema_cache, cache_key
                    )
                else:
                    vs = _fmt(v)
                    if not verbose and len(vs) > 60:
                        vs = vs[:57] + "..."
                    print(f"        {label} -> {vs}")
            if not verbose and len(items) > 5:
                print(f"        ... and {len(items) - 5} more")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--port", type=int, default=9002, help="UDP port to bind (default: 9002)"
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print all values in each report without truncation",
    )
    parser.add_argument(
        "--filter-eui",
        type=lambda s: int(s, 16),
        default=None,
        metavar="HEX",
        help=(
            "Only print reports whose header EUI, top-level 0x6E, or any "
            "record[].0x6E matches this 64-bit hex value (e.g. "
            "badb1b0000000001 or 0xbadb1b0000000001)"
        ),
    )
    parser.add_argument(
        "--decorate",
        action="store_true",
        help=(
            "On first sighting of each source IP, fetch the device schema "
            "over TCP (port 9001) in the background and annotate printed "
            "IDs with their schema path (e.g. `Metadata/rBoard`)"
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
    args = parser.parse_args()

    static_fields: dict[int, str] | None = None
    if args.record_fields:
        with open(args.record_fields) as f:
            raw = json.load(f)
        static_fields = {int(k, 16): v for k, v in raw.items()}

    try:
        asyncio.run(
            main(
                args.port,
                args.verbose,
                args.filter_eui,
                args.decorate,
                static_fields,
            )
        )
    except KeyboardInterrupt:
        print("\nstopped.")
