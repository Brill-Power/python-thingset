#
# Copyright (c) 2024-2025 Brill Power.
#
# SPDX-License-Identifier: Apache-2.0
#
"""Decoded ThingSet publish/subscribe reports.

Reports are broadcast by devices on UDP port 9002 (IP) or onto the
CAN bus without any subscribe handshake — the device picks its own
schedule. The async receivers reassemble fragments and yield
``(addr, ThingSetReport)`` pairs.
"""

from dataclasses import dataclass
from typing import Any, Dict, Union


@dataclass
class ThingSetReport:
    """A single publish/subscribe message decoded off the wire.

    The transport-level source address lives on the receiver's
    iterator tuple, not here — a report is transport-agnostic content.

    ``subset_id`` is the CBOR uint that follows the type byte in the
    standard report envelope. It is ``None`` for synthetic reports
    built from CAN single-frame publishes (where the data ID is in
    the CAN-ID itself and there is no subset concept).
    """

    subset_id: Union[int, None]
    values: Dict[int, Any]
    eui: Union[int, None] = None

    def __str__(self) -> str:
        eui_part = f"EUI={self.eui:#018x}" if self.eui is not None else "no EUI"
        subset = (
            f"{self.subset_id:#x}" if self.subset_id is not None else "none"
        )
        return (
            f"ThingSetReport(subset={subset}, {eui_part}, "
            f"{len(self.values)} values)"
        )
