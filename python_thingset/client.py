#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
from abc import ABC, abstractmethod
from typing import Any, List, Union

from ._protocol import ParsedResponse, ThingSetProtocol, WireFormat
from .log import get_logger
from .response import ThingSetResponse, ThingSetStatus, ThingSetValue


logger = get_logger()


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
        get_paths: bool = False,
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
                values.append(
                    self._build_value(parent_id, node_id, parsed.data, get_paths)
                )
            else:
                for idx, vid in enumerate(ids):
                    values.append(
                        self._build_value(vid, node_id, parsed.data[idx], get_paths)
                    )

        return self._to_response(parsed, values)

    def get(
        self,
        value_id: Union[int, str],
        node_id: Union[int, None] = None,
        get_paths: bool = False,
    ) -> ThingSetResponse:
        self._send(self._protocol.encode_get(value_id), node_id)
        parsed = self._recv()

        values: List[ThingSetValue] = []
        if (
            parsed is not None
            and parsed.status_code is not None
            and parsed.status_code <= ThingSetStatus.CONTENT
        ):
            values.append(self._build_value(value_id, node_id, parsed.data, get_paths))

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

    def _build_value(
        self,
        value_id: Union[int, str],
        node_id: Union[int, None],
        value: Any,
        get_paths: bool,
    ) -> ThingSetValue:
        if self.wire_format is WireFormat.TEXT:
            # Text (serial) addresses values by path; the "id" IS the path
            return ThingSetValue(None, value, value_id)

        path = None
        if get_paths:
            if value_id == ThingSetValue.ID_ROOT:
                path = "Root"
            else:
                self._send(self._protocol.encode_get_path(value_id), node_id)
                parsed = self._recv()
                if parsed is not None and parsed.data is not None:
                    path = parsed.data[0]
                else:
                    logger.warning("Failed to read value path")

        return ThingSetValue(value_id, value, path)

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
