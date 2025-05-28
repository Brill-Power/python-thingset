#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
#!/usr/bin/env python3

import argparse

from time import sleep
from typing import Union

from .backends import ThingSetBackend
from .thingset import ThingSet


def process_args(args: list) -> list:
    processed_args = list()

    """ convert '36' to int, '24.0' to float and leave 'some-text' as str """
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
    ts: ThingSet, object_id: Union[int, str], node_id: Union[int, None] = None
):
    if node_id is not None:
        child_ids = ts.fetch(object_id, [], node_id)

        for val in child_ids.values:
            print(val)

            for v in val.value:
                get_schema(ts, v, node_id)
    else:
        child_ids = ts.fetch("" if object_id == "00" else object_id, [])

        for val in child_ids.values:
            for v in val.value:
                print(f"{object_id if object_id != '00' else ''}/{v}")

                """ avoid <wrn> shell_uart: RX ring buffer full """
                sleep(0.005)

                if object_id != "00":
                    get_schema(ts, f"{object_id}/{v}")
                else:
                    get_schema(ts, v)


def setup_args() -> argparse.Namespace:
    parent_parser = argparse.ArgumentParser(add_help=False)

    arg_parser = argparse.ArgumentParser()

    group = parent_parser.add_mutually_exclusive_group(required=True)

    """ CAN options """
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

    """ Serial options """
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

    """ Socket options """
    group.add_argument(
        "-i",
        "--ip",
        help="Specify which IPv4 address to connect to (example 192.0.2.1)",
    )

    """ Functions """
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

    """ post-parser validation """
    if args.can_bus:
        if not args.target_address:
            arg_parser.error("-t/--target-address is required with -c/--can_bus")

        if args.method == "update":
            if len(args.update_args) != 3:
                arg_parser.error(
                    "When using update with -c/--can-bus you must suply a parent_id, value_id and value "
                    "(example: thingset update f f03 MyValue -c vcan0"
                )
            else:
                args.parent_id = args.update_args[0]
                args.value_id = args.update_args[1]
                args.value = [args.update_args[2]]

        args.backend = ThingSetBackend.CAN
    elif args.port:
        if args.method == "update":
            if len(args.update_args) != 2:
                arg_parser.error(
                    "When using update with -p/--port you must suply a path and a value (example: "
                    "thingset update Module/sCanMaxLogLevel 4 -p /dev/pts/5"
                )
            else:
                args.parent_id = args.update_args[0]
                args.value = [args.update_args[1]]

        args.backend = ThingSetBackend.Serial
    elif args.ip:
        args.backend = ThingSetBackend.Socket

        if args.method == "update":
            if len(args.update_args) != 3:
                arg_parser.error(
                    "When using update with -i/--ip you must suply a parent_id, value_id and value "
                    "(example: thingset update f f03 MyValue -i 192.0.2.1"
                )
            else:
                args.parent_id = args.update_args[0]
                args.value_id = args.update_args[1]
                args.value = [args.update_args[2]]

    if not (args.can_bus or args.port or args.ip):
        arg_parser.error("One of -c/--can_bus, -i/--ip or -p/--port is required")

    return args


def run_cli():
    args = setup_args()

    with ThingSet(can_bus=args.can_bus, backend=args.backend, port=args.port) as ts:
        response = None

        match args.method:
            case "get":
                if args.backend.lower() == "serial":
                    response = ts.get(args.id)
                elif args.backend.lower() == "socket":
                    response = ts.get(int(args.id, 16))
                else:
                    response = ts.get(int(args.id, 16), int(args.target_address, 16))
            case "fetch":
                if args.backend.lower() == "serial":
                    response = ts.fetch(args.parent_id, args.value_ids)
                elif args.backend.lower() == "socket":
                    response = ts.fetch(
                        int(args.parent_id, 16), [int(i, 16) for i in args.value_ids]
                    )
                else:
                    response = ts.fetch(
                        int(args.parent_id, 16),
                        [int(i, 16) for i in args.value_ids],
                        int(args.target_address, 16),
                    )
            case "exec":
                p_args = process_args(args.values)

                if args.backend.lower() == "serial":
                    response = ts.exec(args.value_id, p_args)
                elif args.backend.lower() == "socket":
                    response = ts.exec(int(args.value_id, 16), p_args)
                else:
                    response = ts.exec(
                        int(args.value_id, 16),
                        p_args,
                        node_id=int(args.target_address, 16),
                    )
            case "update":
                if args.backend.lower() == "serial":
                    response = ts.update(args.parent_id, args.value)
                elif args.backend.lower() == "socket":
                    p_args = process_args(args.value)
                    response = ts.update(
                        int(args.value_id, 16),
                        p_args[0],
                        parent_id=int(args.parent_id, 16),
                    )
                else:
                    p_args = process_args(args.value)
                    response = ts.update(
                        int(args.value_id, 16),
                        p_args[0],
                        int(args.target_address, 16),
                        int(args.parent_id, 16),
                    )
            case "schema":
                if args.backend.lower() == "serial":
                    get_schema(ts, args.root_id)
                elif args.backend.lower() == "socket":
                    get_schema(ts, int(args.root_id, 16))
                else:
                    get_schema(ts, int(args.root_id, 16), int(args.target_address, 16))
            case _:
                pass

    if response is not None:
        print(response)

        if response.values is not None:
            for v in response.values:
                print(v)


if __name__ == "__main__":
    run_cli()
