"""
Unit tests for sell-price undercut + AH chat price formatting.

Casual: prove 7m/7.1m/7.7… sells at 7.6m, and 7.6m formats right.
"""

from __future__ import annotations

import unittest

from ah_price.pricing.ah_price_formatter import AhPriceFormatter
from ah_price.pricing.sell_price_calculator import SellPriceCalculator


def _listing(slot: int, price: int, ok: bool = True) -> dict:
    """Build a fake compare-row dict."""
    return {
        "slot": slot,
        "ok": ok,
        "price": price,
        "price_raw": f"${price}",
        "hover_xy": (100 + slot * 72, 200),
    }


class AhPriceFormatterTests(unittest.TestCase):
    """Compact K/M/B strings for /ah sell."""

    def setUp(self) -> None:
        self.fmt = AhPriceFormatter()

    def test_millions_one_decimal(self) -> None:
        self.assertEqual(self.fmt.format_coins(7_600_000), "7.6m")

    def test_whole_millions_drop_point_zero(self) -> None:
        self.assertEqual(self.fmt.format_coins(7_000_000), "7m")

    def test_thousands(self) -> None:
        self.assertEqual(self.fmt.format_coins(100_000), "100k")

    def test_billions(self) -> None:
        self.assertEqual(self.fmt.format_coins(1_200_000_000), "1.2b")

    def test_rejects_negative(self) -> None:
        with self.assertRaises(ValueError):
            self.fmt.format_coins(-1)


class SellPriceCalculatorTests(unittest.TestCase):
    """100k under competitive reference; skip stacked snags."""

    def setUp(self) -> None:
        self.calc = SellPriceCalculator(
            undercut_coins=100_000,
            outlier_min_discount_coins=199_000,
        )

    def test_user_stacked_example_sells_under_cluster(self) -> None:
        """
        Book: 7m, 7.1m, then 7.7/7.8 cluster. Bought 7m → sell 7.6m.

        2nd-lowest naive would be 7.1m - 100k = 7.0m; we skip the
        egregious 7.1m and undercut 7.7m instead.
        """
        listings = [
            _listing(0, 7_000_000),
            _listing(1, 7_100_000),
            _listing(2, 7_700_000),
            _listing(3, 7_700_000),
            _listing(4, 7_700_000),
            _listing(5, 7_700_000),
            _listing(6, 7_800_000),
            _listing(7, 7_800_000),
            _listing(8, 7_800_000),
        ]
        decision = self.calc.decide(listings, purchased_slot=0)
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.sell_coins, 7_600_000)
        self.assertEqual(decision.reference_coins, 7_700_000)
        self.assertEqual(decision.skipped_outlier_count, 1)

    def test_normal_second_lowest_minus_100k(self) -> None:
        # Bought 6.0m; next is 6.4m (not an outlier) → sell 6.3m.
        listings = [
            _listing(0, 6_000_000),
            _listing(1, 6_400_000),
            _listing(2, 6_400_000),
            _listing(3, 6_400_000),
            _listing(4, 6_400_000),
        ]
        decision = self.calc.decide(listings, purchased_slot=0)
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.sell_coins, 6_300_000)
        self.assertEqual(decision.reference_coins, 6_400_000)
        self.assertEqual(decision.skipped_outlier_count, 0)

    def test_single_neighbor_undercut_is_skipped(self) -> None:
        # 6.0 bought; 6.1 is still egregious vs 6.4 median → sell 6.3m.
        listings = [
            _listing(0, 6_000_000),
            _listing(1, 6_100_000),
            _listing(2, 6_400_000),
            _listing(3, 6_400_000),
            _listing(4, 6_400_000),
            _listing(5, 6_400_000),
            _listing(6, 6_400_000),
            _listing(7, 6_400_000),
            _listing(8, 6_400_000),
        ]
        decision = self.calc.decide(listings, purchased_slot=0)
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.sell_coins, 6_300_000)
        self.assertEqual(decision.skipped_outlier_count, 1)

    def test_needs_two_priced_slots(self) -> None:
        self.assertIsNone(
            self.calc.decide([_listing(0, 5_000_000)], purchased_slot=0)
        )

    def test_buy_equals_planned_sell_is_not_profitable(self) -> None:
        """
        Buy 7.6m with next real listing 7.7m → sell 7.6m → skip.

        Casual: same buy/sell coins means zero edge; would_profit is False.
        """
        listings = [
            _listing(0, 7_600_000),
            _listing(1, 7_700_000),
            _listing(2, 7_800_000),
            _listing(3, 7_800_000),
            _listing(4, 7_800_000),
            _listing(5, 7_800_000),
            _listing(6, 7_800_000),
            _listing(7, 7_800_000),
            _listing(8, 7_800_000),
        ]
        profitable, decision = self.calc.would_profit(
            listings, purchased_slot=0, buy_coins=7_600_000
        )
        self.assertFalse(profitable)
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.sell_coins, 7_600_000)

    def test_buy_below_planned_sell_is_profitable(self) -> None:
        # Buy 7.0m → sell 7.6m (ref 7.7m) → clear profit.
        listings = [
            _listing(0, 7_000_000),
            _listing(1, 7_100_000),
            _listing(2, 7_700_000),
            _listing(3, 7_700_000),
            _listing(4, 7_700_000),
            _listing(5, 7_700_000),
            _listing(6, 7_800_000),
            _listing(7, 7_800_000),
            _listing(8, 7_800_000),
        ]
        profitable, decision = self.calc.would_profit(
            listings, purchased_slot=0, buy_coins=7_000_000
        )
        self.assertTrue(profitable)
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.sell_coins, 7_600_000)

    def test_low_liquidity_sell_anchors_to_front_of_book(self) -> None:
        """
        Thin staircase after buying 4.9m: undercut next real listing 5.2m.

        Casual: don't treat the far-right 5.9m as the market on a thin book.
        Front-window market is 5.25m; 5.2m is competitive → sell 5.1m.
        """
        listings = [
            _listing(0, 4_900_000),
            _listing(1, 5_200_000),
            _listing(2, 5_300_000),
            _listing(3, 5_400_000),
            _listing(4, 5_500_000),
            _listing(5, 5_600_000),
            _listing(6, 5_700_000),
            _listing(7, 5_800_000),
            _listing(8, 5_900_000),
        ]
        decision = self.calc.decide(listings, purchased_slot=0)
        self.assertIsNotNone(decision)
        assert decision is not None
        self.assertEqual(decision.market_price, 5_250_000)
        self.assertEqual(decision.reference_coins, 5_200_000)
        self.assertEqual(decision.sell_coins, 5_100_000)
        self.assertEqual(decision.skipped_outlier_count, 0)


if __name__ == "__main__":
    unittest.main()
