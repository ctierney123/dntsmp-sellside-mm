"""
Find the green $ glyph inside an Auction House tooltip crop.

Casual: scans the tooltip box for the dollar sign that marks the price.
Ignores any match that sits inside the HUD scoreboard CAPTURE_REGION so we
don't accidentally lock onto the player's own balance $.

Green is a hard requirement for AH price `$`, but other tooltip text
(durability, some armor lines) can also be green — so we never pick "first
green pixel." We AND a green mask into the binary, then still require the
`$` glyph template to win. Matching only runs on green-row bands so a tall
tooltip ROI stays cheap.

Templates are authored at HUD SCALE_FACTOR; AH may run at AH_SCALE_FACTOR
(often 2) — the $ template is nearest-neighbor rescaled to match.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import cv2
import numpy as np

from ah_price.config import (
    AH_SCALE_FACTOR,
    DOLLAR_GREEN_MAX_RB,
    DOLLAR_GREEN_MIN_G,
    DOLLAR_GREEN_MIN_G_MINUS_RB,
    DOLLAR_GREEN_ROW_MIN_PIXELS,
    DOLLAR_MATCH_THRESHOLD,
)
from screen_reader.config import CAPTURE_REGION, SCALE_FACTOR, TEMPLATES_DIR
from screen_reader.glyph_atlas import GlyphAtlas
from screen_reader.preprocessor import ImagePreprocessor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DollarMatch:
    """
    One $ hit inside a tooltip crop (coords are in *upscaled* binary space).

    Casual: "here's where the price dollar lives in the screenshot."
    """

    # Top-left of the template match in the preprocessed (upscaled) image.
    x: int
    y: int
    width: int
    height: int
    score: float

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2


class DollarLocator:
    """
    Template-match the balance `$` glyph across a tooltip / column ROI.

    Casual: look for our known green dollar picture, not just any green text.
    Returns the best hit that is NOT sitting on the scoreboard balance.
    """

    def __init__(
        self,
        match_threshold: float = DOLLAR_MATCH_THRESHOLD,
        hud_region: dict[str, int] | None = None,
        scale_factor: int = AH_SCALE_FACTOR,
        template_native_scale: int = SCALE_FACTOR,
        green_min_g: int = DOLLAR_GREEN_MIN_G,
        green_max_rb: int = DOLLAR_GREEN_MAX_RB,
        green_min_g_minus_rb: int = DOLLAR_GREEN_MIN_G_MINUS_RB,
        green_row_min_pixels: int = DOLLAR_GREEN_ROW_MIN_PIXELS,
    ) -> None:
        self._threshold = match_threshold
        self._hud_region = dict(hud_region or CAPTURE_REGION)
        self._green_min_g = green_min_g
        self._green_max_rb = green_max_rb
        self._green_min_g_minus_rb = green_min_g_minus_rb
        self._green_row_min_pixels = max(1, green_row_min_pixels)
        self._preprocessor = ImagePreprocessor(scale_factor=scale_factor)
        self._atlas = GlyphAtlas(TEMPLATES_DIR)
        self._atlas.load()
        self._dollar_template = self._require_dollar_template(
            scale_factor=scale_factor,
            template_native_scale=template_native_scale,
        )

    @property
    def scale_factor(self) -> int:
        """Upscale factor used for locate() binary space."""
        return self._preprocessor.scale_factor

    def _require_dollar_template(
        self,
        scale_factor: int,
        template_native_scale: int,
    ) -> np.ndarray:
        """
        Pull `$` from the atlas and rescale it to the AH preprocess scale.

        Casual: templates were saved at HUD zoom; shrink/grow to match AH zoom.
        """
        template = self._atlas.balance_templates.get("$")
        if template is None:
            raise FileNotFoundError(
                "Missing $ glyph template (templates/dollar.png). "
                "Run: python -m screen_reader --build-atlas <user> '$ 12.3M'"
            )
        native = max(1, template_native_scale)
        target = max(1, scale_factor)
        if native == target:
            return template

        # Nearest-neighbor keeps Minecraft pixels crisp when downscaling 4→2.
        scale_ratio = target / native
        new_w = max(1, int(round(template.shape[1] * scale_ratio)))
        new_h = max(1, int(round(template.shape[0] * scale_ratio)))
        resized = cv2.resize(template, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
        # Re-binarize after resize so soft edges don't dilute matchTemplate.
        _, binary = cv2.threshold(resized, 127, 255, cv2.THRESH_BINARY)
        logger.debug(
            "Rescaled $ template %sx%s @%dx → %sx%s @%dx",
            template.shape[1],
            template.shape[0],
            native,
            binary.shape[1],
            binary.shape[0],
            target,
        )
        return binary

    def locate(
        self,
        bgr_crop: np.ndarray,
        region: dict[str, int],
        binary: np.ndarray | None = None,
    ) -> DollarMatch | None:
        """
        Find the best non-HUD green `$` in a BGR tooltip crop.

        Casual: screenshot in → dollar position out (or None if no hit).

        Parameters
        ----------
        bgr_crop:
            Raw BGR pixels for the capture region (not yet preprocessed).
            Always used to build the green mask (even when ``binary`` is given).
        region:
            Absolute screen rect of that crop (left/top/width/height) so we
            can map matches back to screen space and skip the HUD box.
        binary:
            Optional preprocessed (upscaled) image. Pass this when the caller
            already thresholded the frame so we don't preprocess twice.
            Price-line OCR should keep using the unmasked binary; only the
            `$` search is green-gated.
        """
        if binary is None:
            binary = self._preprocessor.preprocess(bgr_crop)
        scale = self._preprocessor.scale_factor

        green_mask = self._upscaled_green_mask(bgr_crop, binary.shape, scale)
        if green_mask is None:
            hits = self._match_all(binary)
        else:
            search_binary = cv2.bitwise_and(binary, green_mask)
            hits = self._match_green_row_bands(search_binary, green_mask)

        survivors: list[DollarMatch] = []
        for hit in hits:
            if self._overlaps_hud(hit, region, scale):
                logger.debug(
                    "Skipping $ hit that overlaps HUD at upscaled (%d,%d) score=%.3f",
                    hit.x,
                    hit.y,
                    hit.score,
                )
                continue
            survivors.append(hit)

        if not survivors:
            logger.debug(
                "No non-HUD $ matches found (threshold=%.2f)",
                self._threshold,
            )
            return None

        best = max(survivors, key=lambda h: (h.score, -h.y))
        logger.info(
            "Selected $ at upscaled (%d,%d) score=%.3f (of %d candidates)",
            best.x,
            best.y,
            best.score,
            len(survivors),
        )
        return best

    def count_green_pixels(self, bgr_crop: np.ndarray) -> int:
        """
        Count green-ish pixels in a BGR crop (no upscale / no template match).

        Casual: quick "is the green $ probably on screen yet?" peek.
        """
        return int(np.count_nonzero(self._green_mask_bgr(bgr_crop)))

    def _upscaled_green_mask(
        self,
        bgr_crop: np.ndarray,
        binary_shape: tuple[int, ...],
        scale: int,
    ) -> np.ndarray | None:
        """
        Build a green mask in upscaled binary space, or None if shapes disagree.

        Casual: same green filter, zoomed to match the OCR image.
        """
        green_mask = self._green_mask_bgr(bgr_crop)
        if scale > 1:
            green_mask = cv2.resize(
                green_mask,
                (binary_shape[1], binary_shape[0]),
                interpolation=cv2.INTER_NEAREST,
            )
        if green_mask.shape[:2] != binary_shape[:2]:
            logger.debug(
                "Green mask shape %s != binary %s — skipping green gate",
                green_mask.shape[:2],
                binary_shape[:2],
            )
            return None
        return green_mask

    def _green_mask_bgr(self, bgr: np.ndarray) -> np.ndarray:
        """
        Binary mask of Minecraft-ish green text pixels (G high, R/B lower).

        Casual: "is this pixel the green money color?"
        """
        b = bgr[:, :, 0].astype(np.int16)
        g = bgr[:, :, 1].astype(np.int16)
        r = bgr[:, :, 2].astype(np.int16)
        rb_max = np.maximum(r, b)
        is_green = (
            (g >= self._green_min_g)
            & (rb_max <= self._green_max_rb)
            & ((g - rb_max) >= self._green_min_g_minus_rb)
        )
        return np.where(is_green, np.uint8(255), np.uint8(0))

    def _match_green_row_bands(
        self,
        search_binary: np.ndarray,
        green_mask: np.ndarray,
    ) -> list[DollarMatch]:
        """
        Run `$` template match only on vertical bands that contain green pixels.

        Casual: skip empty tooltip rows; only hunt where green text lives.
        """
        template = self._dollar_template
        th, tw = template.shape[:2]
        ih, iw = search_binary.shape[:2]
        if ih < th or iw < tw:
            logger.warning("Tooltip crop smaller than $ template — widen capture region")
            return []

        row_counts = np.count_nonzero(green_mask, axis=1)
        active = np.flatnonzero(row_counts >= self._green_row_min_pixels)
        if active.size == 0:
            logger.debug("No green rows above min-pixel threshold — no $ search bands")
            return []

        pad = max(th, 8)
        bands = self._contiguous_bands(active.tolist(), gap_merge=max(2, th // 4))
        hits: list[DollarMatch] = []
        for y0, y1 in bands:
            top = max(0, y0 - pad)
            bottom = min(ih, y1 + pad)
            band = search_binary[top:bottom, :]
            if band.shape[0] < th or band.shape[1] < tw:
                continue
            for hit in self._match_all(band):
                hits.append(
                    DollarMatch(
                        x=hit.x,
                        y=hit.y + top,
                        width=hit.width,
                        height=hit.height,
                        score=hit.score,
                    )
                )

        if not hits:
            logger.debug("Green-row bands missed $ — falling back to full-frame match")
            return self._match_all(search_binary)

        return self._non_max_suppress(hits, min_dist=max(tw, th) // 2)

    @staticmethod
    def _contiguous_bands(
        rows: list[int],
        gap_merge: int,
    ) -> list[tuple[int, int]]:
        """
        Collapse sorted row indices into [start, end) bands, merging small gaps.

        Casual: turn "green on rows 10,11,12,40,41" into two search windows.
        """
        if not rows:
            return []
        bands: list[tuple[int, int]] = []
        start = rows[0]
        prev = rows[0]
        for row in rows[1:]:
            if row - prev <= gap_merge:
                prev = row
                continue
            bands.append((start, prev + 1))
            start = row
            prev = row
        bands.append((start, prev + 1))
        return bands

    def _match_all(self, binary: np.ndarray) -> list[DollarMatch]:
        """
        Run matchTemplate and collect peaks above the threshold.

        Casual: slide the $ picture over the tip/column and keep strong hits.
        """
        template = self._dollar_template
        th, tw = template.shape[:2]
        ih, iw = binary.shape[:2]

        if ih < th or iw < tw:
            logger.warning("Tooltip crop smaller than $ template — widen capture region")
            return []

        result = cv2.matchTemplate(binary, template, cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(result >= self._threshold)

        raw: list[DollarMatch] = []
        for y, x in zip(ys.tolist(), xs.tolist()):
            raw.append(
                DollarMatch(
                    x=int(x),
                    y=int(y),
                    width=tw,
                    height=th,
                    score=float(result[y, x]),
                )
            )

        return self._non_max_suppress(raw, min_dist=max(tw, th) // 2)

    def _non_max_suppress(
        self,
        hits: list[DollarMatch],
        min_dist: int,
    ) -> list[DollarMatch]:
        """
        Keep the strongest hit in each local cluster.

        Casual: one $ glyph should only win once, not a dozen nearby pixels.
        """
        ordered = sorted(hits, key=lambda h: h.score, reverse=True)
        kept: list[DollarMatch] = []
        for hit in ordered:
            too_close = any(
                abs(hit.center_x - other.center_x) < min_dist
                and abs(hit.center_y - other.center_y) < min_dist
                for other in kept
            )
            if not too_close:
                kept.append(hit)
        return kept

    def _overlaps_hud(
        self,
        hit: DollarMatch,
        region: dict[str, int],
        scale: int,
    ) -> bool:
        """
        True if this match's screen-space center sits inside CAPTURE_REGION.

        Casual: is this the scoreboard balance $, not the AH price $?
        """
        local_x = hit.center_x / max(scale, 1)
        local_y = hit.center_y / max(scale, 1)
        screen_x = region["left"] + local_x
        screen_y = region["top"] + local_y

        hud = self._hud_region
        return (
            hud["left"] <= screen_x <= hud["left"] + hud["width"]
            and hud["top"] <= screen_y <= hud["top"] + hud["height"]
        )
