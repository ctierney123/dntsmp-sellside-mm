"""
One remembered AH listing we put up ourselves.

Casual: sticky note — "we listed this query at this price."
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class OwnListingRecord:
    """
    A sell we placed: search query, coins, optional tooltip fingerprint.

    Casual: remember what we listed so we don't buy it back.
    ``tooltip_binary`` is filled the first time we re-see a matching price
    on the book (or when a caller supplies a capture). Matching uses that
    binary crop plus the coin price — see ``OwnListingTracker``.
    """

    query: str
    sell_coins: int
    listed_at: float
    tooltip_binary: np.ndarray | None = field(default=None, repr=False)

    def has_fingerprint(self) -> bool:
        """True once we've stored a tooltip crop for this listing."""
        return self.tooltip_binary is not None
