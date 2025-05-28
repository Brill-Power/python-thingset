#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
import threading
from abc import ABC, abstractmethod
from typing import Union

import can


class ThingSetBackend(ABC):
    CAN: str = "can"
    Serial: str = "serial"
    Socket: str = "socket"

    def __init__(self):
        self._running = False
        self._thread = None

    def start_receiving(self) -> None:
        if not self._running:
            self._running = True
            self._thread = threading.Thread(target=self._receive_loop)
            self._thread.start()

    def stop_receiving(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join()

    def _receive_loop(self) -> None:
        while self._running:
            message = self.receive()
            if message:
                self._handle_message(message)

    @abstractmethod
    def _handle_message(self, message: Union[bytes, can.Message]) -> None:
        """Handle an incoming message (customize this as needed)."""
        pass

    @abstractmethod
    def connect(self) -> None:
        """perform backend initialisation"""
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """perform backend teardown"""
        pass

    @abstractmethod
    def send(self, _data: Union[bytes, can.Message]) -> None:
        """send data"""
        pass

    @abstractmethod
    def receive(self) -> Union[bytes, can.Message]:
        """receive data"""
        pass
