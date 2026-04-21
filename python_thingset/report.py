#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
"""Decoded ThingSet publish/subscribe reports.

Reports are broadcast by devices on UDP port 9002 (for IP transports)
without any subscribe handshake — the device picks its own schedule.
An :class:`AsyncThingSetUDPReceiver` reassembles UDP fragments and
yields ``(addr, ThingSetReport)`` pairs.
"""

from dataclasses import dataclass
from typing import Any, Dict, Union


@dataclass
class ThingSetReport:
    """A single publish/subscribe message decoded off the wire.

    The transport-level source address (``(ip, port)``) lives on the
    receiver's iterator tuple, not here — a report is transport-
    agnostic content.
    """

    subset_id: int
    values: Dict[int, Any]
    eui: Union[int, None] = None

    def __str__(self) -> str:
        eui_part = f"EUI={self.eui:#018x}" if self.eui is not None else "no EUI"
        return (
            f"ThingSetReport(subset={self.subset_id:#x}, {eui_part}, "
            f"{len(self.values)} values)"
        )
