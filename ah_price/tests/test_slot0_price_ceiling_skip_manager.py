"""
Unit tests for per-item slot-0 price ceiling skips.

Casual: prove ingots/swords above their caps get ignored; at/under still run.
"""

from __future__ import annotations

import unittest
from typing import Any

from ah_price.armor_arb.slot0_price_ceiling_skip_manager import (
    Slot0PriceCeilingSkipManager,
)


def _listing(slot: int, price: int | None, *, ok: bool = True) -> dict[str, Any]:
    """Build a fake compare-row dict like PriceCompareManager emits."""
    return {
        "slot": slot,
        "ok": ok and price is not None,
        "price": price,
        "price_raw": None if price is None else f"${price}",
    }


class Slot0PriceCeilingSkipManagerTests(unittest.TestCase):
    """Ceiling map lookup + strict-greater skip rule."""

    def setUp(self) -> None:
        self.manager = Slot0PriceCeilingSkipManager(
            ceilings={"netherite ingot": 10_100_000},
        )

    def test_ingot_above_ceiling_skips(self) -> None:
        decision = self.manager.evaluate(
            "/ah netherite ingot",
            [_listing(0, 10_100_001), _listing(1, 10_200_000)],
        )
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.reason, "slot0_price_ceiling")
        self.assertEqual(decision.item_key, "netherite ingot")
        self.assertEqual(decision.slot0_price, 10_100_001)
        self.assertEqual(decision.ceiling_coins, 10_100_000)

    def test_ingot_at_ceiling_does_not_skip(self) -> None:
        decision = self.manager.evaluate(
            "/ah netherite ingot",
            [_listing(0, 10_100_000)],
        )
        self.assertIsNone(decision)

    def test_ingot_under_ceiling_does_not_skip(self) -> None:
        decision = self.manager.evaluate(
            "netherite ingot",
            [_listing(0, 9_900_000)],
        )
        self.assertIsNone(decision)

    def test_unconfigured_query_never_skips(self) -> None:
        decision = self.manager.evaluate(
            "/ah netherite boots",
            [_listing(0, 50_000_000)],
        )
        self.assertIsNone(decision)

    def test_failed_slot0_ocr_does_not_skip(self) -> None:
        decision = self.manager.evaluate(
            "/ah netherite ingot",
            [_listing(0, None, ok=False), _listing(1, 11_000_000)],
        )
        self.assertIsNone(decision)

    def test_default_config_includes_ingot_and_sword_ceilings(self) -> None:
        manager = Slot0PriceCeilingSkipManager()
        self.assertIn("netherite ingot", manager.ceilings)
        self.assertEqual(manager.ceilings["netherite ingot"], 10_100_000)
        self.assertIn("netherite sword", manager.ceilings)
        self.assertEqual(manager.ceilings["netherite sword"], 7_100_000)

    def test_sword_above_ceiling_skips_with_default_config(self) -> None:
        manager = Slot0PriceCeilingSkipManager()
        decision = manager.evaluate(
            "/ah netherite sword",
            [_listing(0, 7_100_001)],
        )
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.reason, "slot0_price_ceiling")
        self.assertEqual(decision.item_key, "netherite sword")
        self.assertEqual(decision.ceiling_coins, 7_100_000)

    def test_sword_at_ceiling_does_not_skip_with_default_config(self) -> None:
        manager = Slot0PriceCeilingSkipManager()
        decision = manager.evaluate(
            "/ah netherite sword",
            [_listing(0, 7_100_000)],
        )
        self.assertIsNone(decision)


if __name__ == "__main__":
    unittest.main()
