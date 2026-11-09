"""
Capture a binary AH tooltip fingerprint for own-listing checks.

Casual: hover the slot, screenshot the tip, make a fingerprint.
"""

from __future__ import annotations

import logging
import time

import numpy as np
import pyautogui

from ah_price.config import (
    COMPARE_MOUSE_MOVE_DURATION_SECONDS,
    COMPARE_PYAUTOGUI_PAUSE_SECONDS,
    OWN_LISTING_FINGERPRINT_HOVER_DELAY_SECONDS,
)
from ah_price.scan.slot_grid_manager import SlotGridManager
from ah_price.tooltip.tooltip_fingerprint_matcher import TooltipFingerprintMatcher
from ah_price.tooltip.tooltip_price_reader import TooltipPriceReader

logger = logging.getLogger(__name__)


class OwnListingFingerprintCaptureManager:
    """
    Re-hover a listing slot and grab a binary tooltip fingerprint.

    Casual: park on the snag, snap the tip, hand it to the tracker.
    Uses the same tooltip ROI shift as price compare so the crop lines up
    with what we would have seen during the row scan.
    """

    def __init__(
        self,
        grid: SlotGridManager | None = None,
        reader: TooltipPriceReader | None = None,
        matcher: TooltipFingerprintMatcher | None = None,
        hover_delay_seconds: float = OWN_LISTING_FINGERPRINT_HOVER_DELAY_SECONDS,
        mouse_move_duration: float = COMPARE_MOUSE_MOVE_DURATION_SECONDS,
    ) -> None:
        self._grid = grid or SlotGridManager()
        # save_debug off — fingerprint grabs are frequent and shouldn't spam PNGs.
        self._reader = reader or TooltipPriceReader(save_debug=False)
        self._matcher = matcher or TooltipFingerprintMatcher()
        self._hover_delay = float(hover_delay_seconds)
        self._mouse_move_duration = float(mouse_move_duration)
        self._owns_reader = reader is None

    def capture_for_hover(self, hover_xy: tuple[int, int]) -> np.ndarray | None:
        """
        Hover ``hover_xy``, capture TOOLTIP_REGION (shifted), return binary.

        Casual: look at that listing and photograph the tooltip.
        Returns None when capture fails (caller should not skip on price alone
        unless the tracker already has an unclaimed sell — see tracker).
        """
        previous_pause = pyautogui.PAUSE
        pyautogui.PAUSE = COMPARE_PYAUTOGUI_PAUSE_SECONDS
        try:
            pyautogui.moveTo(
                hover_xy[0],
                hover_xy[1],
                duration=self._mouse_move_duration,
            )
            if self._hover_delay > 0:
                time.sleep(self._hover_delay)

            region = self._grid.tooltip_region_for_hover(hover_xy)
            frame = self._reader.capture_bgr(region)
            binary = self._matcher.to_binary(frame)
            logger.debug(
                "Captured own-listing fingerprint at %s shape=%s",
                hover_xy,
                binary.shape,
            )
            return binary
        except Exception as exc:
            logger.warning(
                "Own-listing fingerprint capture failed at %s: %s",
                hover_xy,
                exc,
            )
            return None
        finally:
            pyautogui.PAUSE = previous_pause

    def close(self) -> None:
        """Release the tooltip reader if we created it."""
        if self._owns_reader:
            self._reader.close()
