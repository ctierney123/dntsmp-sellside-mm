"""
Format integer coin amounts for DonutSMP /ah sell chat commands.

Casual: turn 7600000 into the '7.6m' string chat expects.
"""

from __future__ import annotations


class AhPriceFormatter:
    """
    Converts raw coin ints into compact K/M/B chat suffixes.

    Casual: pretty-print money the way /ah sell wants it.
    Matches the HUD / tooltip style (``7.6m``, ``100k``, ``1.2b``) so we
    can paste the string straight into ``/ah sell <price>``.
    """

    def format_coins(self, coins: int) -> str:
        """
        Render coins as a compact suffix string (no leading $).

        Casual: 7_600_000 → '7.6m'.
        Uses lowercase suffixes to match common DonutSMP chat examples.
        Trailing ``.0`` is stripped (``7_000_000`` → ``7m``, not ``7.0m``).
        """
        amount = int(coins)
        if amount < 0:
            raise ValueError(f"coin amount must be non-negative, got {amount}")

        if amount >= 1_000_000_000:
            return self._with_suffix(amount / 1_000_000_000, "b")
        if amount >= 1_000_000:
            return self._with_suffix(amount / 1_000_000, "m")
        if amount >= 1_000:
            return self._with_suffix(amount / 1_000, "k")
        return str(amount)

    @staticmethod
    def _with_suffix(scaled: float, suffix: str) -> str:
        """
        One-decimal compact form, dropping a useless trailing .0.

        Casual: 7.0 → '7m', 7.6 → '7.6m'.
        """
        # Round to one decimal so 7.599999 float noise doesn't leak into chat.
        rounded = round(scaled, 1)
        if abs(rounded - int(rounded)) < 1e-9:
            return f"{int(rounded)}{suffix}"
        # Normalize 7.60 → 7.6
        text = f"{rounded:.1f}".rstrip("0").rstrip(".")
        return f"{text}{suffix}"
