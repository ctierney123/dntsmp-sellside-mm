"""
Unit tests for median market undercut detection.

Casual: prove the 6.0M + 6.1M under a 6.4M row buys slot 0.
"""

from __future__ import annotations

import unittest

from ah_price.pricing.market_price_estimator import MarketPriceEstimator
from ah_price.pricing.order_book_liquidity_classifier import OrderBookLiquidityClassifier
from ah_price.pricing.undercut_detector import UndercutDetector


def _listing(slot: int, price: int, ok: bool = True) -> dict:
    """Build a fake compare-row dict with a hover point."""
    return {
        "slot": slot,
        "ok": ok,
        "price": price,
        "price_raw": f"${price}",
        "hover_xy": (100 + slot * 72, 200),
    }


class OrderBookLiquidityClassifierTests(unittest.TestCase):
    """Thin staircases vs thick price walls."""

    def setUp(self) -> None:
        self.classifier = OrderBookLiquidityClassifier(max_price_repeat_for_low=2)

    def test_unique_staircase_is_low_liquidity(self) -> None:
        # User example: 5.1…5.6 with no repeated walls.
        prices = [
            5_100_000,
            5_200_000,
            5_300_000,
            5_400_000,
            5_500_000,
            5_600_000,
        ]
        self.assertTrue(self.classifier.is_low_liquidity(prices))

    def test_thick_wall_is_not_low_liquidity(self) -> None:
        prices = [6_000_000, 6_100_000] + [6_400_000] * 6
        self.assertFalse(self.classifier.is_low_liquidity(prices))

    def test_pair_repeats_still_count_as_low(self) -> None:
        # Max repeat 2 ≤ threshold → still thin enough for front-window median.
        prices = [5_100_000, 5_200_000, 5_200_000, 5_300_000, 5_400_000]
        self.assertTrue(self.classifier.is_low_liquidity(prices))

    def test_triple_repeat_is_a_wall(self) -> None:
        prices = [5_100_000, 5_200_000, 5_300_000, 5_300_000, 5_300_000]
        self.assertFalse(self.classifier.is_low_liquidity(prices))


class MarketPriceEstimatorTests(unittest.TestCase):
    """Median should ignore stacked left-side undercuts."""

    def setUp(self) -> None:
        self.estimator = MarketPriceEstimator()

    def test_empty_returns_none(self) -> None:
        self.assertIsNone(self.estimator.estimate([]))

    def test_odd_length_median(self) -> None:
        # Classic user case: 6.0, 6.1, 6.3, then six 6.4s → median 6.4M.
        prices = [
            6_000_000,
            6_100_000,
            6_300_000,
            6_400_000,
            6_400_000,
            6_400_000,
            6_400_000,
            6_400_000,
            6_400_000,
        ]
        self.assertEqual(self.estimator.estimate(prices), 6_400_000)

    def test_even_length_median_is_int(self) -> None:
        # Two unique prices → low-liq window of both; avg of 5 and 7 → 6.
        self.assertEqual(self.estimator.estimate([5, 7]), 6)

    def test_low_liquidity_uses_front_window_median(self) -> None:
        """
        Thin 5.1…5.9 book must not use the far-right full-row median.

        Full-row median would be 5.5M and invent a 400k "snag" on 5.1M.
        Front window of 4 → median(5.1, 5.2, 5.3, 5.4) = 5.25M.
        """
        prices = [
            5_100_000,
            5_200_000,
            5_300_000,
            5_400_000,
            5_500_000,
            5_600_000,
            5_700_000,
            5_800_000,
            5_900_000,
        ]
        self.assertEqual(self.estimator.estimate(prices), 5_250_000)

    def test_low_liquidity_window_of_three(self) -> None:
        estimator = MarketPriceEstimator(low_liquidity_median_window=3)
        prices = [
            5_100_000,
            5_200_000,
            5_300_000,
            5_400_000,
            5_500_000,
            5_600_000,
        ]
        # Median of cheapest 3 = 5.2M.
        self.assertEqual(estimator.estimate(prices), 5_200_000)


class UndercutDetectorTests(unittest.TestCase):
    """Buy the cheapest in-band snag vs median; never multi-buy."""

    def setUp(self) -> None:
        self.detector = UndercutDetector(
            min_discount_coins=199_000,
            max_discount_coins=2_500_000,
        )

    def test_stacked_undercuts_buys_cheapest(self) -> None:
        """
        User's live miss: 6.0M should buy even with 6.1M next door.

        Old next-cheapest logic saw only 100k vs 6.1M and skipped.
        Median is 6.4M → 400k discount → buy slot 0 only.
        """
        listings = [
            _listing(0, 6_000_000),
            _listing(1, 6_100_000),
            _listing(2, 6_300_000),
            _listing(3, 6_400_000),
            _listing(4, 6_400_000),
            _listing(5, 6_400_000),
            _listing(6, 6_400_000),
            _listing(7, 6_400_000),
            _listing(8, 6_400_000),
        ]
        opp = self.detector.find_opportunity(listings)
        self.assertIsNotNone(opp)
        assert opp is not None
        self.assertEqual(opp.slot, 0)
        self.assertEqual(opp.price, 6_000_000)
        self.assertEqual(opp.market_price, 6_400_000)
        self.assertEqual(opp.discount_coins, 400_000)

    def test_classic_single_undercut_still_works(self) -> None:
        listings = [
            _listing(0, 5_000_000),
            _listing(1, 5_300_000),
            _listing(2, 5_300_000),
            _listing(3, 5_500_000),
            _listing(4, 5_500_000),
        ]
        opp = self.detector.find_opportunity(listings)
        self.assertIsNotNone(opp)
        assert opp is not None
        self.assertEqual(opp.slot, 0)
        self.assertEqual(opp.market_price, 5_300_000)
        self.assertEqual(opp.discount_coins, 300_000)

    def test_discount_below_band_is_skipped(self) -> None:
        # 100k under median — too small for the 199k floor.
        listings = [
            _listing(0, 6_300_000),
            _listing(1, 6_400_000),
            _listing(2, 6_400_000),
            _listing(3, 6_400_000),
        ]
        self.assertIsNone(self.detector.find_opportunity(listings))

    def test_discount_above_band_is_skipped(self) -> None:
        # 3M under median — looks like OCR garbage / wrong item, not a snag.
        listings = [
            _listing(0, 3_000_000),
            _listing(1, 6_000_000),
            _listing(2, 6_000_000),
            _listing(3, 6_000_000),
        ]
        self.assertIsNone(self.detector.find_opportunity(listings))

    def test_1_7m_discount_is_in_2_5m_band(self) -> None:
        """Live miss that used to print 'No undercut' with a 1.5m max."""
        listings = [
            _listing(0, 5_000_000),
            _listing(1, 6_700_000),
            _listing(2, 6_700_000),
            _listing(3, 6_700_000),
            _listing(4, 6_700_000),
            _listing(5, 6_700_000),
            _listing(6, 6_700_000),
            _listing(7, 6_700_000),
            _listing(8, 6_700_000),
        ]
        opp = self.detector.find_opportunity(listings)
        self.assertIsNotNone(opp)
        assert opp is not None
        self.assertEqual(opp.slot, 0)
        self.assertEqual(opp.discount_coins, 1_700_000)

    def test_flat_row_is_skipped(self) -> None:
        listings = [_listing(i, 6_400_000) for i in range(9)]
        self.assertIsNone(self.detector.find_opportunity(listings))

    def test_prefers_leftmost_on_price_tie(self) -> None:
        # Two identical undercuts; buy the left one only.
        listings = [
            _listing(0, 6_000_000),
            _listing(1, 6_000_000),
            _listing(2, 6_400_000),
            _listing(3, 6_400_000),
            _listing(4, 6_400_000),
        ]
        opp = self.detector.find_opportunity(listings)
        self.assertIsNotNone(opp)
        assert opp is not None
        self.assertEqual(opp.slot, 0)
        self.assertEqual(opp.price, 6_000_000)

    def test_needs_at_least_two_priced_slots(self) -> None:
        self.assertIsNone(self.detector.find_opportunity([_listing(0, 5_000_000)]))
        self.assertIsNone(
            self.detector.find_opportunity(
                [_listing(0, 5_000_000), _listing(1, 6_000_000, ok=False)]
            )
        )

    def test_low_liquidity_staircase_skips_fake_edge(self) -> None:
        """
        5.1…5.9 thin book: full median would buy 5.1; front median must not.

        Casual: don't get wrecked by slippage on a staircase book.
        Front-window median 5.25M → 5.1M is only 150k under → below 199k floor.
        """
        listings = [
            _listing(0, 5_100_000),
            _listing(1, 5_200_000),
            _listing(2, 5_300_000),
            _listing(3, 5_400_000),
            _listing(4, 5_500_000),
            _listing(5, 5_600_000),
            _listing(6, 5_700_000),
            _listing(7, 5_800_000),
            _listing(8, 5_900_000),
        ]
        self.assertIsNone(self.detector.find_opportunity(listings))

    def test_low_liquidity_real_front_snag_still_buys(self) -> None:
        # 4.9M under a thin 5.2…5.5 front → 350k vs 5.25M window median.
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
        opp = self.detector.find_opportunity(listings)
        self.assertIsNotNone(opp)
        assert opp is not None
        self.assertEqual(opp.slot, 0)
        self.assertEqual(opp.market_price, 5_250_000)
        self.assertEqual(opp.discount_coins, 350_000)


if __name__ == "__main__":
    unittest.main()
