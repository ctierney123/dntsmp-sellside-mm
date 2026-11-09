"""
Unit tests for overnight parse-failure halt (one-off OK, repeated → stop).

Casual: prove one FAIL is forgiven and the second kills the night.
"""

from __future__ import annotations

import unittest
from typing import Any

from ah_price.guards.parse_failure_guard_manager import (
    ParseFailureGuardManager,
    ParseFailureHalt,
)


def _compare_with_fails(*failed_slots: int) -> dict[str, Any]:
    """Build a fake compare summary with ok=False on the given slots."""
    listings: list[dict[str, Any]] = []
    for slot in range(9):
        if slot in failed_slots:
            listings.append(
                {
                    "slot": slot,
                    "ok": False,
                    "error": f"Could not find $ on slot {slot}",
                    "price": None,
                }
            )
        else:
            listings.append(
                {
                    "slot": slot,
                    "ok": True,
                    "error": None,
                    "price": 5_000_000 + slot * 100_000,
                }
            )
    return {
        "listings": listings,
        "ok_count": 9 - len(failed_slots),
        "slot_count": 9,
    }


class ParseFailureGuardManagerTests(unittest.TestCase):
    """Session-wide one-off OCR miss allowance (only slots 0–4 count)."""

    def test_clean_compare_does_not_increment(self) -> None:
        guard = ParseFailureGuardManager(max_one_off_failures=1)
        count = guard.note_compare_summary(
            _compare_with_fails(),
            context="clean",
        )
        self.assertEqual(count, 0)
        self.assertEqual(guard.failed_slot_count, 0)

    def test_slot_5_plus_fails_are_ignored(self) -> None:
        """Tall-tooltip ROI clips on the right — never burn the one-off."""
        guard = ParseFailureGuardManager(max_one_off_failures=1)
        for slot in (5, 6, 7, 8):
            count = guard.note_compare_summary(
                _compare_with_fails(slot),
                context=f"slot{slot}",
            )
            self.assertEqual(count, 0)
        self.assertEqual(guard.failed_slot_count, 0)
        # Still can take a real one-off after many ignored right-side misses.
        count = guard.note_compare_summary(
            _compare_with_fails(3),
            context="real",
        )
        self.assertEqual(count, 1)
        self.assertEqual(guard.failed_slot_count, 1)

    def test_one_off_fail_is_tolerated(self) -> None:
        guard = ParseFailureGuardManager(max_one_off_failures=1)
        count = guard.note_compare_summary(
            _compare_with_fails(3),
            context="helm",
        )
        self.assertEqual(count, 1)
        self.assertEqual(guard.failed_slot_count, 1)

    def test_second_fail_halts(self) -> None:
        guard = ParseFailureGuardManager(max_one_off_failures=1)
        guard.note_compare_summary(_compare_with_fails(3), context="helm")
        with self.assertRaises(ParseFailureHalt) as ctx:
            guard.note_compare_summary(
                _compare_with_fails(4),
                context="boots",
            )
        self.assertEqual(guard.failed_slot_count, 2)
        self.assertIn("Repeated parsing fails", str(ctx.exception))
        self.assertIn("boots", str(ctx.exception))

    def test_slot_7_plus_counted_fail_counts_only_counted(self) -> None:
        """Slot 7 + slot 3 in one scan → only slot 3 burns the one-off."""
        guard = ParseFailureGuardManager(max_one_off_failures=1)
        count = guard.note_compare_summary(
            _compare_with_fails(3, 7),
            context="sword",
        )
        self.assertEqual(count, 1)
        self.assertEqual(guard.failed_slot_count, 1)

    def test_two_counted_fails_in_one_scan_halts_immediately(self) -> None:
        """Two slots-0–4 FAILs in one row blow past the one-off at once."""
        guard = ParseFailureGuardManager(max_one_off_failures=1)
        with self.assertRaises(ParseFailureHalt):
            guard.note_compare_summary(
                _compare_with_fails(2, 4),
                context="sword",
            )
        self.assertEqual(guard.failed_slot_count, 2)

    def test_clean_searches_do_not_reset_one_off_budget(self) -> None:
        """Allowance is session-wide — a clean scan does not forgive again."""
        guard = ParseFailureGuardManager(max_one_off_failures=1)
        guard.note_compare_summary(_compare_with_fails(3), context="first")
        guard.note_compare_summary(_compare_with_fails(), context="clean")
        with self.assertRaises(ParseFailureHalt):
            guard.note_compare_summary(
                _compare_with_fails(0),
                context="later",
            )


if __name__ == "__main__":
    unittest.main()
