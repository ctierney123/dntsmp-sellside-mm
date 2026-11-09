"""
Normalize user-provided AH chat commands before typing into Minecraft.

Casual: makes sure your query is a real slash command, not plain chat text.
"""

from __future__ import annotations

from ah_price.config import AH_SEARCH_QUERY


class AhSearchQueryNormalizer:
    """
    Turns loose CLI queries into valid Minecraft /ah commands.

    Casual: adds the missing slash (and /ah when you only pass an item name).
  If you pass ``netherite chestplate`` we type ``/ah netherite chestplate``.
    """

    @staticmethod
    def normalize(query: str | None, *, default: str = AH_SEARCH_QUERY) -> str:
        """
        Ensure the query is a slash command suitable for Auction House search.

        Casual: prepends ``/`` when missing; bare item names get ``/ah `` too.

        Rules:
          - Empty / whitespace → ``default`` (from config).
          - No leading ``/`` → prepend ``/``.
          - After ``/``, if the text does not start with ``ah`` (command word),
            insert ``ah `` so ``/netherite`` becomes ``/ah netherite``.
          - Already ``/ah …`` or ``ah …`` (after slash fix) → left alone.
        """
        if query is None or not str(query).strip():
            return default

        q = str(query).strip()

        # Minecraft commands must start with / or they post as public chat.
        if not q.startswith("/"):
            q = "/" + q

        # Strip the slash and any spaces so we can inspect the command word.
        body = q[1:].lstrip()
        lower_body = body.lower()

        # "ah", "ah foo", "/ah foo" (after slash fix) are already AH commands.
        is_ah_command = lower_body == "ah" or lower_body.startswith("ah ")
        if not is_ah_command:
            q = "/ah " + body

        return q
