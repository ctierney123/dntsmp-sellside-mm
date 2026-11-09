"""
Decide whether an AH first-row book looks thin / low-liquidity.

Casual: is this a staircase of unique prices, or a thick price wall?
"""

from __future__ import annotations

from collections import Counter

from ah_price.config import ARMOR_ARB_LOW_LIQUIDITY_MAX_PRICE_REPEAT


class OrderBookLiquidityClassifier:
    """
    Labels a priced AH row as low-liquidity vs normal/thick.

    Casual: thin book = 5.1, 5.2, 5.3…; thick book = lots of the same number.
    Low liquidity means few (or no) repeated prices — a smooth ascending
    staircase with no "cliffs" / walls of identical listings. Thick books
    show the same coin amount many times (e.g. six 6.4M slots), which is
    our signal that the far side of the row is a real market cluster.
    """

    def __init__(
        self,
        max_price_repeat_for_low: int = ARMOR_ARB_LOW_LIQUIDITY_MAX_PRICE_REPEAT,
    ) -> None:
        if max_price_repeat_for_low < 1:
            raise ValueError("max_price_repeat_for_low must be >= 1")
        self._max_repeat_for_low = int(max_price_repeat_for_low)

    @property
    def max_price_repeat_for_low(self) -> int:
        return self._max_repeat_for_low

    def is_low_liquidity(self, prices: list[int]) -> bool:
        """
        True when no single price repeats enough to look like a wall.

        Casual: mostly unique steps → thin book; a fat repeat → thick book.
        Empty / single-price rows are not treated as low-liquidity special
        cases here — the market estimator already handles tiny lists. We
        only flip to "low" when there is at least one priced listing and
        the busiest price appears at most ``max_price_repeat_for_low`` times
        (default 2). Example: ``5.1…5.6`` → low; ``6.4×6`` → not low.
        """
        if not prices:
            return False

        # Counter values are how many slots share each exact coin amount.
        max_repeat = max(Counter(prices).values())
        return max_repeat <= self._max_repeat_for_low
