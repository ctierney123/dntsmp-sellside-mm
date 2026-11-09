"""
Orchestrates capture → preprocess → recognize → parse for one HUD read.
"""

from __future__ import annotations

import logging
from typing import Any

import cv2
import numpy as np

from screen_reader.capture_manager import ScreenCaptureManager
from screen_reader.config import (
    BALANCE_CHARSET,
    CAPTURE_REGION,
    USERNAME_CHARSET,
)
from screen_reader.glyph_atlas import GlyphAtlas
from screen_reader.glyph_segmenter import GlyphSegmenter
from screen_reader.parser import BalanceParser
from screen_reader.preprocessor import ImagePreprocessor
from screen_reader.recognizer import LineRecognizer

logger = logging.getLogger(__name__)


class HudReader:
    """
    High-level reader: one call = one screenshot + parsed username/balance.

    Casual: the main gadget — grabs the HUD box and tells you name + money.
    Completely passive: screen capture only, no input injection, no network.
    """

    def __init__(
        self,
        region: dict[str, int] | None = None,
        use_tesseract: bool = False,
    ) -> None:
        self._capture = ScreenCaptureManager(region or CAPTURE_REGION)
        self._preprocessor = ImagePreprocessor()
        self._segmenter = GlyphSegmenter()
        self._atlas = GlyphAtlas()
        self._atlas.load()
        self._recognizer = LineRecognizer(self._atlas, use_tesseract=use_tesseract)
        self._parser = BalanceParser()

    def capture(self) -> np.ndarray:
        """Grab raw BGR pixels for the configured HUD region."""
        return self._capture.capture()

    def preprocess(self, bgr: np.ndarray) -> np.ndarray:
        """Upscale + binarize a BGR crop."""
        return self._preprocessor.preprocess(bgr)

    def read_once(self) -> dict[str, Any]:
        """
        Single passive read cycle.

        Casual: screenshot once, return username + balance dict.

        Returns
        -------
        {"username": str, "balance_raw": str, "balance": int}
        """
        frame = self.capture()
        binary = self.preprocess(frame)
        lines = self._segmenter.split_lines(binary)

        if len(lines) < 2:
            raise RuntimeError(
                f"Expected 2 HUD text lines (username + balance), found {len(lines)}. "
                "Check CAPTURE_REGION and GUI scale."
            )

        username_raw = self.recognize_line(
            lines[0],
            charset=USERNAME_CHARSET,
            templates=self._atlas.username_templates,
        )
        balance_raw = self.recognize_line(
            lines[1],
            charset=BALANCE_CHARSET,
            templates=self._atlas.balance_templates,
        )

        username = self._parser.join_username(username_raw)
        balance = self._parser.parse_balance(balance_raw)

        return {
            "username": username,
            "balance_raw": balance_raw.strip(),
            "balance": balance,
        }

    def recognize_line(
        self,
        binary_line: np.ndarray,
        charset: str,
        templates: dict[str, np.ndarray],
    ) -> str:
        """Expose line recognition for testing / extension."""
        return self._recognizer.recognize_line(binary_line, charset, templates)

    def close(self) -> None:
        self._capture.close()


# Module-level helpers matching the requested function names -----------------

_default_reader: HudReader | None = None


def _get_reader(use_tesseract: bool = False) -> HudReader:
    global _default_reader
    if _default_reader is None or _default_reader._recognizer._use_tesseract != use_tesseract:
        if _default_reader is not None:
            _default_reader.close()
        _default_reader = HudReader(use_tesseract=use_tesseract)
    return _default_reader


def capture() -> np.ndarray:
    """Capture the HUD region (BGR)."""
    return _get_reader().capture()


def preprocess(bgr: np.ndarray) -> np.ndarray:
    """Preprocess a BGR frame to binary."""
    return _get_reader().preprocess(bgr)


def recognize_line(
    binary_line: np.ndarray,
    charset: str,
    templates: dict[str, np.ndarray],
) -> str:
    """Recognize one binary text line."""
    return _get_reader().recognize_line(binary_line, charset, templates)


def parse_balance(raw: str) -> int:
    """Parse a balance string to integer."""
    return BalanceParser().parse_balance(raw)


def read_once(use_tesseract: bool = False) -> dict[str, Any]:
    """One-shot HUD read returning username + balance dict."""
    return _get_reader(use_tesseract=use_tesseract).read_once()
