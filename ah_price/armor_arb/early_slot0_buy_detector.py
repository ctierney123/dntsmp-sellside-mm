"""
Decide whether slot 0 is obvious enough to buy before scanning the full row.

Casual: if the left listing is clearly a snag vs 1/2/3, stop OCR'ing and buy.
"""

from __future__ import annotations

from statistics import median
from typing import Any

from ah_price.config import (
    ARMOR_ARB_EARLY_BUY_PROBE_SLOT_COUNT,
    ARMOR_ARB_UNDERCUT_MAX_COINS,
    ARMOR_ARB_UNDERCUT_MIN_COINS,
)
from ah_price.pricing.undercut_detector import UndercutOpportunity


class EarlySlot0BuyDetector:
    """
    Early-exit gate for obvious slot-0 undercuts after a short probe.

    Casual: peek slots 0–3; if 0 is way under 1/2/3, skip 4–8 and buy.
    Requires every probe slot to OCR successfully, slot 0 strictly below
    each neighbor, a next-cheapest gap of at least ``min_discount_coins``
    (so stacked left-side snags like 6.0/6.1/6.2 do not early-exit and
    wreck sell pricing), and ``median(neighbors) - slot0`` inside the
    normal undercut band. Returns an ``UndercutOpportunity`` shaped like
    the full-row detector so buy/sell paths stay unchanged.
    """

    def __init__(
        self,
        *,
        probe_slot_count: int = ARMOR_ARB_EARLY_BUY_PROBE_SLOT_COUNT,
        min_discount_coins: int = ARMOR_ARB_UNDERCUT_MIN_COINS,
        max_discount_coins: int = ARMOR_ARB_UNDERCUT_MAX_COINS,
    ) -> None:
        if probe_slot_count < 2:
            raise ValueError("probe_slot_count must be >= 2 (slot 0 + neighbors)")
        if min_discount_coins < 0 or max_discount_coins < 0:
            raise ValueError("undercut coin bounds must be non-negative")
        if min_discount_coins > max_discount_coins:
            raise ValueError(
                "min_discount_coins cannot exceed max_discount_coins "
                f"({min_discount_coins} > {max_discount_coins})"
            )
        self._probe_slot_count = int(probe_slot_count)
        self._min_discount = int(min_discount_coins)
        self._max_discount = int(max_discount_coins)

    @property
    def probe_slot_count(self) -> int:
        return self._probe_slot_count

    @property
    def min_discount_coins(self) -> int:
        return self._min_discount

    @property
    def max_discount_coins(self) -> int:
        return self._max_discount

    def should_stop_after(self, listings: list[dict[str, Any]]) -> bool:
        """
        True when the probe is complete and slot 0 is an early buy.

        Casual: enough slots read + obvious snag? stop the compare loop.
        """
        return self.evaluate(listings) is not None

    def evaluate(
        self,
        listings: list[dict[str, Any]],
    ) -> UndercutOpportunity | None:
        """
        Inspect the partial row and return a slot-0 buy, or None.

        Casual: after slots 0–3, is the left one clearly the snag?
        Returns None until all probe slots are present and priced, or when
        the gap / band rules fail (caller should keep scanning).
        """
        by_slot = self._priced_probe_by_slot(listings)
        if by_slot is None:
            return None

        slot0 = by_slot[0]
        neighbors = [by_slot[index] for index in range(1, self._probe_slot_count)]
        slot0_price = int(slot0["price"])
        neighbor_prices = [int(row["price"]) for row in neighbors]

        # Must beat every probed neighbor — "egregiously low vs 1/2/3".
        if any(slot0_price >= price for price in neighbor_prices):
            return None

        # Next-cheapest gap guards stacked undercuts (6.0 then 6.1…).
        next_cheapest = min(neighbor_prices)
        nearest_gap = next_cheapest - slot0_price
        if nearest_gap < self._min_discount:
            return None

        # Market reference from the probed wall only (exclude the snag).
        market_price = int(median(neighbor_prices))
        discount = market_price - slot0_price
        if discount < self._min_discount or discount > self._max_discount:
            return None

        hover = slot0.get("hover_xy")
        if not isinstance(hover, tuple) or len(hover) != 2:
            return None

        return UndercutOpportunity(
            slot=0,
            hover_xy=(int(hover[0]), int(hover[1])),
            price=slot0_price,
            price_raw=slot0.get("price_raw"),
            market_price=market_price,
            discount_coins=discount,
        )

    def _priced_probe_by_slot(
        self,
        listings: list[dict[str, Any]],
    ) -> dict[int, dict[str, Any]] | None:
        """
        Map probe slot index → listing when every probe slot OCR'd OK.

        Casual: need a clean 0..N-1 read before we dare early-buy.
        """
        if len(listings) < self._probe_slot_count:
            return None

        by_slot: dict[int, dict[str, Any]] = {}
        for row in listings:
            slot = int(row["slot"])
            if slot < 0 or slot >= self._probe_slot_count:
                continue
            if not row.get("ok") or row.get("price") is None:
                return None
            by_slot[slot] = row

        if len(by_slot) != self._probe_slot_count:
            return None
        return by_slot
