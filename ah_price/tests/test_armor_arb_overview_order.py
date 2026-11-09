"""
Unit tests for catalog-stable armor-arb pass overviews.

Casual: shuffled search order should still print in catalog order.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from ah_price.armor_arb.manager import ArmorArbManager
from ah_price.automation.query_normalizer import AhSearchQueryNormalizer


class ArmorArbOverviewOrderTests(unittest.TestCase):
    """End-of-pass overview should follow constructor catalog order."""

    def test_items_in_catalog_order_reorders_shuffled_pass(self) -> None:
        catalog = (
            "netherite chestplate",
            "netherite leggings",
            "netherite helm",
            "netherite boots",
        )
        arb = ArmorArbManager.__new__(ArmorArbManager)
        arb._queries = tuple(
            AhSearchQueryNormalizer.normalize(q) for q in catalog
        )

        shuffled_reports = [
            {"query": "/ah netherite boots", "purchased": True},
            {"query": "/ah netherite chestplate", "purchased": False},
            {"query": "/ah netherite helm", "purchased": False},
            {"query": "/ah netherite leggings", "purchased": False},
        ]
        ordered = arb._items_in_catalog_order(shuffled_reports)
        self.assertEqual(
            [row["query"] for row in ordered],
            [
                "/ah netherite chestplate",
                "/ah netherite leggings",
                "/ah netherite helm",
                "/ah netherite boots",
            ],
        )

    def test_print_final_summary_uses_overview_items(self) -> None:
        printed: list[str] = []

        def fake_print(*args: object, **_: object) -> None:
            printed.append(" ".join(str(a) for a in args))

        summary = {
            "purchase_count": 1,
            "sell_count": 1,
            "items": [
                {"query": "/ah netherite boots", "purchased": False},
                {
                    "query": "/ah netherite chestplate",
                    "purchased": True,
                    "opportunity": {
                        "slot": 0,
                        "price_raw": "$4.6M",
                        "discount_coins": 200_000,
                    },
                    "buy_confirm": {"clicked": True},
                    "sell": {"sold": True, "price_text": "4.7m"},
                },
            ],
            "overview_items": [
                {
                    "query": "/ah netherite chestplate",
                    "purchased": True,
                    "opportunity": {
                        "slot": 0,
                        "price_raw": "$4.6M",
                        "discount_coins": 200_000,
                    },
                    "buy_confirm": {"clicked": True},
                    "sell": {"sold": True, "price_text": "4.7m"},
                },
                {"query": "/ah netherite boots", "purchased": False},
            ],
        }
        with patch("builtins.print", side_effect=fake_print):
            ArmorArbManager._print_final_summary(summary)

        buy_lines = [line for line in printed if line.startswith("  BUY")]
        skip_lines = [line for line in printed if line.startswith("  skip")]
        self.assertEqual(len(buy_lines), 1)
        self.assertIn("chestplate", buy_lines[0])
        self.assertEqual(len(skip_lines), 1)
        self.assertIn("boots", skip_lines[0])
        # Catalog-stable overview: BUY (chestplate) before skip (boots).
        self.assertLess(
            printed.index(buy_lines[0]),
            printed.index(skip_lines[0]),
        )


if __name__ == "__main__":
    unittest.main()
