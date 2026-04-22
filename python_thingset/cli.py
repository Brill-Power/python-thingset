#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
#!/usr/bin/env python3

import argparse
from time import sleep
from typing import Union

from ._protocol import WireFormat
from .client import ThingSetClient
from .transport import ThingSetCAN, ThingSetSerial, ThingSetTCP


def process_args(args: list) -> list:
    processed_args = list()

    # convert '36' to int, '24.0' to float, leave 'some-text' as str
    for a in args:
        try:
            processed_args.append(int(a))
            continue
        except ValueError:
            pass

        try:
            processed_args.append(float(a))
            continue
        except ValueError:
            pass

        processed_args.append(a)

    return processed_args


def get_schema(
    ts: ThingSetClient,
    object_id: Union[int, str],
    node_id: Union[int, None] = None,
):
    """Recursively print every child identifier under ``object_id``."""
    if ts.wire_format is WireFormat.BINARY:
        _schema_binary(ts, object_id, node_id)
    else:
        _schema_text(ts, object_id, node_id)


def _schema_binary(
    ts: ThingSetClient,
    object_id: int,
    node_id: Union[int, None],
) -> None:
    tree = ts.discover_schema(root_id=object_id, node_id=node_id)
    for node in tree:
        print(node)


def _schema_text(
    ts: ThingSetClient,
    object_id: str,
    node_id: Union[int, None],
) -> None:
    """Text-transport schema walk — path-concatenated recursion."""
    response = ts.fetch(object_id, [], node_id)
    if not response.values:
        return
    for val in response.values:
        children = val.value if isinstance(val.value, list) else []
        for child in children:
            display = child if object_id == "" else f"{object_id}/{child}"
            print(display)
            # avoid <wrn> shell_uart: RX ring buffer full on serial targets
            sleep(0.005)
            _schema_text(ts, display, node_id)


def setup_args() -> argparse.Namespace:
    parent_parser = argparse.ArgumentParser(add_help=False)

    arg_parser = argparse.ArgumentParser()

    group = parent_parser.add_mutually_exclusive_group(required=True)

    group.add_argument(
        "-c",
        "--can-bus",
        help="Specify which CAN bus to use (example: vcan0)",
        nargs="?",
        type=str,
    )
    parent_parser.add_argument(
        "-t",
        "--target-address",
        help="Specify target device node address (example: 2F)",
    )

    group.add_argument(
        "-p",
        "--port",
        help="Specify which serial port to use (example: /dev/pts/5)",
        nargs="?",
        type=str,
    )
    parent_parser.add_argument(
        "-r",
        "--baud-rate",
        help="Specify serial baud rate (example: 115200)",
        nargs="?",
        default=115200,
        type=int,
    )

    group.add_argument(
        "-i",
        "--ip",
        help="Specify which IPv4 address to connect to (example 192.0.2.1)",
    )
    parent_parser.add_argument(
        "-e",
        "--target-eui",
        help=(
            "With -i/--ip only: target a CAN-side module through the IP "
            "gateway at --ip. 16-char lowercase hex EUI-64 (with or "
            "without 0x prefix). Each request is wrapped in a forward "
            "envelope so the gateway routes it to the module."
        ),
    )

    subparsers = arg_parser.add_subparsers(
        dest="method",
        required=True,
        help="ThingSet function execute (one of: exec, fetch, get, update, schema)",
    )

    get_parser = subparsers.add_parser(
        "get", help="Perform ThingSet get request", parents=[parent_parser]
    )
    get_parser.add_argument(
        "id", help="Path or ID of value to retreive (example Build/rBoard, or F03)"
    )

    fetch_parser = subparsers.add_parser(
        "fetch", parents=[parent_parser], help="Perform ThingSet fetch request"
    )
    fetch_parser.add_argument(
        "parent_id",
        help="Path or ID for parent node of value(s) to retrieve (example: Build)",
    )
    fetch_parser.add_argument(
        "value_ids",
        help="Paths or IDs (space delimited) for values to retrieve (example: rBoard "
        "rBuildUser or F03 F02 or can be empty)",
        nargs="*",
    )

    exec_parser = subparsers.add_parser(
        "exec", parents=[parent_parser], help="Perform ThingSet exec request"
    )
    exec_parser.add_argument(
        "value_id",
        help="Path or ID of function to execute (example: Module/xSaveNVM or 5F)",
    )
    exec_parser.add_argument(
        "values",
        help="Arguments to function (space delimited) (example: some-text or 24.6 "
        "or can be empty) (numeric values should be decimal)",
        nargs="*",
    )

    update_parser = subparsers.add_parser(
        "update", parents=[parent_parser], help="Perform ThingSet update request"
    )
    update_parser.add_argument(
        "update_args",
        help="If using -p/--port: path value - Path of value to update (example: "
        "Module/sCanMaxLogLevel 3) (value is decimal if numeric). If using -c/--can-bus: "
        "parent_id value_id value - (example: 0F F02 MyValue)",
        nargs="*",
    )

    schema_parser = subparsers.add_parser(
        "schema", parents=[parent_parser], help="Get ThingSet schema for device"
    )
    schema_parser.add_argument(
        "root_id",
        help="Path or ID of node at which to start schema fetch (example: Module or 0F) "
        '("" or 00 for root path) (leave empty to fetch full schema)',
        nargs="?",
        default="00",
    )

    args = arg_parser.parse_args()

    # post-parser validation
    if args.target_eui and not args.ip:
        arg_parser.error(
            "-e/--target-eui is only valid with -i/--ip (gateway forwarding)"
        )

    if args.can_bus:
        if not args.target_address:
            arg_parser.error("-t/--target-address is required with -c/--can_bus")

        if args.method == "update":
            if len(args.update_args) != 3:
                arg_parser.error(
                    "When using update with -c/--can-bus you must suply a "
                    "parent_id, value_id and value "
                    "(example: thingset update f f03 MyValue -c vcan0"
                )
            else:
                args.parent_id = args.update_args[0]
                args.value_id = args.update_args[1]
                args.value = [args.update_args[2]]
    elif args.port:
        if args.method == "update":
            if len(args.update_args) != 2:
                arg_parser.error(
                    "When using update with -p/--port you must suply a path "
                    "and a value (example: "
                    "thingset update Module/sCanMaxLogLevel 4 -p /dev/pts/5"
                )
            else:
                args.parent_id = args.update_args[0]
                args.value = [args.update_args[1]]
    elif args.ip:
        if args.method == "update":
            if len(args.update_args) != 3:
                arg_parser.error(
                    "When using update with -i/--ip you must suply a "
                    "parent_id, value_id and value "
                    "(example: thingset update f f03 MyValue -i 192.0.2.1"
                )
            else:
                args.parent_id = args.update_args[0]
                args.value_id = args.update_args[1]
                args.value = [args.update_args[2]]

    if not (args.can_bus or args.port or args.ip):
        arg_parser.error("One of -c/--can_bus, -i/--ip or -p/--port is required")

    return args


def _make_client(args: argparse.Namespace) -> ThingSetClient:
    if args.can_bus:
        return ThingSetCAN(args.can_bus)
    if args.port:
        return ThingSetSerial(args.port, args.baud_rate)
    target_eui = int(args.target_eui, 16) if args.target_eui else None
    return ThingSetTCP(args.ip, target_eui=target_eui)


def _dispatch(ts: ThingSetClient, args: argparse.Namespace):
    is_serial = bool(args.port)
    is_tcp = bool(args.ip)

    match args.method:
        case "get":
            if is_serial:
                return ts.get(args.id)
            if is_tcp:
                return ts.get(int(args.id, 16))
            return ts.get(int(args.id, 16), int(args.target_address, 16))

        case "fetch":
            if is_serial:
                return ts.fetch(args.parent_id, args.value_ids)
            if is_tcp:
                return ts.fetch(
                    int(args.parent_id, 16),
                    [int(i, 16) for i in args.value_ids],
                )
            return ts.fetch(
                int(args.parent_id, 16),
                [int(i, 16) for i in args.value_ids],
                int(args.target_address, 16),
            )

        case "exec":
            p_args = process_args(args.values)
            if is_serial:
                return ts.exec(args.value_id, p_args)
            if is_tcp:
                return ts.exec(int(args.value_id, 16), p_args)
            return ts.exec(
                int(args.value_id, 16),
                p_args,
                node_id=int(args.target_address, 16),
            )

        case "update":
            if is_serial:
                return ts.update(args.parent_id, args.value)
            p_args = process_args(args.value)
            if is_tcp:
                return ts.update(
                    int(args.value_id, 16),
                    p_args[0],
                    parent_id=int(args.parent_id, 16),
                )
            return ts.update(
                int(args.value_id, 16),
                p_args[0],
                int(args.target_address, 16),
                int(args.parent_id, 16),
            )

        case "schema":
            if is_serial:
                root = "" if args.root_id == "00" else args.root_id
                get_schema(ts, root)
            elif is_tcp:
                get_schema(ts, int(args.root_id, 16))
            else:
                get_schema(ts, int(args.root_id, 16), int(args.target_address, 16))
            return None

    return None


_METADATA_OVERLAY_ID = 0x19
_METADATA_NAME_KEY = 26
_METADATA_TYPE_KEY = 27


def _fmt(v, names: dict = None) -> str:
    """Render dict keys as uppercase hex (they're ThingSet IDs by
    convention) but leave values and list elements as their plain repr
    — those are data, not IDs. When ``names`` is given, a dict key (or
    a list element that is entirely a set of known IDs) gets the name
    appended after the hex."""
    names = names or {}
    if isinstance(v, dict):
        parts = []
        for k, val in v.items():
            if isinstance(k, int) and not isinstance(k, bool):
                key = f"0x{k:X}"
                info = names.get(k)
                if info and info[0]:
                    key += f" {info[0]}"
            else:
                key = repr(k)
            parts.append(f"{key}: {_fmt(val, names)}")
        return "{" + ", ".join(parts) + "}"
    if isinstance(v, list):
        # A list whose elements are all known IDs (resolved via
        # metadata) is a children-fetch result — render as hex IDs
        # with names. Otherwise leave as plain repr (firmware-version
        # tuples and similar data arrays stay decimal).
        if v and all(
            isinstance(x, int) and not isinstance(x, bool) and x in names
            for x in v
        ):
            parts = []
            for i in v:
                label = f"0x{i:X}"
                if names[i][0]:
                    label += f" {names[i][0]}"
                parts.append(label)
            return "[" + ", ".join(parts) + "]"
        return "[" + ", ".join(_fmt(i, names) for i in v) + "]"
    return repr(v)


def _resolve_names(
    ts: ThingSetClient, ids: list, node_id: Union[int, None] = None
) -> dict:
    """Best-effort ``fetch(0x19, [ids])`` → ``{id: (name, type)}``.

    Only runs for binary wire formats. ``node_id`` is required for CAN
    (to build the ISO-TP request address) and ignored by TCP. Silently
    returns {} on any failure so the caller falls back to raw IDs.
    """
    if ts.wire_format is not WireFormat.BINARY or not ids:
        return {}
    try:
        resp = ts.fetch(_METADATA_OVERLAY_ID, ids, node_id)
    except Exception:
        return {}
    if resp is None or resp.status_code is None or not resp.values:
        return {}
    out = {}
    for idx, obj_id in enumerate(ids):
        if idx >= len(resp.values):
            break
        md = resp.values[idx].value
        if isinstance(md, dict):
            name = md.get(_METADATA_NAME_KEY, "")
            type_str = md.get(_METADATA_TYPE_KEY, "")
            out[obj_id] = (name, type_str)
    return out


_NO_RESPONSE_HINTS = {
    "get_root": (
        "(no response — `get 0` returns the whole device which typically "
        "exceeds the 4095-byte wire limit. Try `fetch 0` for root's child "
        "IDs, or `get <id>` for a specific branch.)"
    ),
    "fetch_with_ids": (
        "(no response — this firmware doesn't accept `fetch <parent> "
        "<ids>` outside the 0x19 metadata overlay. Try `fetch <parent>` "
        "for the child-ID list, or `get <parent>` for the whole group.)"
    ),
}


def _print_response(
    ts: ThingSetClient,
    response,
    op_hint: str = None,
    node_id: Union[int, None] = None,
) -> None:
    if response is None:
        return

    if response.status_code is None:
        print(_NO_RESPONSE_HINTS.get(op_hint, "(no response)"))
        return

    status_line = f"0x{response.status_code:02X} ({response.status_string})"

    if not response.values:
        print(status_line)
        return

    # Collect every int that might be a ThingSet ID we want to name:
    # top-level value IDs, inner dict keys (group contents), and int
    # entries in list values (children-fetch results). The metadata
    # overlay returns results per-id; unresolvable ones simply don't
    # appear in the names map, so decoration self-gates.
    all_ids: set = set()
    for v in response.values:
        if isinstance(v.id, int):
            all_ids.add(v.id)
        if isinstance(v.value, dict):
            for k in v.value:
                if isinstance(k, int) and not isinstance(k, bool):
                    all_ids.add(k)
        elif isinstance(v.value, list) and v.value and all(
            isinstance(x, int) and not isinstance(x, bool) for x in v.value
        ):
            all_ids.update(v.value)
    names = (
        _resolve_names(ts, sorted(all_ids), node_id) if all_ids else {}
    )

    print(status_line)
    for v in response.values:
        if isinstance(v.id, int) and v.id in names:
            name, type_str = names[v.id]
            label = f"0x{v.id:04X}"
            if name:
                label += f"  {name}"
            if type_str:
                label += f"  ({type_str})"
            print(f"  {label}: {_fmt(v.value, names)}")
        else:
            print(f"  {v}")


def _op_hint(args: argparse.Namespace) -> Union[str, None]:
    """Classify the invocation so a helpful hint can accompany a
    silent-timeout response."""
    if args.method == "get":
        try:
            if int(args.id, 16) == 0:
                return "get_root"
        except (AttributeError, ValueError, TypeError):
            pass
    elif args.method == "fetch" and getattr(args, "value_ids", None):
        return "fetch_with_ids"
    return None


def _node_id_for(args: argparse.Namespace) -> Union[int, None]:
    """CAN needs the target node address for every RPC, including the
    post-response metadata lookup. TCP/serial ignore this argument."""
    if args.can_bus and args.target_address:
        return int(args.target_address, 16)
    return None


def run_cli():
    args = setup_args()
    with _make_client(args) as ts:
        response = _dispatch(ts, args)
        if response is not None:
            _print_response(
                ts,
                response,
                op_hint=_op_hint(args),
                node_id=_node_id_for(args),
            )


if __name__ == "__main__":
    run_cli()
