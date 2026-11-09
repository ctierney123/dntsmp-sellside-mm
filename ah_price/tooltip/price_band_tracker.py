"""
Remember the AH price $ column relative to the cursor (X only).

Casual: after the first tooltip hit, only screenshot a tall skinny column.
Enchant lines move $ up/down, so we lock horizontal offset — never Y —
then OCR digits from that same strip. A default X offset lets slot 0 start
in strip mode without a full-ROI hunt.
"""

from __future__ import annotations

from ah_price.config import (
    AH_SCALE_FACTOR,
    COMPARE_DEFAULT_DOLLAR_OFFSET_X_PX,
    COMPARE_DOLLAR_COLUMN_PAD_X_PX,
    COMPARE_DOLLAR_COLUMN_WIDTH_PX,
    COMPARE_PRICE_LINE_HEIGHT_PX,
    COMPARE_PRICE_LINE_PAD_X_PX,
    COMPARE_PRICE_LINE_PAD_Y_PX,
    COMPARE_PRICE_LINE_WIDTH_PX,
    TOOLTIP_REGION,
)
from ah_price.tooltip.dollar_locator import DollarMatch


class PriceBandTracker:
    """
    Converts a successful $ match into cursor-relative capture regions.

    Casual: "the dollar column is this far right of the mouse — crop just that."
    Can be seeded with COMPARE_DEFAULT_DOLLAR_OFFSET_X_PX so slot 0 also uses
    the fast strip path instead of a full tooltip ROI.
    """

    def __init__(
        self,
        column_width: int = COMPARE_DOLLAR_COLUMN_WIDTH_PX,
        column_pad_x: int = COMPARE_DOLLAR_COLUMN_PAD_X_PX,
        price_line_width: int = COMPARE_PRICE_LINE_WIDTH_PX,
        price_line_height: int = COMPARE_PRICE_LINE_HEIGHT_PX,
        price_line_pad_x: int = COMPARE_PRICE_LINE_PAD_X_PX,
        price_line_pad_y: int = COMPARE_PRICE_LINE_PAD_Y_PX,
        scale_factor: int = AH_SCALE_FACTOR,
        default_offset_x: float | None = COMPARE_DEFAULT_DOLLAR_OFFSET_X_PX,
        base_tooltip_region: dict[str, int] | None = None,
    ) -> None:
        self._column_width = column_width
        self._column_pad_x = column_pad_x
        self._price_line_width = price_line_width
        self._price_line_height = price_line_height
        self._price_line_pad_x = price_line_pad_x
        self._price_line_pad_y = price_line_pad_y
        self._scale = max(1, scale_factor)
        self._base_tooltip = dict(base_tooltip_region or TOOLTIP_REGION)
        self._default_offset_x = default_offset_x
        # Horizontal offset only: hover.x → $ left edge in *screen* pixels.
        self._offset_x: float | None = (
            float(default_offset_x) if default_offset_x is not None else None
        )

    @property
    def is_locked(self) -> bool:
        """True once we've learned (or seeded) a $ X offset."""
        return self._offset_x is not None

    @property
    def scale_factor(self) -> int:
        """Upscale factor used when converting DollarMatch coords → screen."""
        return self._scale

    def lock_from_match(
        self,
        dollar: DollarMatch,
        region: dict[str, int],
        hover_xy: tuple[int, int],
    ) -> None:
        """
        Store $ column as an X offset from the current hover point.

        Casual: remember "the dollar is ~40px right of the icon" (ignore Y).
        """
        screen_x = region["left"] + (dollar.x / self._scale)
        self._offset_x = screen_x - hover_xy[0]

    def band_region_for_hover(
        self,
        hover_xy: tuple[int, int],
        tooltip_region: dict[str, int] | None = None,
    ) -> dict[str, int] | None:
        """Alias for dollar_column_region_for_hover."""
        return self.dollar_column_region_for_hover(hover_xy, tooltip_region)

    def dollar_column_region_for_hover(
        self,
        hover_xy: tuple[int, int],
        tooltip_region: dict[str, int] | None = None,
    ) -> dict[str, int] | None:
        """
        Build a tall narrow capture rect around the expected $ column.

        Casual: full-height skinny screenshot glued to the cursor's X.
        """
        if self._offset_x is None:
            return None

        tip = dict(tooltip_region) if tooltip_region is not None else self._base_tooltip
        dollar_left = hover_xy[0] + self._offset_x

        left = int(round(dollar_left - self._column_pad_x))
        top = int(tip["top"])
        width = int(self._column_width + 2 * self._column_pad_x)
        height = int(tip["height"])

        return self._clamp_region(left, top, width, height, min_w=16, min_h=24)

    def price_line_region_from_match(
        self,
        dollar: DollarMatch,
        column_region: dict[str, int],
    ) -> dict[str, int] | None:
        """
        Build a short wide capture rect for the digits to the right of $.

        Casual: once we know where $, screenshot just the money line.
        """
        screen_x = column_region["left"] + (dollar.x / self._scale)
        screen_y = column_region["top"] + (dollar.y / self._scale)
        glyph_h = max(1.0, dollar.height / self._scale)

        left = int(round(screen_x - self._price_line_pad_x))
        top = int(round(screen_y - self._price_line_pad_y))
        width = int(self._price_line_width + 2 * self._price_line_pad_x)
        height = int(
            max(
                self._price_line_height,
                glyph_h + 2 * self._price_line_pad_y,
            )
        )

        return self._clamp_region(left, top, width, height, min_w=32, min_h=12)

    @staticmethod
    def _clamp_region(
        left: int,
        top: int,
        width: int,
        height: int,
        min_w: int,
        min_h: int,
    ) -> dict[str, int] | None:
        """Keep a capture rect on-screen; return None if it collapses."""
        if left < 0:
            width += left
            left = 0
        if top < 0:
            height += top
            top = 0
        if width < min_w or height < min_h:
            return None
        return {"left": left, "top": top, "width": width, "height": height}

    def clear(self) -> None:
        """
        Reset to the seeded default offset (not fully unlocked).

        Casual: new AH search — keep the calibrated X guess, drop live locks.
        """
        self._offset_x = (
            float(self._default_offset_x)
            if self._default_offset_x is not None
            else None
        )
