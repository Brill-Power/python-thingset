#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
import queue
import threading
from typing import Callable, Tuple, Union

import can
import isotp

from .backend import ThingSetBackend
from ..client import ThingSetClient
from ..encoders import ThingSetBinaryEncoder
from ..id import ThingSetID
from ..log import get_logger


logger = get_logger()


class CAN(ThingSetBackend):
    def __init__(self, bus: str, interface: str = "socketcan", fd=True):
        super().__init__()

        self.bus = bus
        self.interface = interface
        self.fd = fd

        self._can = None
        self._rx_filters = []

    @property
    def bus(self) -> str:
        return self._bus

    @bus.setter
    def bus(self, _bus: str) -> None:
        self._bus = _bus

    @property
    def interface(self) -> str:
        return self._interface

    @interface.setter
    def interface(self, _interface: str) -> None:
        self._interface = _interface

    @property
    def fd(self) -> bool:
        return self._fd

    @fd.setter
    def fd(self, _fd: bool) -> None:
        self._fd = _fd

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


class ISOTP(ThingSetBackend):
    def __init__(self, bus: str, rx_id: int, tx_id: int, fd: bool = True):
        super().__init__()

        self.bus = bus
        self.rx_id = rx_id
        self.tx_id = tx_id

        self._address = None
        self._sock = isotp.socket(timeout=0.1)
        self._queue = queue.Queue()
        self._send_recurse_ctr = 0

        if fd:
            self._sock.set_ll_opts(mtu=isotp.socket.LinkLayerProtocol.CAN_FD, tx_dl=64)

        self.set_address()
        self.connect()

    @property
    def bus(self) -> str:
        return self._bus

    @bus.setter
    def bus(self, _bus: str) -> None:
        self._bus = _bus

    @property
    def rx_id(self) -> int:
        return self._rx_id

    @rx_id.setter
    def rx_id(self, _id: int) -> None:
        self._rx_id = _id

    @property
    def tx_id(self) -> int:
        return self._tx_id

    @tx_id.setter
    def tx_id(self, _id: int) -> None:
        self._tx_id = _id

    def set_address(self) -> None:
        self._address = isotp.Address(
            addressing_mode=isotp.AddressingMode.Normal_29bits,
            rxid=self.rx_id,
            txid=self.tx_id,
        )

    def get_message(self, timeout: float = 1.5) -> Union[bytes, None]:
        message = None

        try:
            message = self._queue.get(timeout=timeout)
        except queue.Empty:
            pass
        finally:
            if message is not None:
                self._queue.task_done()
            self.disconnect()
            return message

    def _handle_message(self, message):
        self._queue.put(message)

    def connect(self) -> None:
        self._sock.bind(self.bus, self._address)
        self.start_receiving()

    def disconnect(self) -> None:
        self.stop_receiving()
        self._sock.close()

    def send(self, _data: bytes) -> None:
        """We have recursive calls to self.send here as we can't easily tell when the CAN
        device is busy from another program (which is entirely possible)

        So we just retry up to 10 times - with a timeout of 100ms this equates to 1 second

        The resultant call to ThingSetCAN.get/update/fetch/exec will just return a None response
        if the retry limit is exceeded so can be handled easily at the application layer
        """

        try:
            _send = self._sock.send(_data)
            self._send_recurse_ctr = 0
            return _send
        except TimeoutError:
            self._send_recurse_ctr += 1
            if self._send_recurse_ctr >= 10:
                self._send_recurse_ctr = 0
                logger.error("ISOTP transmission retry limit exceeded")
                return None

            self.send(_data)

    def receive(self) -> bytes:
        try:
            return self._sock.recv()
        except TimeoutError:
            return None


class ThingSetCAN(ThingSetClient, ThingSetBinaryEncoder):
    ADDR_CLAIM_TIMEOUT_MS: int = 500
    CONNECT_TIMEOUT_MS: int = 10000

    EUI: list = [0xDE, 0xAD, 0xBE, 0xEF, 0xC0, 0xFF, 0xEE, 0xEE]

    def __init__(
        self, bus: str, addr: int = 0x00, source_bus: int = 0x00, target_bus: int = 0x00
    ):
        super().__init__()

        self.backend = ThingSetBackend.CAN
        self.bus = bus
        self.node_addr = None
        self.source_bus = source_bus
        self.target_bus = target_bus

        self._addr_claim_timer = None
        self._taken_node_addrs = []

        self._can = CAN(self.bus)
        self._can.connect()
        self._negotiate_address(addr)

    def disconnect(self) -> None:
        self._can.disconnect()

        if self._addr_claim_timer is not None:
            self._addr_claim_timer.cancel()

        self._can.remove_all_rx_filters()

    def _send(self, data: bytes, node_id: Union[int, None]) -> None:
        req_id, resp_id = self._get_isotp_ids(node_id)
        self._isotp = ISOTP(self.bus, resp_id.id, req_id.id)
        self._isotp.send(data)

    def _recv(self) -> bytes:
        return self._isotp.get_message()

    def _get_isotp_ids(self, node_id: int) -> Tuple[ThingSetID]:
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
                f"All addresses within range 0x{ThingSetID.MIN_ADDR:02X} to 0x{ThingSetID.MAX_ADDR:02X} are taken"
            )
        else:
            logger.debug(
                f"Device tried to claim this nodes address 0x{self.node_addr:02X}, sending claim frame"
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

    @property
    def bus(self) -> str:
        return self._bus

    @bus.setter
    def bus(self, _bus: str) -> None:
        self._bus = _bus

    @property
    def node_addr(self) -> int:
        return self._node_addr

    @node_addr.setter
    def node_addr(self, _addr: Union[int, None]) -> None:
        self._node_addr = _addr
