"""
Unit tests for own-listing skip (price + tooltip fingerprint).

Casual: prove we remember sells and don't rebuy our own tips.
"""

from __future__ import annotations

import unittest

import numpy as np

from ah_price.listings.own_listing_tracker import OwnListingTracker
from ah_price.tooltip.tooltip_fingerprint_matcher import TooltipFingerprintMatcher
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


def _binary_tip(seed: int, width: int = 40, height: int = 20) -> np.ndarray:
    """
    Make a tiny deterministic binary "tooltip" for fingerprint tests.

    Casual: fake tip pixels so we can test match / mismatch without mss.
    """
    rng = np.random.default_rng(seed)
    # Sparse white strokes on black — enough structure for correlation.
    frame = np.zeros((height, width), dtype=np.uint8)
    noise = rng.integers(0, 2, size=(height, width), dtype=np.uint8) * 255
    frame[:, :] = noise
    # Unique block so different seeds don't accidentally correlate highly.
    frame[seed % height, :] = 255
    frame[:, seed % width] = 255
    return frame


class TooltipFingerprintMatcherTests(unittest.TestCase):
    """Near-1:1 binary tip compare."""

    def setUp(self) -> None:
        self.matcher = TooltipFingerprintMatcher(match_threshold=0.92)

    def test_identical_crops_match(self) -> None:
        tip = _binary_tip(7)
        matched, score = self.matcher.is_same_listing(tip, tip.copy())
        self.assertTrue(matched)
        self.assertGreaterEqual(score, 0.99)

    def test_different_crops_do_not_match(self) -> None:
        a = _binary_tip(1)
        b = _binary_tip(99)
        matched, score = self.matcher.is_same_listing(a, b)
        self.assertFalse(matched)
        self.assertLess(score, 0.92)


class OwnListingTrackerTests(unittest.TestCase):
    """Record sells; skip on price + fingerprint."""

    def setUp(self) -> None:
        self.clock = {"t": 1_000.0}

        def _now() -> float:
            return float(self.clock["t"])

        self.tracker = OwnListingTracker(
            enabled=True,
            ttl_seconds=3_600.0,
            matcher=TooltipFingerprintMatcher(match_threshold=0.92),
            clock=_now,
        )

    def test_disabled_never_matches(self) -> None:
        tracker = OwnListingTracker(enabled=False)
        tracker.record_sell("/ah netherite boots", 5_000_000)
        is_own, _score, reason = tracker.matches_own_listing(
            "/ah netherite boots",
            5_000_000,
            _binary_tip(1),
        )
        self.assertFalse(is_own)
        self.assertEqual(reason, "disabled")

    def test_first_sighting_claims_fingerprint(self) -> None:
        self.tracker.record_sell("/ah netherite boots", 5_000_000)
        tip = _binary_tip(3)
        is_own, score, reason = self.tracker.matches_own_listing(
            "/ah netherite boots",
            5_000_000,
            tip,
        )
        self.assertTrue(is_own)
        self.assertEqual(reason, "fingerprint_claimed")
        self.assertEqual(score, 1.0)

        # Second sighting with the same tip must fingerprint-match.
        is_own2, score2, reason2 = self.tracker.matches_own_listing(
            "/ah netherite boots",
            5_000_000,
            tip.copy(),
        )
        self.assertTrue(is_own2)
        self.assertEqual(reason2, "fingerprint_match")
        self.assertGreaterEqual(score2 or 0.0, 0.92)

    def test_same_price_different_tooltip_is_not_ours(self) -> None:
        self.tracker.record_sell("/ah netherite boots", 5_000_000)
        self.tracker.matches_own_listing(
            "/ah netherite boots",
            5_000_000,
            _binary_tip(3),
        )
        is_own, _score, reason = self.tracker.matches_own_listing(
            "/ah netherite boots",
            5_000_000,
            _binary_tip(88),
        )
        self.assertFalse(is_own)
        self.assertEqual(reason, "fingerprint_mismatch")

    def test_price_hit_without_capture_still_skips(self) -> None:
        self.tracker.record_sell("/ah netherite boots", 5_000_000)
        is_own, score, reason = self.tracker.matches_own_listing(
            "/ah netherite boots",
            5_000_000,
            None,
        )
        self.assertTrue(is_own)
        self.assertIsNone(score)
        self.assertEqual(reason, "price_hit_no_capture")

    def test_wrong_price_is_not_ours(self) -> None:
        self.tracker.record_sell("/ah netherite boots", 5_000_000)
        is_own, _score, reason = self.tracker.matches_own_listing(
            "/ah netherite boots",
            5_100_000,
            _binary_tip(3),
        )
        self.assertFalse(is_own)
        self.assertEqual(reason, "no_price_hit")

    def test_ttl_expires_listings(self) -> None:
        self.tracker.record_sell("/ah netherite boots", 5_000_000)
        self.clock["t"] = 1_000.0 + 3_601.0
        is_own, _score, reason = self.tracker.matches_own_listing(
            "/ah netherite boots",
            5_000_000,
            _binary_tip(3),
        )
        self.assertFalse(is_own)
        self.assertEqual(reason, "no_price_hit")
        self.assertEqual(self.tracker.active_count, 0)


class UndercutExcludeSlotsTests(unittest.TestCase):
    """exclude_slots should pick the next in-band snag."""

    def setUp(self) -> None:
        self.detector = UndercutDetector(
            min_discount_coins=199_000,
            max_discount_coins=1_500_000,
        )

    def test_exclude_cheapest_picks_next(self) -> None:
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
        # Slot 0 is "ours"; next in-band snag is slot 1 (300k under 6.4M).
        opp = self.detector.find_opportunity(listings, exclude_slots={0})
        self.assertIsNotNone(opp)
        assert opp is not None
        self.assertEqual(opp.slot, 1)
        self.assertEqual(opp.price, 6_100_000)
        # Market still uses the full row (including excluded slot 0).
        self.assertEqual(opp.market_price, 6_400_000)


if __name__ == "__main__":
    unittest.main()
