"""
Build Minecraft chat commands for sell (/ah) and buy (/order) books.

Casual: turn an item name into the two commands we paste into chat.
"""

from __future__ import annotations


class MarketMakingCommandBuilder:
    """
    Formats /ah and /order chat strings from a bare item name.

    Casual: "enchanted golden apple" → the two book-open commands.
    Sell listings live under ``/ah <item>``; buy orders under ``/order <item>``.
    Slot 0 on each book is the best price for that side (cheapest ask /
    highest bid).
    """

    def sell_book_command(self, item_name: str) -> str:
        """
        Build the sell-book search command.

        Casual: ``/ah enchanted golden apple``.
        """
        return f"/ah {self._clean_item_name(item_name)}"

    def buy_book_command(self, item_name: str) -> str:
        """
        Build the buy-book search command.

        Casual: ``/order enchanted golden apple``.
        """
        return f"/order {self._clean_item_name(item_name)}"

    @staticmethod
    def _clean_item_name(item_name: str) -> str:
        """
        Strip whitespace / accidental slash prefixes from a user item name.

        Casual: tidy whatever you typed so we don't double up /ah.
        Accepts bare names, ``/ah …``, ``ah …``, ``/order …``, etc., and
        returns just the item words.
        """
        cleaned = str(item_name).strip()
        if not cleaned:
            raise ValueError("item name must be non-empty")

        # Drop a leading slash so "/ah foo" and "ah foo" share one path.
        if cleaned.startswith("/"):
            cleaned = cleaned[1:].lstrip()

        lower = cleaned.lower()
        for prefix in ("ah ", "order "):
            if lower.startswith(prefix):
                cleaned = cleaned[len(prefix) :].lstrip()
                break

        cleaned = cleaned.strip()
        if not cleaned:
            raise ValueError("item name must be non-empty after stripping commands")
        return cleaned
