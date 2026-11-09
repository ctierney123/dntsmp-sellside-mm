"""
Grab pixels from the screen — read-only, never touches keyboard or mouse.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import mss
import numpy as np

if TYPE_CHECKING:
    from screen_reader.config import CAPTURE_REGION as CaptureRegionType


class ScreenCaptureManager:
    """
    Pulls a rectangular slice of the monitor into a BGR numpy array.

    Casual: screenshots one box on your screen, fast.
    Uses mss for low-latency capture; only reads display memory, never injects input.
    """

    def __init__(self, region: dict[str, int]) -> None:
        # Region dict matches mss monitor format: left, top, width, height.
        self._region = dict(region)
        self._sct = mss.mss()

    @property
    def region(self) -> dict[str, int]:
        """Current capture rectangle (copy)."""
        return dict(self._region)

    def set_region(self, region: dict[str, int]) -> None:
        """
        Point the next grab at a different screen rectangle.

        Casual: move the screenshot box without rebuilding mss.
        Used when AH tooltips follow the cursor across listing slots.
        """
        self._region = dict(region)

    def capture(self) -> np.ndarray:
        """
        Capture the configured region and return BGR uint8 array (H, W, 3).

        Casual: one screenshot of the HUD box.
        """
        raw = self._sct.grab(self._region)
        # mss gives BGRA; drop alpha and keep BGR for OpenCV.
        frame = np.array(raw, dtype=np.uint8)
        return frame[:, :, :3].copy()

    def capture_full_screen(self, width: int = 1920, height: int = 1080) -> np.ndarray:
        """
        Capture the primary monitor at the given resolution (calibration helper).

        Casual: full-screen shot for finding coordinates.
        """
        monitor = {"left": 0, "top": 0, "width": width, "height": height}
        raw = self._sct.grab(monitor)
        frame = np.array(raw, dtype=np.uint8)
        return frame[:, :, :3].copy()

    def close(self) -> None:
        """Release mss resources."""
        self._sct.close()
