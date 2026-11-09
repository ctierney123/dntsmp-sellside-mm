"""
Remember our own AH sells so we don't click them again.

Casual: track what we listed; skip buying our own stuff back.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np

from ah_price.config import (
    OWN_LISTING_SKIP_ENABLED,
    OWN_LISTING_TTL_SECONDS,
)
from ah_price.listings.own_listing_record import OwnListingRecord
from ah_price.tooltip.tooltip_fingerprint_matcher import TooltipFingerprintMatcher

logger = logging.getLogger(__name__)


class OwnListingTracker:
    """
    In-memory registry of listings we placed via sell-after-buy.

    Casual: sticky notes for "we put this up" so we don't rebuy it.
    Matching rules when a buy candidate shares query + sell price:
      1) If we already have a tooltip fingerprint → require near-1:1 match.
      2) If we don't yet → claim this sighting as ours (first price hit
         after listing is almost always our own undercut) and store the
         fingerprint for later passes.
    Sold / expired listings drop after ``ttl_seconds``. Multiple open
    listings for the same query+price are tracked as separate records.
    """

    def __init__(
        self,
        *,
        enabled: bool = OWN_LISTING_SKIP_ENABLED,
        ttl_seconds: float = OWN_LISTING_TTL_SECONDS,
        matcher: TooltipFingerprintMatcher | None = None,
        clock: Any = time.time,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be > 0, got {ttl_seconds}")
        self._enabled = bool(enabled)
        self._ttl = float(ttl_seconds)
        self._matcher = matcher or TooltipFingerprintMatcher()
        self._clock = clock
        self._records: list[OwnListingRecord] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def active_count(self) -> int:
        """How many non-expired own listings we still remember."""
        self._prune_expired()
        return len(self._records)

    def record_sell(
        self,
        query: str,
        sell_coins: int,
        tooltip_binary: np.ndarray | None = None,
    ) -> OwnListingRecord | None:
        """
        Remember a successful /ah sell so later buys can skip it.

        Casual: we just listed this — jot it down.
        Returns the stored record, or None when the tracker is disabled.
        """
        if not self._enabled:
            return None
        query_key = str(query).strip()
        coins = int(sell_coins)
        if not query_key or coins <= 0:
            raise ValueError(
                f"invalid own listing (query={query!r}, sell_coins={sell_coins})"
            )

        record = OwnListingRecord(
            query=query_key,
            sell_coins=coins,
            listed_at=float(self._clock()),
            tooltip_binary=(
                None if tooltip_binary is None else np.array(tooltip_binary, copy=True)
            ),
        )
        self._records.append(record)
        self._prune_expired()
        logger.info(
            "Own listing recorded: %s @ %s (active=%d)",
            query_key,
            f"{coins:,}",
            len(self._records),
        )
        return record

    def matches_own_listing(
        self,
        query: str,
        price_coins: int,
        tooltip_binary: np.ndarray | None,
    ) -> tuple[bool, float | None, str]:
        """
        Check whether this buy candidate is one of our open listings.

        Casual: same search + same price + tip looks like ours?
        Returns ``(is_own, match_score, reason)`` where reason is one of:
        ``disabled``, ``no_price_hit``, ``fingerprint_match``,
        ``fingerprint_claimed``, ``fingerprint_mismatch``,
        ``price_hit_no_capture``.
        """
        if not self._enabled:
            return False, None, "disabled"

        self._prune_expired()
        query_key = str(query).strip()
        coins = int(price_coins)
        candidates = [
            row
            for row in self._records
            if row.query == query_key and row.sell_coins == coins
        ]
        if not candidates:
            return False, None, "no_price_hit"

        # Prefer confirming against a record that already has a fingerprint.
        fingerprinted = [row for row in candidates if row.has_fingerprint()]
        unclaimed = [row for row in candidates if not row.has_fingerprint()]

        if tooltip_binary is None:
            # Capture failed — still refuse the click when price matches an
            # open sell. Better to miss a snag than buy our own listing.
            return True, None, "price_hit_no_capture"

        if fingerprinted:
            best_score = 0.0
            for row in fingerprinted:
                matched, score = self._matcher.is_same_listing(
                    row.tooltip_binary,  # type: ignore[arg-type]
                    tooltip_binary,
                )
                best_score = max(best_score, score)
                if matched:
                    return True, score, "fingerprint_match"
            # Price matched a known listing but the tip looks different —
            # likely someone else listed the same undercut number.
            if not unclaimed:
                return False, best_score, "fingerprint_mismatch"

        # First re-sighting after sell: claim it and lock the tip pixels.
        claim = unclaimed[0]
        claim.tooltip_binary = np.array(tooltip_binary, copy=True)
        logger.info(
            "Own listing fingerprint claimed: %s @ %s",
            query_key,
            f"{coins:,}",
        )
        return True, 1.0, "fingerprint_claimed"

    def _prune_expired(self) -> None:
        """
        Drop listings older than the TTL.

        Casual: forget sells that are probably gone from the AH by now.
        """
        now = float(self._clock())
        before = len(self._records)
        self._records = [
            row for row in self._records if (now - row.listed_at) <= self._ttl
        ]
        dropped = before - len(self._records)
        if dropped:
            logger.debug("Pruned %d expired own listing(s)", dropped)
