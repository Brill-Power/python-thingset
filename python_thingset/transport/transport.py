#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
import threading
from abc import ABC, abstractmethod
from typing import Any


class ThingSetTransport(ABC):
    """Abstract base class for ThingSet transport drivers.

    Owns a background receive thread that polls receive() and dispatches
    completed messages via _handle_message(). Subclasses implement the
    wire-specific I/O and the framing logic in _handle_message.
    """

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
    def _handle_message(self, message: Any) -> None:
        pass

    @abstractmethod
    def connect(self) -> None:
        pass

    @abstractmethod
    def disconnect(self) -> None:
        pass

    @abstractmethod
    def send(self, data: Any) -> None:
        pass

    @abstractmethod
    def receive(self) -> Any:
        pass
