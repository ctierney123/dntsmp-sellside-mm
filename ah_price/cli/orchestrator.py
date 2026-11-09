"""
End-to-end AH price test: chat → search → hover → OCR → print.

Casual: the one-shot script that actually tries to read an item price.
Coordinates InputManager + TooltipPriceReader. Vision-only mode lets you
skip the keyboard and just hover an item yourself.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ah_price.config import (
    FOCUS_COUNTDOWN_SECONDS,
    ITEM_HOVER_XY,
)
from ah_price.automation.input_manager import InputManager
from ah_price.automation.query_normalizer import AhSearchQueryNormalizer
from ah_price.tooltip.tooltip_price_reader import TooltipPriceReader

logger = logging.getLogger(__name__)


class AhPriceTestOrchestrator:
    """
    Wires input + tooltip OCR into a runnable AH price test.

    Casual: press T, search, hover, print the price.
    Supports --vision-only so you can test dollar locate / OCR without typing.
    """

    def __init__(
        self,
        query: str | None = None,
        hover_xy: tuple[int, int] | None = None,
        countdown_seconds: float = FOCUS_COUNTDOWN_SECONDS,
        save_debug: bool = True,
    ) -> None:
        self._query = AhSearchQueryNormalizer.normalize(query)
        self._hover_xy = hover_xy or ITEM_HOVER_XY
        self._countdown = countdown_seconds
        self._input = InputManager()
        self._reader = TooltipPriceReader(save_debug=save_debug)

    def run_full(self) -> dict[str, Any]:
        """
        Full automation: focus countdown → /ah search → hover → read price.

        Casual: the real end-to-end test. Click Minecraft during the countdown.
        """
        self._countdown_to_minecraft()
        self._input.open_ah_search(self._query)
        self._input.hover_item(self._hover_xy)
        return self._read_and_print()

    def run_vision_only(self) -> dict[str, Any]:
        """
        Skip typing — assume AH is open and the mouse is already on an item.

        Casual: hover manually, then let OCR prove it can find the $.
        Still does a short countdown so you can alt-tab back into MC if needed.
        """
        print(
            "Vision-only mode: hover the AH item now. "
            f"Reading tooltip in {self._countdown:.0f}s..."
        )
        self._sleep_countdown(self._countdown)
        return self._read_and_print()

    def _read_and_print(self) -> dict[str, Any]:
        """Capture, OCR, print, and return the price dict (sans DollarMatch)."""
        result = self._reader.read_price()
        printable = {
            "price_raw": result["price_raw"],
            "price": result["price"],
        }
        dollar = result.get("dollar")
        if dollar is not None:
            printable["dollar_xy_upscaled"] = (dollar.x, dollar.y)
            printable["dollar_score"] = round(dollar.score, 3)

        print(printable)
        return printable

    def _countdown_to_minecraft(self) -> None:
        """
        Give the user time to click into Minecraft before keyspam starts.

        Casual: 3…2…1… don't type into the wrong window.
        """
        print(
            f"Click into Minecraft now — starting in {self._countdown:.0f}s "
            f"(query={self._query!r}, hover={self._hover_xy})"
        )
        self._sleep_countdown(self._countdown)

    @staticmethod
    def _sleep_countdown(seconds: float) -> None:
        remaining = int(seconds)
        while remaining > 0:
            print(f"  {remaining}...", flush=True)
            time.sleep(1.0)
            remaining -= 1
        # Fractional leftover (e.g. 3.5 → sleep 0.5 after the 3s loop).
        frac = seconds - int(seconds)
        if frac > 0:
            time.sleep(frac)

    def close(self) -> None:
        self._reader.close()
