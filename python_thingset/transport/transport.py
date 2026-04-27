#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
import threading
from abc import ABC, abstractmethod
from typing import Any

from ..log import get_logger


_logger = get_logger()


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
        # A single bad frame from the bus must not kill the receive
        # thread — callers waiting on a response in get_response()
        # would hang forever and the next reconnect would race against
        # a still-running thread. Log and continue; if the underlying
        # socket is permanently broken, receive() will keep raising
        # and the caller's timeout will surface the failure.
        while self._running:
            try:
                message = self.receive()
            except Exception as e:
                _logger.warning(
                    "%s receive raised %s: %s — continuing",
                    type(self).__name__, e.__class__.__name__, e,
                )
                continue
            if message:
                try:
                    self._handle_message(message)
                except Exception as e:
                    _logger.warning(
                        "%s handler raised %s: %s — continuing",
                        type(self).__name__, e.__class__.__name__, e,
                    )

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
