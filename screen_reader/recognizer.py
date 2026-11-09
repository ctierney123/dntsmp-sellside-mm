"""
Match segmented glyph crops against the template atlas.
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

from screen_reader.config import MATCH_SCORE_THRESHOLD
from screen_reader.glyph_atlas import GlyphAtlas

logger = logging.getLogger(__name__)


class LineRecognizer:
    """
    Turn a binary text line into a string via normalized cross-correlation.

    Casual: compares each letter blob to saved templates and picks the best fit.
    Primary engine is cv2.matchTemplate (TM_CCOEFF_NORMED). Optional Tesseract
    fallback exists but is less accurate — enable only with --use-tesseract.
    """

    def __init__(
        self,
        atlas: GlyphAtlas,
        score_threshold: float = MATCH_SCORE_THRESHOLD,
        use_tesseract: bool = False,
    ) -> None:
        self._atlas = atlas
        self._threshold = score_threshold
        self._use_tesseract = use_tesseract

    def recognize_line(
        self,
        binary_line: np.ndarray,
        charset: str,
        templates: dict[str, np.ndarray] | None = None,
    ) -> str:
        """
        Segment + match one horizontal line of binary text.

        Casual: one row of pixels in → string out.
        """
        from screen_reader.glyph_segmenter import GlyphSegmenter

        segmenter = GlyphSegmenter()
        glyphs = segmenter.segment_line(binary_line)

        if not glyphs:
            if self._use_tesseract:
                return self._tesseract_fallback(binary_line, charset)
            return ""

        template_map = templates or self._pick_templates(charset)
        chars: list[str] = []

        for glyph in glyphs:
            char, score = self._match_glyph(glyph, template_map)
            if char and score >= self._threshold:
                chars.append(char)
            else:
                logger.debug("Low-confidence glyph (best=%s score=%.3f)", char, score)

        result = "".join(chars)

        # Optional fallback when template matching produced nothing useful.
        if self._use_tesseract and len(result) < max(1, len(glyphs) // 2):
            logger.warning("Template match weak; trying Tesseract fallback (less accurate).")
            tess = self._tesseract_fallback(binary_line, charset)
            if len(tess) > len(result):
                return tess

        return result

    def _pick_templates(self, charset: str) -> dict[str, np.ndarray]:
        """Filter loaded templates to characters present in `charset`."""
        merged = {**self._atlas.balance_templates, **self._atlas.username_templates}
        return {ch: merged[ch] for ch in charset if ch in merged}

    def _match_glyph(
        self,
        glyph: np.ndarray,
        templates: dict[str, np.ndarray],
    ) -> tuple[str, float]:
        """
        Compare one glyph crop to every template; return best (char, score).

        Casual: which letter does this blob look most like?
        """
        if not templates:
            return "", 0.0

        best_char = ""
        best_score = -1.0
        glyph_norm = self._normalize_glyph(glyph)

        for char, template in templates.items():
            template_norm = self._normalize_glyph(template)
            score = self._correlation_score(glyph_norm, template_norm)
            if score > best_score:
                best_score = score
                best_char = char

        return best_char, float(best_score)

    def _normalize_glyph(self, img: np.ndarray) -> np.ndarray:
        """
        Pad / resize glyph to a common canvas so templates are comparable.

        Casual: make every letter the same canvas size before comparing.
        """
        if img.size == 0:
            return np.zeros((8, 8), dtype=np.uint8)

        # Trim to bounding box of ink.
        coords = cv2.findNonZero(img)
        if coords is None:
            return np.zeros((8, 8), dtype=np.uint8)

        x, y, w, h = cv2.boundingRect(coords)
        cropped = img[y : y + h, x : x + w]

        # Standard cell: height + small padding (Minecraft glyphs ~7–9 px tall at 1x).
        cell_h = max(h, 8)
        cell_w = max(w, 8)
        canvas = np.zeros((cell_h, cell_w), dtype=np.uint8)
        canvas[0:h, 0:w] = cropped
        return canvas

    def _correlation_score(self, a: np.ndarray, b: np.ndarray) -> float:
        """
        Normalized cross-correlation between two binary-ish glyph images.

        Casual: 1.0 = perfect match, 0 = no match.
        """
        # matchTemplate needs template <= image; pad the smaller one.
        if a.shape[0] > b.shape[0] or a.shape[1] > b.shape[1]:
            big, small = a, b
        else:
            big, small = b, a

        pad_h = max(0, big.shape[0] - small.shape[0])
        pad_w = max(0, big.shape[1] - small.shape[1])
        small_padded = cv2.copyMakeBorder(
            small, 0, pad_h, 0, pad_w, cv2.BORDER_CONSTANT, value=0
        )

        if big.shape[0] < small_padded.shape[0] or big.shape[1] < small_padded.shape[1]:
            big, small_padded = small_padded, big

        result = cv2.matchTemplate(big, small_padded, cv2.TM_CCOEFF_NORMED)
        return float(result.max()) if result.size else 0.0

    def _tesseract_fallback(self, binary_line: np.ndarray, charset: str) -> str:
        """
        LESS ACCURATE fallback — requires pytesseract + Tesseract OCR installed.

        Casual: backup reader when templates fail; don't rely on this for balances.
        """
        try:
            import pytesseract
        except ImportError:
            logger.warning("pytesseract not installed; skipping OCR fallback.")
            return ""

        whitelist = "".join(sorted(set(charset)))
        config = f"--psm 7 -c tessedit_char_whitelist={whitelist}"
        text = pytesseract.image_to_string(binary_line, config=config)
        return text.strip().replace("\n", "").replace(" ", "")
