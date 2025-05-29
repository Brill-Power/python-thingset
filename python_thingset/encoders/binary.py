#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
import json
import struct
from typing import Any, List, Union

import cbor2

from ..response import ThingSetRequest


class ThingSetBinaryEncoder(object):
    PATHS = 0x17
    NULL_BYTE = 0xF6

    def __init__(self):
        pass

    """ Fetch request:
    05                 # FETCH
       F6              # inexplicable null
       02              # CBOR uint: 0x02 (parent ID)
       82              # CBOR array (2 elements)
          18 40        # CBOR uint: 0x40 (object ID)
          18 41        # CBOR uint: 0x41 (object ID)
    """

    def encode_fetch(self, parent_id: int, value_ids: List[Union[int, None]]) -> bytes:
        req = bytearray()
        req.append(ThingSetRequest.FETCH)
        req += cbor2.dumps(parent_id, canonical=True)

        if len(value_ids) == 0:
            req.append(self.NULL_BYTE)
        else:
            req += cbor2.dumps(value_ids, canonical=True)

        return req

    def encode_get(self, value_id: int) -> bytes:
        return bytes([ThingSetRequest.GET] + list(cbor2.dumps(value_id)))

    def encode_exec(self, value_id: int, args: List[Union[Any, None]]) -> bytes:
        p_args = list()

        for a in args:
            if isinstance(a, float):
                p_args.append(self.to_f32(a))
            elif isinstance(a, str):
                if a.lower() == "true" or a.lower() == "false":
                    p_args.append(json.loads(a.lower()))
                else:
                    p_args.append(a)
            else:
                p_args.append(a)

        return bytes(
            [ThingSetRequest.EXEC]
            + list(cbor2.dumps(value_id))
            + list(cbor2.dumps(p_args, canonical=True))
        )

    def encode_update(self, parent_id: int, value_id: int, value: Any) -> bytes:
        if isinstance(value, float):
            value = self.to_f32(value)
        if isinstance(value, str):
            if value.lower() == "true" or value.lower() == "false":
                value = json.loads(value.lower())

        return bytes(
            [ThingSetRequest.UPDATE]
            + list(cbor2.dumps(parent_id))
            + list(cbor2.dumps({value_id: value}, canonical=True))
        )

    def encode_get_path(self, value_id: int) -> bytes:
        req = bytearray([ThingSetRequest.FETCH, self.PATHS])
        req.extend(cbor2.dumps([value_id]))

        return req

    def to_f32(self, value: float) -> float:
        """In Python, all floats are actually doubles. This does not map well to embedded targets where
        there is a clear distinction between the two.

        This function forces the provided floating point argument, value, to its closest 32-bit
        representation so that the resultant encoded (CBOR) value is actually a float (not a double)
        and can be properly parsed by ThingSet running on an embedded target when expecting a float
        """

        return struct.unpack("f", struct.pack("f", value))[0]
