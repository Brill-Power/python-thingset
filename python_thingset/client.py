#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
from abc import ABC, abstractmethod
from typing import Any, List, Union

try:
    from .response import ThingSetResponse
except ImportError:
    from response import ThingSetResponse

class ThingSetClient(ABC):
    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def fetch(self, parent_id: Union[int, str], ids: List[Union[int, str]], node_id: Union[int, None]=None) -> ThingSetResponse:
        pass

    @abstractmethod
    def get(self, value_id: Union[int, str], node_id: Union[int, None]=None) -> ThingSetResponse:
        pass

    @abstractmethod
    def exec(self, value_id: Union[int, str], args: Union[List[Any], None], node_id: Union[int, None]=None) -> ThingSetResponse:
        pass

    @abstractmethod
    def update(self, value_id: Union[int, str], value: Any, node_id: Union[int, None]=None, parent_id: Union[int, None]=None) -> ThingSetResponse:
        pass

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @is_connected.setter
    def is_connected(self, _is_connected: bool) -> None:
        self._is_connected = _is_connected
