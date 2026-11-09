"""
Unit tests for the 30m balance floor / wait / halt guard.

Casual: prove we wait twice then halt on the third under-floor read.
"""

from __future__ import annotations

import unittest
from typing import Any

from ah_price.guards.balance_guard_manager import BalanceFloorHalt, BalanceGuardManager


class _ScriptedReader:
    """Return canned HUD snapshots / errors in order."""

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.calls = 0

    def __call__(self) -> dict[str, Any]:
        self.calls += 1
        if not self._script:
            raise RuntimeError("script exhausted")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class BalanceGuardManagerTests(unittest.TestCase):
    """Floor enforcement without real sleeps / OCR."""

    def test_above_floor_passes_immediately(self) -> None:
        reader = _ScriptedReader(
            [{"username": "PlayerName", "balance_raw": "$ 52.1M", "balance": 52_100_000}]
        )
        guard = BalanceGuardManager(
            min_balance_coins=30_000_000,
            wait_seconds=0.0,
            max_failures=3,
            reader=reader,
        )
        snap = guard.ensure_above_floor(context="test")
        self.assertEqual(snap["balance"], 52_100_000)
        self.assertEqual(guard.consecutive_failures, 0)
        self.assertEqual(reader.calls, 1)

    def test_recovers_after_one_under_floor_wait(self) -> None:
        reader = _ScriptedReader(
            [
                {"balance_raw": "$ 25.0M", "balance": 25_000_000},
                {"balance_raw": "$ 40.0M", "balance": 40_000_000},
            ]
        )
        guard = BalanceGuardManager(
            min_balance_coins=30_000_000,
            wait_seconds=0.0,
            max_failures=3,
            reader=reader,
        )
        snap = guard.ensure_above_floor(context="test")
        self.assertEqual(snap["balance"], 40_000_000)
        self.assertEqual(guard.consecutive_failures, 0)
        self.assertEqual(reader.calls, 2)

    def test_halts_after_three_under_floor_checks(self) -> None:
        reader = _ScriptedReader(
            [
                {"balance_raw": "$ 20.0M", "balance": 20_000_000},
                {"balance_raw": "$ 21.0M", "balance": 21_000_000},
                {"balance_raw": "$ 22.0M", "balance": 22_000_000},
            ]
        )
        guard = BalanceGuardManager(
            min_balance_coins=30_000_000,
            wait_seconds=0.0,
            max_failures=3,
            reader=reader,
        )
        with self.assertRaises(BalanceFloorHalt):
            guard.ensure_above_floor(context="test")
        self.assertEqual(guard.consecutive_failures, 3)
        self.assertEqual(reader.calls, 3)


if __name__ == "__main__":
    unittest.main()
