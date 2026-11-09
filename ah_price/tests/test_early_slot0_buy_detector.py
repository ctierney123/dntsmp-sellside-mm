"""
Unit tests for early slot-0 buy after probing slots 0–3.

Casual: prove 5.0 vs 5.6/5.6/5.7 early-buys, and stacked snags don't.
"""

from __future__ import annotations

import unittest

from ah_price.armor_arb.early_slot0_buy_detector import EarlySlot0BuyDetector


def _listing(slot: int, price: int, ok: bool = True) -> dict:
    """Build a fake compare-row dict with a hover point."""
    return {
        "slot": slot,
        "ok": ok,
        "price": price,
        "price_raw": f"${price}",
        "hover_xy": (100 + slot * 72, 200),
    }


class EarlySlot0BuyDetectorTests(unittest.TestCase):
    """Obvious snags early-buy; stacked / thin gaps keep scanning."""

    def setUp(self) -> None:
        self.detector = EarlySlot0BuyDetector(
            probe_slot_count=4,
            min_discount_coins=199_000,
            max_discount_coins=2_500_000,
        )

    def test_user_example_early_buys(self) -> None:
        """5.0 / 5.6 / 5.6 / 5.7 → skip 4–8 and buy slot 0."""
        listings = [
            _listing(0, 5_000_000),
            _listing(1, 5_600_000),
            _listing(2, 5_600_000),
            _listing(3, 5_700_000),
        ]
        opp = self.detector.evaluate(listings)
        self.assertIsNotNone(opp)
        assert opp is not None
        self.assertEqual(opp.slot, 0)
        self.assertEqual(opp.price, 5_000_000)
        self.assertEqual(opp.market_price, 5_600_000)
        self.assertEqual(opp.discount_coins, 600_000)
        self.assertTrue(self.detector.should_stop_after(listings))

    def test_wide_wall_within_new_2_5m_band_early_buys(self) -> None:
        """5.0 vs 6.7 wall (1.7m) — previously above 1.5m max, now early-buys."""
        listings = [
            _listing(0, 5_000_000),
            _listing(1, 6_700_000),
            _listing(2, 6_700_000),
            _listing(3, 6_700_000),
        ]
        opp = self.detector.evaluate(listings)
        self.assertIsNotNone(opp)
        assert opp is not None
        self.assertEqual(opp.discount_coins, 1_700_000)

    def test_stacked_undercuts_do_not_early_buy(self) -> None:
        """
        6.0 / 6.1 / 6.2 / 6.4 must keep scanning the full row.

        Next-cheapest gap is only 100k — early exit would under-price the
        sell reference without the 6.4 wall.
        """
        listings = [
            _listing(0, 6_000_000),
            _listing(1, 6_100_000),
            _listing(2, 6_200_000),
            _listing(3, 6_400_000),
        ]
        self.assertIsNone(self.detector.evaluate(listings))
        self.assertFalse(self.detector.should_stop_after(listings))

    def test_incomplete_probe_waits(self) -> None:
        listings = [
            _listing(0, 5_000_000),
            _listing(1, 5_600_000),
            _listing(2, 5_600_000),
        ]
        self.assertIsNone(self.detector.evaluate(listings))
        self.assertFalse(self.detector.should_stop_after(listings))

    def test_failed_neighbor_ocr_blocks_early_buy(self) -> None:
        listings = [
            _listing(0, 5_000_000),
            _listing(1, 5_600_000),
            _listing(2, 5_600_000, ok=False),
            _listing(3, 5_700_000),
        ]
        self.assertIsNone(self.detector.evaluate(listings))

    def test_discount_above_max_band_skips(self) -> None:
        listings = [
            _listing(0, 3_000_000),
            _listing(1, 6_000_000),
            _listing(2, 6_000_000),
            _listing(3, 6_000_000),
        ]
        self.assertIsNone(self.detector.evaluate(listings))

    def test_tiny_gap_below_min_band_skips(self) -> None:
        listings = [
            _listing(0, 5_500_000),
            _listing(1, 5_600_000),
            _listing(2, 5_600_000),
            _listing(3, 5_600_000),
        ]
        self.assertIsNone(self.detector.evaluate(listings))


if __name__ == "__main__":
    unittest.main()
