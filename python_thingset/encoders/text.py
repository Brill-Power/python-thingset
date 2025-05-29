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
        value = value[0]

        val = None

        if isinstance(value, int):
            val = int(value)

        if isinstance(value, float):
            val = float(value)

        if val is None:
            val = f'\\"{value}\\"'

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
