"""
Compute bid/ask spread from slot-0 sell and buy book prices.

Casual: ask minus bid — how wide the gap is.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpreadSnapshot:
    """
    One bid/ask reading for a single item.

    Casual: the numbers we print after peeking both books.
    ``ask_coins`` = cheapest sell (/ah slot 0).
    ``bid_coins`` = highest buy (/order slot 0).
    ``spread_coins`` = ask - bid (negative means the book is crossed).
    """

    item_name: str
    ask_coins: int
    bid_coins: int
    ask_raw: str | None = None
    bid_raw: str | None = None

    @property
    def spread_coins(self) -> int:
        """Ask minus bid in raw coins."""
        return int(self.ask_coins) - int(self.bid_coins)

    @property
    def is_crossed(self) -> bool:
        """True when bid is strictly above ask (arb gap)."""
        return self.bid_coins > self.ask_coins


class SpreadCalculator:
    """
    Builds a SpreadSnapshot from slot-0 ask + bid coin amounts.

    Casual: feed it two prices, get the spread math back.
    Pure logic — no OCR, no input. Easy to unit test.
    """

    def calculate(
        self,
        *,
        item_name: str,
        ask_coins: int,
        bid_coins: int,
        ask_raw: str | None = None,
        bid_raw: str | None = None,
    ) -> SpreadSnapshot:
        """
        Validate prices and return a frozen spread snapshot.

        Casual: wrap ask/bid into one tidy result object.
        Both sides must be positive ints (OCR can return 0 on garbage).
        """
        name = str(item_name).strip()
        if not name:
            raise ValueError("item_name must be non-empty")

        ask = int(ask_coins)
        bid = int(bid_coins)
        if ask <= 0:
            raise ValueError(f"ask_coins must be > 0, got {ask}")
        if bid <= 0:
            raise ValueError(f"bid_coins must be > 0, got {bid}")

        return SpreadSnapshot(
            item_name=name,
            ask_coins=ask,
            bid_coins=bid,
            ask_raw=ask_raw,
            bid_raw=bid_raw,
        )
