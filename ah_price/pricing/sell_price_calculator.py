"""
Pick an /ah sell price from the first-row book we just bought from.

Casual: undercut the real market by 100k, not the other snag next door.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ah_price.config import (
    ARMOR_ARB_UNDERCUT_MIN_COINS,
    ARMOR_ARB_SELL_UNDERCUT_COINS,
)
from ah_price.pricing.market_price_estimator import MarketPriceEstimator


@dataclass(frozen=True)
class SellPriceDecision:
    """
    Chosen sell amount plus the book reference we undercut.

    Casual: the number we type after /ah sell, and why.
    """

    sell_coins: int
    reference_coins: int
    market_price: int
    skipped_outlier_count: int


class SellPriceCalculator:
    """
    Compute sell price = competitive_reference - 100k.

    Casual: 100k under the next real listing, skipping egregious lows.
    Default rule: after buying the cheapest slot, sell 100k under the
    next-cheapest remaining listing ("2nd lowest" of the original book).

    Exception — stacked snags (user example ``7m, 7.1m, 7.7×…``):
    the 7.1m is also an egregious undercut vs the row median, so we skip
    it and undercut the first non-outlier (7.7m → sell 7.6m). Outliers
    use the same floor as buy detection (``ARMOR_ARB_UNDERCUT_MIN_COINS``)
    so buy and sell agree on what "egregious" means.
    """

    def __init__(
        self,
        undercut_coins: int = ARMOR_ARB_SELL_UNDERCUT_COINS,
        outlier_min_discount_coins: int = ARMOR_ARB_UNDERCUT_MIN_COINS,
        market_estimator: MarketPriceEstimator | None = None,
    ) -> None:
        if undercut_coins < 0:
            raise ValueError("undercut_coins must be non-negative")
        if outlier_min_discount_coins < 0:
            raise ValueError("outlier_min_discount_coins must be non-negative")
        self._undercut = int(undercut_coins)
        self._outlier_min = int(outlier_min_discount_coins)
        self._market = market_estimator or MarketPriceEstimator()

    @property
    def undercut_coins(self) -> int:
        return self._undercut

    def decide(
        self,
        listings: list[dict[str, Any]],
        purchased_slot: int,
    ) -> SellPriceDecision | None:
        """
        Pick sell coins from the compare row after buying one slot.

        Casual: look at what's left on the row and undercut the real price.
        Returns None when we don't have enough priced slots to decide.
        """
        priced = [
            row
            for row in listings
            if row.get("ok") and row.get("price") is not None
        ]
        if len(priced) < 2:
            return None

        all_prices = [int(row["price"]) for row in priced]
        market_price = self._market.estimate(all_prices)
        if market_price is None:
            return None

        # Drop the listing we just bought; sell vs whatever remains.
        remaining = sorted(
            int(row["price"])
            for row in priced
            if int(row["slot"]) != int(purchased_slot)
        )
        if not remaining:
            return None

        reference, skipped = self._first_competitive_reference(
            remaining, market_price
        )
        sell_coins = reference - self._undercut
        if sell_coins <= 0:
            return None

        return SellPriceDecision(
            sell_coins=sell_coins,
            reference_coins=reference,
            market_price=market_price,
            skipped_outlier_count=skipped,
        )

    def would_profit(
        self,
        listings: list[dict[str, Any]],
        purchased_slot: int,
        buy_coins: int,
    ) -> tuple[bool, SellPriceDecision | None]:
        """
        True only when planned sell is strictly above the buy price.

        Casual: if we'd buy and sell for the same coins, don't bother.
        Uses the same competitive_ref - 100k rule as ``decide``. Returns
        ``(False, None)`` when we cannot price a sell at all (not enough
        remaining listings). Equal buy/sell (e.g. buy 7.6m, ref 7.7m →
        sell 7.6m) is treated as not profitable — zero edge after fees /
        time, so the arb should skip the click.
        """
        decision = self.decide(listings, purchased_slot)
        if decision is None:
            return False, None
        return decision.sell_coins > int(buy_coins), decision

    def _first_competitive_reference(
        self,
        remaining_ascending: list[int],
        market_price: int,
    ) -> tuple[int, int]:
        """
        Walk cheapest→dearest; skip egregious undercuts vs median.

        Casual: ignore the other snags, land on the real going rate.
        Falls back to the market median if every remaining price looks
        like an outlier (pathological / OCR-weird rows).
        """
        skipped = 0
        for price in remaining_ascending:
            discount = market_price - price
            # Still at/above market, or only a tiny gap → competitive.
            if discount < self._outlier_min:
                return price, skipped
            skipped += 1

        # Everything left looked like a snag — undercut the median itself.
        return market_price, skipped
