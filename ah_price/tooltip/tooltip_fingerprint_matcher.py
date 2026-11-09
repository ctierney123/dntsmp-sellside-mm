"""
Compare two AH tooltip screenshots for near-identical listings.

Casual: do these two tip pictures look like the same item?
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

from ah_price.config import (
    AH_SCALE_FACTOR,
    OWN_LISTING_TOOLTIP_MATCH_THRESHOLD,
)
from screen_reader.preprocessor import ImagePreprocessor

logger = logging.getLogger(__name__)


class TooltipFingerprintMatcher:
    """
    Near-1:1 binary tooltip compare via normalized cross-correlation.

    Casual: score how alike two tooltip crops are (price + enchants).
    We preprocess to the same binary Minecraft look the OCR stack uses, then
    require a high ``TM_CCOEFF_NORMED`` peak. Same-size crops use a direct
    score; if sizes differ slightly (hover jitter), the smaller is matched
    as a template inside the larger.
    """

    def __init__(
        self,
        match_threshold: float = OWN_LISTING_TOOLTIP_MATCH_THRESHOLD,
        preprocessor: ImagePreprocessor | None = None,
        scale_factor: int = AH_SCALE_FACTOR,
    ) -> None:
        if not 0.0 <= match_threshold <= 1.0:
            raise ValueError(
                f"match_threshold must be in [0, 1], got {match_threshold}"
            )
        self._threshold = float(match_threshold)
        # Match AH tooltip OCR scale so fingerprints line up with price crops.
        self._preprocessor = preprocessor or ImagePreprocessor(
            scale_factor=scale_factor
        )

    @property
    def match_threshold(self) -> float:
        return self._threshold

    def to_binary(self, bgr_frame: np.ndarray) -> np.ndarray:
        """
        Turn a BGR tooltip crop into the binary fingerprint form.

        Casual: same black/white prep we use for reading prices.
        """
        return self._preprocessor.preprocess(bgr_frame)

    def is_same_listing(
        self,
        stored_binary: np.ndarray,
        candidate_binary: np.ndarray,
    ) -> tuple[bool, float]:
        """
        Decide if two binary tooltips are the same listing.

        Casual: near-perfect visual match → it's probably ours.
        Returns ``(matched, score)`` so callers can log the confidence.
        """
        score = self.similarity(stored_binary, candidate_binary)
        matched = score >= self._threshold
        logger.debug(
            "Tooltip fingerprint score=%.4f threshold=%.4f matched=%s",
            score,
            self._threshold,
            matched,
        )
        return matched, score

    def similarity(
        self,
        stored_binary: np.ndarray,
        candidate_binary: np.ndarray,
    ) -> float:
        """
        Peak normalized correlation between two binary tooltip crops.

        Casual: 1.0 = identical pixels; ~0 = totally different tips.
        """
        a = self._ensure_2d_uint8(stored_binary)
        b = self._ensure_2d_uint8(candidate_binary)
        if a.size == 0 or b.size == 0:
            return 0.0

        # Prefer treating the smaller crop as the template so slight ROI
        # shifts still find a peak instead of failing on shape mismatch.
        if a.shape[0] * a.shape[1] <= b.shape[0] * b.shape[1]:
            template, haystack = a, b
        else:
            template, haystack = b, a

        th, tw = template.shape[:2]
        hh, hw = haystack.shape[:2]
        if hh < th or hw < tw:
            return 0.0

        # Exact same shape → one correlation value; else slide template.
        if th == hh and tw == hw:
            result = cv2.matchTemplate(haystack, template, cv2.TM_CCOEFF_NORMED)
            return float(result[0, 0])

        result = cv2.matchTemplate(haystack, template, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, _max_loc = cv2.minMaxLoc(result)
        return float(max_val)

    @staticmethod
    def _ensure_2d_uint8(frame: np.ndarray) -> np.ndarray:
        """
        Coerce to a single-channel uint8 image for matchTemplate.

        Casual: make sure OpenCV gets a plain gray/binary matrix.
        """
        if frame.ndim == 3:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if frame.dtype != np.uint8:
            frame = frame.astype(np.uint8)
        return frame
