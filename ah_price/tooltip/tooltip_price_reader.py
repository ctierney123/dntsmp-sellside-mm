"""
Read the auction price on the line that starts with $.

Casual: once we know where the $ is, grab the text to its right and OCR it.
Supports a fast two-stage path: locate $ in a tall narrow column, then OCR
only a tiny price-line crop. Builds on LineRecognizer + BalanceParser.
"""

from __future__ import annotations

import logging
from typing import Any

import cv2
import numpy as np
from PIL import Image

from ah_price.config import (
    AH_SCALE_FACTOR,
    PRICE_LINE_PAD_PX,
    PRICE_STRIP_DEBUG_IMAGE,
    PRICE_STRIP_MAX_WIDTH_PX,
    TOOLTIP_DEBUG_IMAGE,
    TOOLTIP_REGION,
)
from ah_price.tooltip.dollar_locator import DollarLocator, DollarMatch
from ah_price.tooltip.price_band_tracker import PriceBandTracker
from screen_reader.capture_manager import ScreenCaptureManager
from screen_reader.config import BALANCE_CHARSET, SCALE_FACTOR
from screen_reader.glyph_atlas import GlyphAtlas
from screen_reader.parser import BalanceParser
from screen_reader.preprocessor import ImagePreprocessor
from screen_reader.recognizer import LineRecognizer

logger = logging.getLogger(__name__)

# Prefer digits/suffix; `$` may still appear in the crop and is in the atlas.
_PRICE_DIGIT_CHARSET: str = "$0123456789.KMB "


class TooltipPriceReader:
    """
    Capture tooltip pixels, find $, OCR the price strip, parse to int.

    Casual: hover an item, then ask this class what it costs.
    Uses AH_SCALE_FACTOR (often 2) so multi-slot compares stay cheap; HUD
    reader keeps its own SCALE_FACTOR.
    """

    def __init__(
        self,
        region: dict[str, int] | None = None,
        save_debug: bool = True,
        scale_factor: int = AH_SCALE_FACTOR,
    ) -> None:
        self._region = dict(region or TOOLTIP_REGION)
        self._save_debug = save_debug
        self._scale = max(1, scale_factor)
        self._capture = ScreenCaptureManager(self._region)
        self._preprocessor = ImagePreprocessor(scale_factor=self._scale)
        self._locator = DollarLocator(scale_factor=self._scale)
        self._band = PriceBandTracker(scale_factor=self._scale)
        self._atlas = GlyphAtlas()
        self._atlas.load()
        # OCR templates are authored at HUD SCALE_FACTOR; rescale for AH zoom.
        self._price_templates = self._rescale_balance_templates(
            self._atlas.balance_templates,
            native_scale=SCALE_FACTOR,
            target_scale=self._scale,
        )
        self._recognizer = LineRecognizer(self._atlas)
        self._parser = BalanceParser()

    @property
    def region(self) -> dict[str, int]:
        return dict(self._region)

    @property
    def scale_factor(self) -> int:
        return self._scale

    def read_price(self, region: dict[str, int] | None = None) -> dict[str, Any]:
        """
        One-shot: screenshot region → find $ → OCR price → return dict.

        Casual: "what's the price on the item I'm hovering?"
        Used for slot-0 full ROI and as a fallback when two-stage fails.
        """
        active_region = dict(region) if region is not None else self._region
        frame = self._capture_region(active_region)
        if self._save_debug:
            self._write_bgr(TOOLTIP_DEBUG_IMAGE, frame)

        binary = self._preprocessor.preprocess(frame)
        dollar = self._locator.locate(frame, active_region, binary=binary)
        if dollar is None:
            raise RuntimeError(
                "Could not find a non-HUD $ in TOOLTIP_REGION. "
                "Widen the region, re-hover the item, or check dollar.png."
            )

        strip = self._extract_price_strip(binary, dollar)
        if self._save_debug:
            self._write_gray(PRICE_STRIP_DEBUG_IMAGE, strip)

        return self._ocr_price_strip(strip, dollar)

    def read_price_two_stage(
        self,
        dollar_column_region: dict[str, int],
    ) -> dict[str, Any]:
        """
        Fast path: one tall narrow strip → find $ → OCR digits from same frame.

        Casual: skinny full-height grab that already includes `$4.5M`, then crop.
        Named two-stage for API compatibility; the second "stage" is an in-memory
        crop (no second mss screenshot) so we stay fast.
        """
        column_frame = self._capture_region(dollar_column_region)
        if self._save_debug:
            self._write_bgr(TOOLTIP_DEBUG_IMAGE, column_frame)

        column_binary = self._preprocessor.preprocess(column_frame)
        dollar = self._locator.locate(
            column_frame,
            dollar_column_region,
            binary=column_binary,
        )
        if dollar is None:
            raise RuntimeError(
                "Could not find $ in dollar column — tooltip may not be ready."
            )

        strip = self._extract_price_strip(column_binary, dollar)
        if self._save_debug:
            self._write_gray(PRICE_STRIP_DEBUG_IMAGE, strip)

        result = self._ocr_price_strip(strip, dollar)
        result["dollar_column_region"] = dict(dollar_column_region)
        return result

    def count_green_pixels(self, region: dict[str, int]) -> int:
        """
        Cheap tooltip-ready check: how many green-ish pixels are in ``region``.

        Casual: peek for green money color without running full $ OCR.
        Used by the compare loop to wait for the tip to paint.
        """
        frame = self._capture_region(region)
        return int(self._locator.count_green_pixels(frame))

    def capture_bgr(self, region: dict[str, int] | None = None) -> np.ndarray:
        """
        Screenshot a tooltip ROI as BGR without running OCR.

        Casual: just grab the tip pixels (for fingerprints / debug).
        Used by own-listing checks that need a visual match, not a price.
        """
        active_region = dict(region) if region is not None else self._region
        return self._capture_region(active_region)

    def _ocr_price_strip(
        self,
        strip: np.ndarray,
        dollar: DollarMatch,
    ) -> dict[str, Any]:
        """
        Glyph-OCR a binary price strip and parse to an int.

        Casual: turn the money pixels into `$4.3M` → 4300000.
        """
        raw = self._recognizer.recognize_line(
            strip,
            charset=_PRICE_DIGIT_CHARSET,
            templates=self._price_templates,
        )
        price_raw = raw.strip()
        if price_raw and not price_raw.lstrip().startswith("$"):
            price_raw = f"${price_raw}"

        price = self._parser.parse_balance(price_raw)
        logger.info("AH price raw=%r → %s", price_raw, price)
        return {
            "price_raw": price_raw,
            "price": price,
            "dollar": dollar,
        }

    def _capture_region(self, region: dict[str, int]) -> np.ndarray:
        """Point mss at ``region`` and grab one BGR frame."""
        self._capture.set_region(region)
        return self._capture.capture()

    def _extract_price_strip(
        self,
        binary: np.ndarray,
        dollar: DollarMatch,
    ) -> np.ndarray:
        """
        Crop the horizontal band to the right of the matched $.

        Casual: cut out just the money numbers on that line.
        """
        pad = PRICE_LINE_PAD_PX * self._scale
        max_w = PRICE_STRIP_MAX_WIDTH_PX * self._scale

        y0 = max(0, dollar.y - pad)
        y1 = min(binary.shape[0], dollar.y + dollar.height + pad)
        # Include `$` so the parser sees a leading dollar when OCR keeps it.
        x0 = max(0, dollar.x)
        x1 = min(binary.shape[1], x0 + max_w)

        strip = binary[y0:y1, x0:x1]
        if strip.size == 0:
            raise RuntimeError("Price strip crop was empty — check $ location / padding.")
        return strip

    @staticmethod
    def _rescale_balance_templates(
        templates: dict[str, np.ndarray],
        native_scale: int,
        target_scale: int,
    ) -> dict[str, np.ndarray]:
        """
        Nearest-neighbor rescale atlas glyphs from HUD scale → AH scale.

        Casual: shrink the letter stickers so they match our cheaper zoom.
        """
        native = max(1, native_scale)
        target = max(1, target_scale)
        if native == target:
            return dict(templates)

        ratio = target / native
        out: dict[str, np.ndarray] = {}
        for char, template in templates.items():
            new_w = max(1, int(round(template.shape[1] * ratio)))
            new_h = max(1, int(round(template.shape[0] * ratio)))
            resized = cv2.resize(
                template,
                (new_w, new_h),
                interpolation=cv2.INTER_NEAREST,
            )
            _, binary = cv2.threshold(resized, 127, 255, cv2.THRESH_BINARY)
            out[char] = binary
        return out

    @staticmethod
    def _write_bgr(path, bgr: np.ndarray) -> None:
        """Save a BGR debug frame as PNG."""
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        Image.fromarray(rgb).save(path)
        logger.debug("Wrote debug image %s", path)

    @staticmethod
    def _write_gray(path, gray: np.ndarray) -> None:
        """Save a single-channel debug strip as PNG."""
        Image.fromarray(gray).save(path)
        logger.debug("Wrote debug strip %s", path)

    def close(self) -> None:
        """Release the capture handle."""
        self._capture.close()
