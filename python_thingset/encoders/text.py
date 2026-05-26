#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
from typing import Any, List, Union


class ThingSetTextEncoder(object):
    def __init__(self):
        pass

    def encode_fetch(self, parent_id: str, ids: List[str]) -> bytes:
        children = "null"

        if len(ids) > 0:
            children = "["

            for i in ids:
                children += f'\\"{i}\\",'

            children += "]"

        return f"thingset ?{parent_id} {children}\n".encode()

    def encode_get(self, value_id: str) -> bytes:
        return f"thingset ?{value_id}\n".encode()

    def encode_exec(self, value_id: str, args: List[Union[Any, None]]) -> bytes:
        """properly format strings for transmission, add args to stringified list"""
        processed_args = "["

        """ leave numeric values as is, surround strings with escape chars """
        for a in args:
            if isinstance(a, int):
                processed_args += f"{a},"
                continue

            if isinstance(a, float):
                processed_args += f"{a},"
                continue

            processed_args += f'\\"{a}\\",'

        processed_args += "]"

        return f"""thingset !{value_id} {processed_args}\n""".encode()

    def encode_update(self, parent_id: None, value_id: str, value: Any) -> bytes:
        """properly format strings for transmission, add args to stringified list"""
        # Legacy CLI convention: scalars are wrapped in a single-element list
        # before being passed in. Unwrap so the wire format stays scalar.
        # Multi-element or nested lists fall through and become JSON arrays.
        if (
            isinstance(value, list)
            and len(value) == 1
            and not isinstance(value[0], list)
        ):
            value = value[0]

        val = self._encode_value(value)

        path = " "
        value_name = None

        path_split = value_id.split("/")

        if len(path_split) > 1:
            path = "/".join(path_split[:-1]) + " "
            value_name = path_split[-1]
        else:
            value_name = path_split[0]

        value_path = f'{path}£\\"{value_name}\\":{val}$'
        value_path = value_path.replace("£", "{").replace("$", "}")

        return f"""thingset ={value_path}\n""".encode()

    def _encode_value(self, value: Any) -> str:
        """Render a single value for the text wire format."""
        # bool is a subclass of int — check it first
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, list):
            return "[" + ",".join(self._encode_value(v) for v in value) + "]"
        if isinstance(value, (int, float)):
            return str(value)
        return f'\\"{value}\\"'
