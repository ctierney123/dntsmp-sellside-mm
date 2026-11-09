"""
Decide whether a first-row AH listing is a buyable undercut.

Casual: spot the suspiciously cheap slot vs the row's market rate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ah_price.config import (
    ARMOR_ARB_UNDERCUT_MAX_COINS,
    ARMOR_ARB_UNDERCUT_MIN_COINS,
)
from ah_price.pricing.market_price_estimator import MarketPriceEstimator


@dataclass(frozen=True)
class UndercutOpportunity:
    """
    One listing cheap enough vs the row's market reference to buy.

    Casual: the "buy this" verdict + how deep the discount is.
    ``market_price`` is the row's market reference (full-row median on
    thick books; front-of-book median on thin staircases — see
    ``MarketPriceEstimator``), so a 6.0M snag still qualifies when 6.1M
    sits beside a 6.4M wall, without inventing edge on 5.1…5.6 books.
    """

    slot: int
    hover_xy: tuple[int, int]
    price: int
    price_raw: str | None
    market_price: int
    discount_coins: int


class UndercutDetector:
    """
    Finds the single best listing undercut vs the market reference.

    Casual: is this 6m a snag when the row's going rate is ~6.4m?
    Rule: market comes from ``MarketPriceEstimator`` (full median, or
    cheapest-N median on low-liquidity staircases). A candidate
    qualifies when ``market - candidate`` falls in
    ``[ARMOR_ARB_UNDERCUT_MIN_COINS, ARMOR_ARB_UNDERCUT_MAX_COINS]``.
    Among qualifiers we buy only the cheapest (lowest slot on ties) —
    never multiple items in one pass.
    """

    def __init__(
        self,
        min_discount_coins: int = ARMOR_ARB_UNDERCUT_MIN_COINS,
        max_discount_coins: int = ARMOR_ARB_UNDERCUT_MAX_COINS,
        market_estimator: MarketPriceEstimator | None = None,
    ) -> None:
        if min_discount_coins < 0 or max_discount_coins < 0:
            raise ValueError("undercut coin bounds must be non-negative")
        if min_discount_coins > max_discount_coins:
            raise ValueError(
                "min_discount_coins cannot exceed max_discount_coins "
                f"({min_discount_coins} > {max_discount_coins})"
            )
        self._min_discount = int(min_discount_coins)
        self._max_discount = int(max_discount_coins)
        self._market = market_estimator or MarketPriceEstimator()

    @property
    def min_discount_coins(self) -> int:
        return self._min_discount

    @property
    def max_discount_coins(self) -> int:
        return self._max_discount

    def find_opportunity(
        self,
        listings: list[dict[str, Any]],
        *,
        exclude_slots: set[int] | frozenset[int] | None = None,
    ) -> UndercutOpportunity | None:
        """
        Scan priced slots and return the single best undercut, if any.

        Casual: pick the cheapest in-band snag vs the row median, else None.
        Stacked undercuts (e.g. 6.0M + 6.1M under a 6.4M market) all
        qualify on discount; we still return only the lowest-priced one.
        ``exclude_slots`` skips candidates already ruled out (e.g. our own
        listing) so the next-best in-band snag can still be bought.
        """
        blocked = set(exclude_slots or ())
        priced = [
            row
            for row in listings
            if row.get("ok")
            and row.get("price") is not None
            and int(row["slot"]) not in blocked
        ]
        # Market median still uses the full priced row (including blocked
        # slots) so excluding our listing doesn't warp the going rate.
        all_priced = [
            row
            for row in listings
            if row.get("ok") and row.get("price") is not None
        ]
        if len(all_priced) < 2:
            return None

        prices = [int(row["price"]) for row in all_priced]
        market_price = self._market.estimate(prices)
        if market_price is None:
            return None

        best: UndercutOpportunity | None = None
        for candidate in priced:
            opportunity = self._opportunity_for_candidate(
                candidate, market_price
            )
            if opportunity is None:
                continue
            if best is None or self._is_better(opportunity, best):
                best = opportunity
        return best

    def _opportunity_for_candidate(
        self,
        candidate: dict[str, Any],
        market_price: int,
    ) -> UndercutOpportunity | None:
        """
        Test one slot against the row's market median.

        Casual: is this one cheap enough vs the going rate?
        """
        candidate_slot = int(candidate["slot"])
        candidate_price = int(candidate["price"])

        # Must sit strictly below the market reference.
        if candidate_price >= market_price:
            return None

        discount = market_price - candidate_price
        if discount < self._min_discount or discount > self._max_discount:
            return None

        hover = candidate.get("hover_xy")
        if not isinstance(hover, tuple) or len(hover) != 2:
            return None

        return UndercutOpportunity(
            slot=candidate_slot,
            hover_xy=(int(hover[0]), int(hover[1])),
            price=candidate_price,
            price_raw=candidate.get("price_raw"),
            market_price=market_price,
            discount_coins=discount,
        )

    @staticmethod
    def _is_better(
        candidate: UndercutOpportunity,
        incumbent: UndercutOpportunity,
    ) -> bool:
        """
        Prefer lower price; break ties with the leftmost slot.

        Casual: buy the cheapest snag, and if tied, the one on the left.
        """
        if candidate.price != incumbent.price:
            return candidate.price < incumbent.price
        return candidate.slot < incumbent.slot
