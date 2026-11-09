"""
Parse recognized HUD strings into structured username / balance values.
"""

from __future__ import annotations

import re


class BalanceParser:
    """
    Turn strings like '$ 52.1M' into integer balance amounts.

    Casual: reads the money text and converts K/M/B into a plain number.
    """

    _SUFFIX_MULTIPLIERS: dict[str, int] = {
        "K": 1_000,
        "M": 1_000_000,
        "B": 1_000_000_000,
    }

    _BALANCE_PATTERN = re.compile(
        r"^\s*\$?\s*(?P<number>\d+(?:\.\d+)?)\s*(?P<suffix>[KMB])?\s*$",
        re.IGNORECASE,
    )

    def parse_balance(self, raw: str) -> int:
        """
        Strip '$', whitespace, parse number + optional K/M/B suffix → int.

        Casual: '$ 52.1M' becomes 52100000.
        Uses round() after multiplying so decimals like 52.1M land cleanly.
        """
        cleaned = raw.strip()
        if not cleaned:
            return 0

        match = self._BALANCE_PATTERN.match(cleaned)
        if not match:
            # Lenient pass: remove everything except digits, dot, suffix letter.
            digits = re.sub(r"[^\d.KMB]", "", cleaned.upper())
            match = self._BALANCE_PATTERN.match(digits)

        if not match:
            raise ValueError(f"Could not parse balance from: {raw!r}")

        number = float(match.group("number"))
        suffix = (match.group("suffix") or "").upper()
        multiplier = self._SUFFIX_MULTIPLIERS.get(suffix, 1)
        return int(round(number * multiplier))

    @staticmethod
    def join_username(glyphs: str) -> str:
        """
        Normalize a recognized username string.

        Casual: glue letters together and keep only valid MC name chars.
        """
        allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
        return "".join(ch for ch in glyphs if ch in allowed)
