"""
Turn a raw HUD crop into a clean binary image ready for template matching.
"""

from __future__ import annotations

import cv2
import numpy as np

from screen_reader.config import SCALE_FACTOR


class ImagePreprocessor:
    """
    Upscale + threshold Minecraft HUD text so glyphs pop off the background.

    Casual: makes tiny pixel text big and black-and-white for matching.
    Nearest-neighbor upscale preserves crisp pixels; a high brightness cutoff
    keeps white (and green '$') strokes while dropping the ~25% drop shadow.
    """

    def __init__(
        self,
        scale_factor: int = SCALE_FACTOR,
        brightness_threshold: int = 160,
    ) -> None:
        self._scale = scale_factor
        self._threshold = brightness_threshold

    @property
    def scale_factor(self) -> int:
        return self._scale

    def preprocess(self, bgr: np.ndarray) -> np.ndarray:
        """
        Return a single-channel binary image: 255 = glyph pixel, 0 = background.

        Casual: zoom in, then keep only the bright text pixels.
        """
        upscaled = self._upscale_nearest(bgr)
        gray = self._luminance(upscaled)
        binary = self._threshold_glyphs(gray)
        return binary

    def _upscale_nearest(self, bgr: np.ndarray) -> np.ndarray:
        """Scale up with INTER_NEAREST so Minecraft font pixels stay square."""
        if self._scale <= 1:
            return bgr
        height, width = bgr.shape[:2]
        new_w = width * self._scale
        new_h = height * self._scale
        return cv2.resize(bgr, (new_w, new_h), interpolation=cv2.INTER_NEAREST)

    def _luminance(self, bgr: np.ndarray) -> np.ndarray:
        """
        Per-pixel brightness that still catches the green '$'.

        White digits: all channels high. Green '$': G channel dominates.
        We take max(R, G, B) so both survive preprocessing.
        """
        b, g, r = cv2.split(bgr)
        return np.maximum(np.maximum(r, g), b).astype(np.uint8)

    def _threshold_glyphs(self, gray: np.ndarray) -> np.ndarray:
        """
        High threshold → main glyph strokes only.

        Drop shadow is offset 1px down-right at ~25% brightness (~64 on 0–255).
        Main text is ~255 white or bright green, so threshold ~160 excludes shadow.
        """
        _, binary = cv2.threshold(gray, self._threshold, 255, cv2.THRESH_BINARY)
        return binary
