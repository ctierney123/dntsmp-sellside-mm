"""
Overnight safety guards: balance floor + OCR parse-fail budget.

Casual: stop the bot before it bleeds cash or spins on bad OCR.
"""

from __future__ import annotations

from ah_price.guards.balance_guard_manager import BalanceFloorHalt, BalanceGuardManager
from ah_price.guards.parse_failure_guard_manager import (
    ParseFailureGuardManager,
    ParseFailureHalt,
)

__all__ = [
    "BalanceFloorHalt",
    "BalanceGuardManager",
    "ParseFailureGuardManager",
    "ParseFailureHalt",
]
