"""
AH row scan: slot grid geometry + multi-slot price compare.

Casual: hover each listing slot and figure out who's cheapest.
"""

from __future__ import annotations

from ah_price.scan.price_compare_manager import PriceCompareManager
from ah_price.scan.slot_grid_manager import SlotGridManager

__all__ = [
    "PriceCompareManager",
    "SlotGridManager",
]
