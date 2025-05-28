#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
from abc import ABC, abstractmethod
from typing import Any, List, Union

from .backends import ThingSetBackend
from .response import ThingSetResponse, ThingSetStatus, ThingSetValue
from .log import get_logger


logger = get_logger()


class ThingSetClient(ABC):
    def fetch(
        self,
        parent_id: Union[int, str],
        ids: List[Union[int, str]],
        node_id: Union[int, None] = None,
        get_paths: bool = True,
    ) -> ThingSetResponse:
        values = []

        self._send(self.encode_fetch(parent_id, ids), node_id)

        msg = self._recv()
        tmp = ThingSetResponse(self.backend, msg)

        if tmp.status_code is not None:
            if tmp.status_code <= ThingSetStatus.CONTENT:
                if len(ids) == 0:
                    if self.backend == ThingSetBackend.Serial:
                        values.append(ThingSetValue(None, tmp.data, parent_id))
                    else:
                        values.append(
                            self._create_value(parent_id, node_id, tmp.data, get_paths)
                        )
                else:
                    for idx, id in enumerate(ids):
                        if self.backend == ThingSetBackend.Serial:
                            values.append(ThingSetValue(None, tmp.data[idx], id))
                        else:
                            values.append(
                                self._create_value(
                                    id, node_id, tmp.data[idx], get_paths
                                )
                            )

        return ThingSetResponse(self.backend, msg, values)

    def get(
        self,
        value_id: Union[int, str],
        node_id: Union[int, None] = None,
        get_paths: bool = True,
    ) -> ThingSetResponse:
        values = []

        self._send(self.encode_get(value_id), node_id)

        msg = self._recv()
        tmp = ThingSetResponse(self.backend, msg)

        if tmp.status_code is not None:
            if tmp.status_code <= ThingSetStatus.CONTENT:
                if self.backend == ThingSetBackend.Serial:
                    values.append(ThingSetValue(None, tmp.data, value_id))
                else:
                    values.append(
                        self._create_value(value_id, node_id, tmp.data, get_paths)
                    )

        return ThingSetResponse(self.backend, msg, values)

    def update(
        self,
        value_id: Union[int, str],
        value: Any,
        node_id: Union[int, None] = None,
        parent_id: Union[int, None] = None,
    ) -> ThingSetResponse:
        self._send(self.encode_update(parent_id, value_id, value), node_id)
        return ThingSetResponse(self.backend, self._recv())

    def exec(
        self,
        value_id: Union[int, str],
        args: Union[List[Any], None],
        node_id: Union[int, None] = None,
    ) -> ThingSetResponse:
        self._send(self.encode_exec(value_id, args), node_id)
        return ThingSetResponse(self.backend, self._recv())

    def _create_value(
        self, value_id: int, node_id: int, value: Any, get_paths: bool
    ) -> ThingSetValue:
        path = None

        if get_paths:
            if value_id == ThingSetValue.ID_ROOT:
                path = "Root"
            else:
                self._send(self.encode_get_path(value_id), node_id)
                tmp = ThingSetResponse(self.backend, self._recv())

                if tmp.data is not None:
                    path = tmp.data[0]
                else:
                    logger.warning("Failed to read value path")

        return ThingSetValue(value_id, value, path)

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def _send(self, data: bytes, node_id: Union[int, None]) -> None:
        pass

    @abstractmethod
    def _recv(self) -> bytes:
        pass

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @is_connected.setter
    def is_connected(self, _is_connected: bool) -> None:
        self._is_connected = _is_connected

    @property
    def backend(self) -> str:
        return self._backend

    @backend.setter
    def backend(self, _backend) -> None:
        self._backend = _backend
