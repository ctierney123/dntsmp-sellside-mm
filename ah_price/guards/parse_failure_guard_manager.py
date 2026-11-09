"""
Halt overnight armor-arb when tooltip OCR fails more than once.

Casual: one flaky slot is fine; a second fail means something's broken — stop.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from ah_price.config import (
    ARMOR_ARB_PARSE_COUNTED_SLOTS,
    ARMOR_ARB_PARSE_MAX_ONE_OFF_FAILURES,
)

logger = logging.getLogger(__name__)


class ParseFailureHalt(RuntimeError):
    """
    Raised when overnight OCR parse fails exceed the one-off allowance.

    Casual: we already burned our freebie miss — quit for the night.
    """


class ParseFailureGuardManager:
    """
    Track AH slot OCR failures and halt after more than a one-off miss.

    Casual: tolerate one bad parse; anything repeated means we screwed up.
    Overnight tooltip OCR should be rock-solid on the left/center of the
    first row. A single failed counted slot in a whole night can be noise.
    A second failed counted slot — same search or later — means calibration
    / focus / region is wrong, so we raise ``ParseFailureHalt`` and stop.

    Only slots in ``counted_slots`` (default 0–4) contribute to the halt
    budget. Slots 5+ often fail on very tall tooltips when the ROI clips
    the $ — those are accepted and never counted. Clean searches do not
    reset the counter: the one-off allowance is session-wide.
    """

    def __init__(
        self,
        max_one_off_failures: int = ARMOR_ARB_PARSE_MAX_ONE_OFF_FAILURES,
        counted_slots: Iterable[int] | None = None,
    ) -> None:
        if max_one_off_failures < 0:
            raise ValueError("max_one_off_failures must be non-negative")
        # How many failed slot parses we forgive before halting.
        # Default 1 = one freebie; the next fail stops the night.
        self._max_one_off = int(max_one_off_failures)
        # Only left/center slots (0–4) matter; 5+ are tall-tooltip noise.
        raw_counted = (
            ARMOR_ARB_PARSE_COUNTED_SLOTS
            if counted_slots is None
            else counted_slots
        )
        self._counted_slots = frozenset(int(s) for s in raw_counted)
        self._failed_slot_count = 0

    @property
    def max_one_off_failures(self) -> int:
        return self._max_one_off

    @property
    def counted_slots(self) -> frozenset[int]:
        return self._counted_slots

    @property
    def failed_slot_count(self) -> int:
        return self._failed_slot_count

    def note_compare_summary(
        self,
        compare_summary: dict[str, Any] | None,
        *,
        context: str = "search",
    ) -> int:
        """
        Ingest one first-row compare; halt if fails exceed the one-off budget.

        Casual: count FAILs on slots 0–4 only; quit if we've seen more than one.
        Returns how many *counted* slots failed in this compare (0 if none
        / only slot-5+ failed / missing summary).
        """
        fail_count = self._count_failed_slots(compare_summary)
        ignored_count = self._count_ignored_failed_slots(compare_summary)
        if ignored_count > 0 and fail_count <= 0:
            # Slot 5+ failed alone — log it, but do not touch the budget.
            ignored_slots = self._ignored_failed_slot_numbers(compare_summary)
            logger.info(
                "Ignoring parse fail(s) on slot(s) %s during %s "
                "(only slots %s count toward overnight halt)",
                ignored_slots,
                context,
                sorted(self._counted_slots),
            )
            print(
                f"Parse fail on slot(s) {ignored_slots} during {context} "
                f"(only {sorted(self._counted_slots)} count) — not counted"
            )
            return 0
        if fail_count <= 0:
            return 0

        previous = self._failed_slot_count
        self._failed_slot_count += fail_count
        logger.warning(
            "Parse failure(s) during %s: +%s counted slot(s) "
            "(session %s; one-off allowance %s; ignored slot-5+ fails %s)",
            context,
            fail_count,
            self._failed_slot_count,
            self._max_one_off,
            ignored_count,
        )

        if self._failed_slot_count <= self._max_one_off:
            print(
                f"Parse fail one-off tolerated ({self._failed_slot_count}/"
                f"{self._max_one_off}) during {context} — continuing"
            )
            return fail_count

        # Second+ failure (or multi-slot fail that blew past the allowance).
        details = self._failure_details(compare_summary)
        prior_note = f"; prior {previous}" if previous else ""
        message = (
            f"Repeated parsing fails during {context} "
            f"(+{fail_count} this scan, session total "
            f"{self._failed_slot_count}; allowance {self._max_one_off}"
            f"{prior_note}) — "
            f"halting overnight. Details: {details}"
        )
        print(message)
        raise ParseFailureHalt(message)

    def _count_failed_slots(
        self,
        compare_summary: dict[str, Any] | None,
    ) -> int:
        """
        How many counted-slot listing rows in this compare did not OCR cleanly.

        Casual: count FAIL lines only on slots 0–4.
        """
        if not compare_summary:
            return 0
        listings = compare_summary.get("listings") or []
        return sum(
            1
            for row in listings
            if not row.get("ok")
            and int(row.get("slot", -1)) in self._counted_slots
        )

    def _count_ignored_failed_slots(
        self,
        compare_summary: dict[str, Any] | None,
    ) -> int:
        """
        How many non-counted (slot 5+) FAILs were in this compare.

        Casual: count tall-tooltip misses we deliberately skip.
        """
        if not compare_summary:
            return 0
        listings = compare_summary.get("listings") or []
        return sum(
            1
            for row in listings
            if not row.get("ok")
            and int(row.get("slot", -1)) not in self._counted_slots
        )

    def _ignored_failed_slot_numbers(
        self,
        compare_summary: dict[str, Any] | None,
    ) -> list[int]:
        """Slot numbers that failed but are outside the counted set."""
        if not compare_summary:
            return []
        slots: list[int] = []
        for row in compare_summary.get("listings") or []:
            if row.get("ok"):
                continue
            slot = int(row.get("slot", -1))
            if slot not in self._counted_slots:
                slots.append(slot)
        return sorted(slots)

    def _failure_details(self, compare_summary: dict[str, Any] | None) -> str:
        """
        Short human-readable list of counted failed slots and why.

        Casual: slot numbers + error text for the halt message (0–4 only).
        """
        if not compare_summary:
            return "(no compare summary)"
        parts: list[str] = []
        for row in compare_summary.get("listings") or []:
            if row.get("ok"):
                continue
            slot = int(row.get("slot", -1))
            if slot not in self._counted_slots:
                continue
            error = row.get("error") or "unknown"
            parts.append(f"slot {slot}: {error}")
        return "; ".join(parts) if parts else "(no failed rows)"
