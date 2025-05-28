#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
from dataclasses import asdict, dataclass
from random import randint
from typing import Union


@dataclass
class ThingSetIDType(object):
    REQ_RESP: int = 0x00 << 24
    MULTI_FR: int = 0x01 << 24
    SINGL_FR: int = 0x02 << 24
    NET_MGMT: int = 0x03 << 24


@dataclass
class ThingSetIDPriority(object):
    NET_MGMT: int = 0x04 << 26
    PUB_HIGH: int = 0x05 << 26
    SERVICE: int = 0x06 << 26
    REQ_RESP: int = SERVICE
    PUB_LOW: int = 0x07 << 26


class ThingSetID(object):
    MIN_ADDR: int = 0x00
    MAX_ADDR: int = 0xFD

    SRC_ADDR_GATEWAY_DEFAULT = MIN_ADDR
    SRC_ADDR_ANON: int = 0xFE
    SRC_ADDR_BCAST: int = 0xFF

    TYPE_DISCOVERY: int = 0x01
    TYPE_CLAIM: int = 0x02
    TYPE_REQ_RESP: int = 0x03

    ADDR_CLAIM_MASK: int = 0xFF00FFFF

    def __init__(
        self,
        source_addr: int,
        target_addr: int,
        priority: ThingSetIDPriority,
        type: ThingSetIDType,
        source_bus: Union[int, None] = None,
        target_bus: Union[int, None] = None,
    ):
        self.source_addr = source_addr
        self.target_addr = target_addr
        self.priority = priority
        self.type = type
        self.source_bus = source_bus
        self.target_bus = target_bus

        """ If source address is 0xFE and priority and type are network management, then
        this is a discovery frame identifer

        Else if target address is 0xFF and priority and type are network management, then
        this is a claim frame identifier
        """
        if (
            self.source_addr == self.SRC_ADDR_ANON
            and self.priority == ThingSetIDPriority.NET_MGMT
            and self.type == ThingSetIDType.NET_MGMT
        ):
            self.id = self.TYPE_DISCOVERY
        elif (
            self.target_addr == self.SRC_ADDR_BCAST
            and self.priority == ThingSetIDPriority.NET_MGMT
            and self.type == ThingSetIDType.NET_MGMT
        ):
            self.id = self.TYPE_CLAIM
        elif (
            self.priority == ThingSetIDPriority.REQ_RESP
            and type == ThingSetIDType.REQ_RESP
        ):
            self.id = self.TYPE_REQ_RESP

    @classmethod
    def generate_discovery_id(cls, target_addr) -> "ThingSetID":
        return ThingSetID(
            cls.SRC_ADDR_ANON,
            target_addr,
            ThingSetIDPriority.NET_MGMT,
            ThingSetIDType.NET_MGMT,
        )

    @classmethod
    def generate_claim_id(
        cls, source_addr: int, source_bus: int, target_bus: int
    ) -> "ThingSetID":
        return ThingSetID(
            source_addr,
            cls.SRC_ADDR_BCAST,
            ThingSetIDPriority.NET_MGMT,
            ThingSetIDType.NET_MGMT,
            source_bus=source_bus,
            target_bus=target_bus,
        )

    @classmethod
    def generate_req_resp_id(
        cls, source_addr: int, target_addr: int, source_bus: int, target_bus: int
    ) -> "ThingSetID":
        return ThingSetID(
            source_addr,
            target_addr,
            ThingSetIDPriority.REQ_RESP,
            ThingSetIDType.REQ_RESP,
            source_bus=source_bus,
            target_bus=target_bus,
        )

    @staticmethod
    def get_source_addr_from_id(id: int) -> int:
        return id & 0x000000FF

    @staticmethod
    def get_target_addr_from_id(id: int) -> int:
        return id & 0x0000FF00

    @property
    def id(self) -> int:
        return self._id

    @id.setter
    def id(self, _id_type) -> None:
        match _id_type:
            case self.TYPE_DISCOVERY:
                self._id = (
                    self.priority
                    | self.type
                    | randint(0x00, 0xFE) << 16
                    | self.target_addr << 8
                    | self.SRC_ADDR_ANON
                )
            case self.TYPE_CLAIM:
                self._id = (
                    self.priority
                    | self.type
                    | self.target_bus << 20
                    | self.source_bus << 16
                    | self.SRC_ADDR_BCAST << 8
                    | self.source_addr
                )
            case self.TYPE_REQ_RESP:
                self._id = (
                    self.priority
                    | self.type
                    | self.target_bus << 20
                    | self.source_bus << 16
                    | self.target_addr << 8
                    | self.source_addr
                )
            case _:
                self._id = None
                raise ValueError(f"Unknown ID type ({hex(_id_type)})")

    @property
    def source_addr(self) -> int:
        return self._source_addr

    @source_addr.setter
    def source_addr(self, _addr: int) -> None:
        if _addr < self.MIN_ADDR or _addr > self.SRC_ADDR_BCAST:
            raise ValueError(
                f"Source address ({hex(_addr)}) must be between {self.MIN_ADDR} and {self.SRC_ADDR_BCAST} inclusive"
            )

        self._source_addr = _addr

    @property
    def target_addr(self) -> int:
        return self._target_addr

    @target_addr.setter
    def target_addr(self, _addr: int) -> None:
        if _addr < self.MIN_ADDR or _addr > self.SRC_ADDR_BCAST:
            raise ValueError(
                f"Target address ({hex(_addr)}) must be between {self.MIN_ADDR} and {self.SRC_ADDR_BCAST} inclusive"
            )

        self._target_addr = _addr

    @property
    def priority(self) -> int:
        return self._priority

    @priority.setter
    def priority(self, _prio: int) -> None:
        if _prio not in asdict(ThingSetIDPriority()).values():
            raise ValueError(f"Invalid priority supplied ({_prio})")

        self._priority = _prio

    @property
    def type(self) -> int:
        return self._type

    @type.setter
    def type(self, _type: int) -> None:
        if _type not in asdict(ThingSetIDType()).values():
            raise ValueError(f"Invalid type supplied ({_type})")

        self._type = _type

    @property
    def source_bus(self) -> Union[int, None]:
        return self._source_bus

    @source_bus.setter
    def source_bus(self, _bus: int) -> None:
        self._source_bus = _bus

    @property
    def target_bus(self) -> Union[int, None]:
        return self._target_bus

    @target_bus.setter
    def target_bus(self, _bus: int) -> None:
        self._target_bus = _bus
