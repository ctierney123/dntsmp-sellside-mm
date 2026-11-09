"""
Unit tests for market-making command + spread math.

Casual: prove /ah+/order strings and ask-bid spread without touching Minecraft.
"""

from __future__ import annotations

import unittest

from ah_price.market_making.command_builder import MarketMakingCommandBuilder
from ah_price.market_making.spread_calculator import SpreadCalculator


class MarketMakingCommandBuilderTests(unittest.TestCase):
    """Build /ah and /order chat strings from item names."""

    def setUp(self) -> None:
        self.builder = MarketMakingCommandBuilder()

    def test_bare_item_name(self) -> None:
        self.assertEqual(
            self.builder.sell_book_command("enchanted golden apple"),
            "/ah enchanted golden apple",
        )
        self.assertEqual(
            self.builder.buy_book_command("enchanted golden apple"),
            "/order enchanted golden apple",
        )

    def test_strips_existing_ah_prefix(self) -> None:
        self.assertEqual(
            self.builder.sell_book_command("/ah enchanted golden apple"),
            "/ah enchanted golden apple",
        )
        self.assertEqual(
            self.builder.buy_book_command("ah enchanted golden apple"),
            "/order enchanted golden apple",
        )

    def test_strips_existing_order_prefix(self) -> None:
        self.assertEqual(
            self.builder.buy_book_command("/order enchanted golden apple"),
            "/order enchanted golden apple",
        )

    def test_empty_item_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.builder.sell_book_command("   ")


class SpreadCalculatorTests(unittest.TestCase):
    """Ask - bid spread snapshots."""

    def setUp(self) -> None:
        self.calc = SpreadCalculator()

    def test_positive_spread(self) -> None:
        snap = self.calc.calculate(
            item_name="enchanted golden apple",
            ask_coins=1_200_000,
            bid_coins=1_000_000,
            ask_raw="$1.2M",
            bid_raw="$1M",
        )
        self.assertEqual(snap.spread_coins, 200_000)
        self.assertFalse(snap.is_crossed)

    def test_crossed_book(self) -> None:
        snap = self.calc.calculate(
            item_name="enchanted golden apple",
            ask_coins=900_000,
            bid_coins=1_000_000,
        )
        self.assertEqual(snap.spread_coins, -100_000)
        self.assertTrue(snap.is_crossed)

    def test_rejects_non_positive_prices(self) -> None:
        with self.assertRaises(ValueError):
            self.calc.calculate(
                item_name="x",
                ask_coins=0,
                bid_coins=1_000,
            )


if __name__ == "__main__":
    unittest.main()
