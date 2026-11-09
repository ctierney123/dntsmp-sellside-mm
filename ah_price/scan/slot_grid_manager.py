"""
AH listing slot coordinates from a first-slot origin + spacing.

Casual: turn "slot 0 is here, slots are X px apart" into nine hover points.
Pure math — no mouse, no screenshots.
"""

from __future__ import annotations

from ah_price.config import (
    ITEM_HOVER_XY,
    SLOT_COUNT,
    SLOT_SPACING_XY,
    TOOLTIP_REGION,
)


class SlotGridManager:
    """
    Builds absolute hover points for the first row of AH listings.

    Casual: slot index in → screen (x, y) out.
    Also shifts TOOLTIP_REGION with the cursor so OCR still sees the tip
    when you hover slots to the right of the calibrated first item.
    """

    def __init__(
        self,
        origin_xy: tuple[int, int] | None = None,
        spacing_xy: tuple[int, int] | None = None,
        slot_count: int = SLOT_COUNT,
        base_tooltip_region: dict[str, int] | None = None,
    ) -> None:
        self._origin = origin_xy or ITEM_HOVER_XY
        self._spacing = spacing_xy or SLOT_SPACING_XY
        self._slot_count = max(1, int(slot_count))
        self._base_tooltip = dict(base_tooltip_region or TOOLTIP_REGION)

    @property
    def slot_count(self) -> int:
        return self._slot_count

    @property
    def origin_xy(self) -> tuple[int, int]:
        return self._origin

    @property
    def spacing_xy(self) -> tuple[int, int]:
        return self._spacing

    def hover_xy_for_slot(self, slot_index: int) -> tuple[int, int]:
        """
        Absolute screen point for one listing slot.

        Casual: where to park the mouse for slot N.
        """
        if slot_index < 0 or slot_index >= self._slot_count:
            raise IndexError(
                f"slot_index {slot_index} out of range [0, {self._slot_count})"
            )
        dx, dy = self._spacing
        x = self._origin[0] + slot_index * dx
        y = self._origin[1] + slot_index * dy
        return (int(x), int(y))

    def all_hover_points(self) -> list[tuple[int, int]]:
        """
        Hover points for every configured slot, left → right.

        Casual: the full first-row checklist of mouse targets.
        """
        return [self.hover_xy_for_slot(i) for i in range(self._slot_count)]

    def tooltip_region_for_hover(self, hover_xy: tuple[int, int]) -> dict[str, int]:
        """
        Shift the calibrated tooltip box so it stays relative to the cursor.

        Casual: move the OCR window with the mouse as you scan slots.
        TOOLTIP_REGION was measured while hovering slot 0; for other slots
        we offset left/top by (hover − origin) so the tip still lands inside.
        """
        ox, oy = self._origin
        hx, hy = hover_xy
        shift_x = hx - ox
        shift_y = hy - oy
        base = self._base_tooltip
        return {
            "left": int(base["left"] + shift_x),
            "top": int(base["top"] + shift_y),
            "width": int(base["width"]),
            "height": int(base["height"]),
        }

    @staticmethod
    def spacing_from_two_points(
        first_xy: tuple[int, int],
        second_xy: tuple[int, int],
    ) -> tuple[int, int]:
        """
        Pixel delta between adjacent slots (slot1 − slot0).

        Casual: two mouse locks → how far apart the icons are.
        """
        return (int(second_xy[0] - first_xy[0]), int(second_xy[1] - first_xy[1]))
