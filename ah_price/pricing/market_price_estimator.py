"""
Estimate the fair / consensus price from an AH first-row scan.

Casual: figure out what the row thinks the item is "supposed" to cost.
"""

from __future__ import annotations

from statistics import median

from ah_price.config import ARMOR_ARB_LOW_LIQUIDITY_MEDIAN_WINDOW
from ah_price.pricing.order_book_liquidity_classifier import OrderBookLiquidityClassifier


class MarketPriceEstimator:
    """
    Turns a list of listing prices into one market reference number.

    Casual: ignore the cheap outliers and read the row's going rate.
    Default (thick book): median of all priced slots so 1–3 stacked
    undercuts on the left do not drag the reference down. With 9 slots
    and ≤3 undercuts, the median lands in the market cluster.

    Low-liquidity exception: when the row is a thin staircase (few/no
    repeated prices, e.g. 5.1 5.2 5.3 5.4…), median of the whole row
    sits too far right and invents fake edge vs what you can actually
    sell into. In that case we median only the cheapest N listings
    (default 4) so buy/sell stay anchored near the front of the book.
    """

    def __init__(
        self,
        liquidity_classifier: OrderBookLiquidityClassifier | None = None,
        low_liquidity_median_window: int = ARMOR_ARB_LOW_LIQUIDITY_MEDIAN_WINDOW,
    ) -> None:
        if low_liquidity_median_window < 1:
            raise ValueError("low_liquidity_median_window must be >= 1")
        self._liquidity = liquidity_classifier or OrderBookLiquidityClassifier()
        self._low_liq_window = int(low_liquidity_median_window)

    @property
    def low_liquidity_median_window(self) -> int:
        return self._low_liq_window

    def estimate(self, prices: list[int]) -> int | None:
        """
        Return the market reference price, or None if the list is empty.

        Casual: thick book → full-row median; thin book → front-of-book median.
        """
        if not prices:
            return None

        sample = self._prices_for_median(prices)
        # statistics.median returns int for odd-length int lists; for even
        # length it may return float — coerce so coin math stays integer.
        return int(median(sample))

    def _prices_for_median(self, prices: list[int]) -> list[int]:
        """
        Pick which prices feed the median (full row vs front window).

        Casual: thin staircase → only look at the first few cheapest slots.
        Ascending sort so "first N" means the left/cheapest side of the
        book regardless of slot OCR order. If the row is shorter than the
        window, we just use everything we have.
        """
        if not self._liquidity.is_low_liquidity(prices):
            return prices

        # Cheapest-first so the window tracks executable depth, not slot index.
        ascending = sorted(int(p) for p in prices)
        window = min(self._low_liq_window, len(ascending))
        return ascending[:window]
