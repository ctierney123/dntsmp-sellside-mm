"""
Skip whole AH searches when slot 0 is above a per-item price ceiling.

Casual: if the leftmost listing is already too expensive, bail on that item.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from ah_price.config import ARMOR_ARB_SLOT0_PRICE_CEILINGS
from ah_price.automation.query_normalizer import AhSearchQueryNormalizer


@dataclass(frozen=True)
class Slot0PriceCeilingSkip:
    """
    One skip decision: this query's slot 0 blew past its configured cap.

    Casual: leftover crumbs so logs can say why we walked away.
    """

    query: str
    item_key: str
    slot0_price: int
    ceiling_coins: int
    reason: str = "slot0_price_ceiling"


class Slot0PriceCeilingSkipManager:
    """
    Enforce per-item max prices on the leftmost AH listing.

    Casual: don't bother with ingots (etc.) when slot 0 is already too rich.
    After a full-row compare, look up the search query in
    ``ARMOR_ARB_SLOT0_PRICE_CEILINGS``. If slot 0 OCR'd a price strictly
    above that ceiling, return a skip decision so the arb never buys.
    Missing / failed slot-0 prices do not trigger a skip (other guards
    handle parse fails).
    """

    def __init__(
        self,
        ceilings: Mapping[str, int] | None = None,
    ) -> None:
        raw = (
            ARMOR_ARB_SLOT0_PRICE_CEILINGS if ceilings is None else ceilings
        )
        # Normalize keys once so "/ah Netherite Ingot" still matches.
        self._ceilings: dict[str, int] = {
            self._item_key_from_query(key): int(coins)
            for key, coins in raw.items()
        }
        for key, coins in self._ceilings.items():
            if coins < 0:
                raise ValueError(
                    f"slot0 price ceiling for {key!r} must be non-negative"
                )

    @property
    def ceilings(self) -> dict[str, int]:
        return dict(self._ceilings)

    def evaluate(
        self,
        query: str,
        listings: list[dict[str, Any]],
    ) -> Slot0PriceCeilingSkip | None:
        """
        Return a skip if this query's slot 0 is above its ceiling.

        Casual: check leftmost price; walk away when it's too high.
        Looks up the item name (after ``/ah``) in the ceiling map. Slot 0
        must have ``ok`` + a numeric ``price``. Equality with the ceiling
        is allowed; only strictly greater prices skip.
        """
        item_key = self._item_key_from_query(query)
        ceiling = self._ceilings.get(item_key)
        if ceiling is None:
            return None

        slot0_price = self._slot0_price_coins(listings)
        if slot0_price is None:
            return None
        if slot0_price <= ceiling:
            return None

        return Slot0PriceCeilingSkip(
            query=query,
            item_key=item_key,
            slot0_price=slot0_price,
            ceiling_coins=ceiling,
        )

    @staticmethod
    def _slot0_price_coins(
        listings: list[dict[str, Any]],
    ) -> int | None:
        """
        Pull the OCR'd coin amount from the leftmost listing row.

        Casual: find slot 0's price, or None if OCR missed.
        """
        for row in listings:
            if int(row.get("slot", -1)) != 0:
                continue
            if not row.get("ok"):
                return None
            price = row.get("price")
            if price is None:
                return None
            return int(price)
        return None

    @staticmethod
    def _item_key_from_query(query: str) -> str:
        """
        Strip ``/ah`` so ceiling keys match config item names.

        Casual: turn ``/ah netherite ingot`` into ``netherite ingot``.
        """
        normalized = AhSearchQueryNormalizer.normalize(query)
        body = normalized[1:].lstrip() if normalized.startswith("/") else normalized
        lower = body.lower()
        if lower == "ah":
            return ""
        if lower.startswith("ah "):
            return body[3:].strip().lower()
        return body.strip().lower()
