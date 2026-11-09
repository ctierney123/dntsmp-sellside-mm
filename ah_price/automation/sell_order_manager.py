"""
List a just-bought hotbar item on the AH at a competitive undercut.

Casual: Esc out, grab slot 1, /ah sell for 100k under the real market.
"""

from __future__ import annotations

import logging
from typing import Any

from ah_price.pricing.ah_price_formatter import AhPriceFormatter
from ah_price.config import ARMOR_ARB_SELL_HOTBAR_SLOT
from ah_price.automation.input_manager import InputManager
from ah_price.pricing.sell_price_calculator import SellPriceCalculator, SellPriceDecision

logger = logging.getLogger(__name__)


class SellOrderManager:
    """
    Post-purchase sell: close AH → select hotbar → /ah sell <price>.

    Casual: dump the snag back on the market before we buy anything else.
    Hotbar slot 1 must stay empty between buys so the purchased item always
    lands there. We never queue a second buy while an unsold item sits in hand.
    """

    def __init__(
        self,
        input_manager: InputManager | None = None,
        price_calculator: SellPriceCalculator | None = None,
        price_formatter: AhPriceFormatter | None = None,
        hotbar_slot: int = ARMOR_ARB_SELL_HOTBAR_SLOT,
    ) -> None:
        self._input = input_manager or InputManager()
        self._calculator = price_calculator or SellPriceCalculator()
        self._formatter = price_formatter or AhPriceFormatter()
        self._hotbar_slot = int(hotbar_slot)
        if self._hotbar_slot < 1 or self._hotbar_slot > 9:
            raise ValueError(
                f"hotbar_slot must be 1..9, got {self._hotbar_slot}"
            )

    def would_profit_after_buy(
        self,
        listings: list[dict[str, Any]],
        purchased_slot: int,
        buy_coins: int,
    ) -> tuple[bool, SellPriceDecision | None]:
        """
        Check that planned sell is strictly above the buy price.

        Casual: don't buy if we'd just relist at the same number.
        """
        return self._calculator.would_profit(
            listings, purchased_slot, buy_coins
        )

    def sell_purchased_item(
        self,
        listings: list[dict[str, Any]],
        purchased_slot: int,
        *,
        escape_ah_first: bool = True,
        decision: SellPriceDecision | None = None,
    ) -> dict[str, Any]:
        """
        Close the AH if needed, select the buy hotbar, list at undercut.

        Casual: get out of the menu and slap the item back up for sale.
        Returns a status dict for the armor-arb report (sold / price / etc.).
        Pass ``decision`` when the pre-buy profit check already priced the
        sell so we don't recompute (and can't disagree with the skip gate).
        """
        # Always leave the AH results GUI before chat/hotbar work — even when
        # we cannot price the sell — so the next /ah search can type cleanly.
        if escape_ah_first:
            print("Closing AH before sell — Esc")
            self._input.press_escape()

        if decision is None:
            decision = self._calculator.decide(listings, purchased_slot)
        if decision is None:
            print(
                "Sell skipped — could not compute a competitive sell price "
                "from the compare row."
            )
            return {
                "sold": False,
                "reason": "no_sell_price",
                "decision": None,
            }

        price_text = self._formatter.format_coins(decision.sell_coins)
        self._print_decision(decision, price_text)

        self._input.select_hotbar_slot(self._hotbar_slot)
        self._input.open_ah_sell(price_text)

        return {
            "sold": True,
            "reason": "ok",
            "price_text": price_text,
            "decision": self._decision_to_dict(decision),
            "hotbar_slot": self._hotbar_slot,
        }

    @staticmethod
    def _print_decision(decision: SellPriceDecision, price_text: str) -> None:
        skip_note = (
            f", skipped {decision.skipped_outlier_count} outlier(s)"
            if decision.skipped_outlier_count
            else ""
        )
        print(
            "Sell price: "
            f"{price_text} ({decision.sell_coins:,}) = "
            f"ref {decision.reference_coins:,} - undercut"
            f"{skip_note}; market median {decision.market_price:,}"
        )

    @staticmethod
    def _decision_to_dict(decision: SellPriceDecision) -> dict[str, Any]:
        return {
            "sell_coins": decision.sell_coins,
            "reference_coins": decision.reference_coins,
            "market_price": decision.market_price,
            "skipped_outlier_count": decision.skipped_outlier_count,
        }
