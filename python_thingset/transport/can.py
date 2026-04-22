#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
import queue
import threading
import time
from typing import Callable, Tuple, Union

import can
import isotp

from .transport import ThingSetTransport
from .._protocol import ParsedResponse, ThingSetProtocol, WireFormat
from ..client import ThingSetClient
from ..id import ThingSetID
from ..log import get_logger


logger = get_logger()


class _CanLink(ThingSetTransport):
    def __init__(self, bus: str, interface: str = "socketcan", fd: bool = True):
        super().__init__()
        self.bus = bus
        self.interface = interface
        self.fd = fd
        self._can = None
        self._rx_filters = []

    def attach_rx_filter(self, id: int, mask: int, callback: Callable) -> None:
        self._rx_filters.append({"id": id, "mask": mask, "callback": callback})

    def remove_rx_filter(self, id: int) -> None:
        for i, f in enumerate(self._rx_filters):
            if f["id"] == id:
                self._rx_filters.pop(i)

    def remove_all_rx_filters(self) -> None:
        self._rx_filters = []

    def _handle_message(self, message: can.Message) -> None:
        for f in self._rx_filters:
            if message.arbitration_id & f["mask"] == f["id"] & f["mask"]:
                f["callback"](message)

    def connect(self) -> None:
        if not self._can:
            self._can = can.Bus(channel=self.bus, interface=self.interface, fd=self.fd)
            self.start_receiving()

    def disconnect(self) -> None:
        if self._can:
            self.stop_receiving()
            self._can.shutdown()

    def receive(self) -> can.Message:
        return self._can.recv(timeout=0.1)

    def send(self, message: can.Message) -> None:
        return self._can.send(message)


class _IsotpLink(ThingSetTransport):
    """ISO-TP (multi-frame CAN) link. Emits parsed ThingSet responses
    into a queue via the injected protocol. Lifetime is one request/
    response cycle — constructed per _send in ThingSetCAN, torn down
    inside get_response().
    """

    def __init__(
        self,
        bus: str,
        rx_id: int,
        tx_id: int,
        protocol: ThingSetProtocol,
        fd: bool = True,
    ):
        super().__init__()
        self.bus = bus
        self.rx_id = rx_id
        self.tx_id = tx_id
        self._protocol = protocol
        self._address = None
        self._sock = isotp.socket(timeout=0.1)
        self._queue: "queue.Queue[ParsedResponse]" = queue.Queue()
        self._send_recurse_ctr = 0

        if fd:
            self._sock.set_ll_opts(mtu=isotp.socket.LinkLayerProtocol.CAN_FD, tx_dl=64)

        self._set_address()
        self.connect()

    def _set_address(self) -> None:
        self._address = isotp.Address(
            addressing_mode=isotp.AddressingMode.Normal_29bits,
            rxid=self.rx_id,
            txid=self.tx_id,
        )

    def get_response(self, timeout: float = 1.5) -> Union[ParsedResponse, None]:
        response = None
        try:
            response = self._queue.get(timeout=timeout)
        except queue.Empty:
            pass
        finally:
            if response is not None:
                self._queue.task_done()
            self.disconnect()
            return response

    def _handle_message(self, message: bytes) -> None:
        self._queue.put(self._protocol.parse_response(message))

    def connect(self) -> None:
        self._sock.bind(self.bus, self._address)
        self.start_receiving()

    def disconnect(self) -> None:
        self.stop_receiving()
        self._sock.close()

    def send(self, data: bytes) -> None:
        """Retry on CAN bus contention up to 10 times (1 s at 100 ms
        per try). Beyond that the resultant get_response call returns
        None and the application layer handles it.
        """
        try:
            sent = self._sock.send(data)
            self._send_recurse_ctr = 0
            return sent
        except TimeoutError:
            self._send_recurse_ctr += 1
            if self._send_recurse_ctr >= 10:
                self._send_recurse_ctr = 0
                logger.error("ISOTP transmission retry limit exceeded")
                return None
            self.send(data)

    def receive(self) -> bytes:
        try:
            return self._sock.recv()
        except TimeoutError:
            return None


class ThingSetCAN(ThingSetClient):
    ADDR_CLAIM_TIMEOUT_MS: int = 500
    CONNECT_TIMEOUT_MS: int = 10000

    EUI: list = [0xDE, 0xAD, 0xBE, 0xEF, 0xC0, 0xFF, 0xEE, 0xEE]

    def __init__(
        self,
        bus: str,
        addr: int = 0x00,
        source_bus: int = 0x00,
        target_bus: int = 0x00,
    ):
        self._protocol = ThingSetProtocol(WireFormat.BINARY)
        self.bus = bus
        self.node_addr = None
        self.source_bus = source_bus
        self.target_bus = target_bus

        self._addr_claim_timer = None
        self._taken_node_addrs = []

        self._can = _CanLink(self.bus)
        self._can.connect()
        self._isotp: Union[_IsotpLink, None] = None
        self.is_connected = False
        self._negotiate_address(addr)

        # Address negotiation is driven by a threading.Timer; block the
        # constructor until is_connected flips true (or we time out).
        # Without this, callers would race _send against a still-None
        # node_addr.
        deadline = time.monotonic() + (self.CONNECT_TIMEOUT_MS / 1000)
        while not self.is_connected and time.monotonic() < deadline:
            time.sleep(0.01)
        if not self.is_connected:
            raise TimeoutError(
                f"CAN address negotiation did not complete within "
                f"{self.CONNECT_TIMEOUT_MS} ms"
            )

    def disconnect(self) -> None:
        self._can.disconnect()
        if self._addr_claim_timer is not None:
            self._addr_claim_timer.cancel()
        self._can.remove_all_rx_filters()

    def _send(self, data: bytes, node_id: Union[int, None]) -> None:
        req_id, resp_id = self._get_isotp_ids(node_id)
        self._isotp = _IsotpLink(self.bus, resp_id.id, req_id.id, self._protocol)
        self._isotp.send(data)

    def _recv(self) -> Union[ParsedResponse, None]:
        if self._isotp is None:
            return None
        return self._isotp.get_response()

    def _get_isotp_ids(self, node_id: int) -> Tuple[ThingSetID, ThingSetID]:
        return (
            ThingSetID.generate_req_resp_id(
                self.node_addr, node_id, self.source_bus, self.target_bus
            ),
            ThingSetID.generate_req_resp_id(
                node_id, self.node_addr, self.source_bus, self.target_bus
            ),
        )

    def _negotiate_address(self, desired_addr: int, timeout=5000) -> None:
        self.is_connected = False

        claim_id = ThingSetID.generate_claim_id(desired_addr, 0x00, 0x00)
        disco_id = ThingSetID.generate_discovery_id(desired_addr)

        logger.debug(f"Attempting to claim node address 0x{desired_addr:02X}")

        self._can.attach_rx_filter(
            claim_id.id, ThingSetID.ADDR_CLAIM_MASK, self._address_claim_handler
        )
        self._can.send(can.Message(arbitration_id=disco_id.id, is_fd=self._can.fd))
        self._addr_claim_timer = threading.Timer(
            0.5, self._address_claim_complete, args=(disco_id.target_addr,)
        )
        self._addr_claim_timer.start()

    def _address_claim_handler(self, message: can.Message) -> None:
        if not self.is_connected:
            taken_addr = ThingSetID.get_source_addr_from_id(message.arbitration_id)

            self._addr_claim_timer.cancel()
            self._can.remove_rx_filter(
                message.arbitration_id & ThingSetID.ADDR_CLAIM_MASK
            )
            self._taken_node_addrs.append(taken_addr)

            logger.debug(f"Address 0x{taken_addr:02X} is in use by another node...")

            for new_addr in range(ThingSetID.MIN_ADDR, ThingSetID.MAX_ADDR):
                if new_addr not in self._taken_node_addrs:
                    self._negotiate_address(new_addr)
                    return None

            raise IOError(
                f"All addresses within range 0x{ThingSetID.MIN_ADDR:02X} to "
                f"0x{ThingSetID.MAX_ADDR:02X} are taken"
            )
        else:
            logger.debug(
                f"Device tried to claim this nodes address 0x{self.node_addr:02X}, "
                f"sending claim frame"
            )
            self._can.send(
                can.Message(
                    arbitration_id=ThingSetID.generate_claim_id(
                        self.node_addr, 0x00, 0x00
                    ).id,
                    data=self.EUI,
                    is_fd=self._can.fd,
                )
            )

    def _address_claim_complete(self, *args: tuple) -> None:
        self.is_connected = True
        self.node_addr = args[0]
        self._taken_node_addrs = []

        self._can.remove_rx_filter(
            ThingSetID.generate_claim_id(self.node_addr, 0x00, 0x00).id
            & ThingSetID.ADDR_CLAIM_MASK
        )
        self._can.attach_rx_filter(
            ThingSetID.generate_discovery_id(self.node_addr).id,
            0xFF00FF00,
            self._address_claim_handler,
        )
        self._can.send(
            can.Message(
                arbitration_id=ThingSetID.generate_claim_id(
                    self.node_addr, 0x00, 0x00
                ).id,
                data=self.EUI,
                is_fd=self._can.fd,
            )
        )

        logger.debug(f"Claimed node address 0x{self.node_addr:02X}")
