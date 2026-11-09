"""
Interactive calibration for AH first-row slot spacing.

Casual: lock slot 0, lock slot 1, get paste-ready SLOT_SPACING_XY.
Reuses SetupCalibrator's public mouse-freeze helpers.
"""

from __future__ import annotations

from ah_price.config import SLOT_COUNT
from ah_price.calibration.setup_calibrator import SetupCalibrator
from ah_price.scan.slot_grid_manager import SlotGridManager


class SlotSpacingCalibrator:
    """
    Capture origin + adjacent-slot delta for the AH listing grid.

    Casual: park on item 1, Enter; park on item 2, Enter; copy the numbers.
    Prints ITEM_HOVER_XY (slot 0) and SLOT_SPACING_XY for config.py, plus a
    preview of all SLOT_COUNT hover points so you can sanity-check the math.
    """

    def __init__(self, slot_count: int = SLOT_COUNT) -> None:
        self._slot_count = slot_count
        self._mouse = SetupCalibrator()

    def run(self) -> tuple[tuple[int, int], tuple[int, int]]:
        """
        Interactive two-point slot spacing setup.

        Casual: measure how far apart the first two AH icons are.

        Returns
        -------
        (origin_xy, spacing_xy)
        """
        print()
        print("=== AH slot spacing setup ===")
        print("1. Open Minecraft + Auction House with the first row visible.")
        print("2. We'll lock TWO adjacent slots (leftmost, then the one next to it).")
        print("3. Click THIS terminal for focus when ready to freeze each point.")
        print()

        points = self._mouse.capture_points(
            [
                "Move mouse onto SLOT 0 (leftmost listing), then Enter...",
                "Move mouse onto SLOT 1 (next listing to the right), then Enter...",
            ]
        )
        origin, second = points[0], points[1]
        print(f"  slot 0 = {origin}")
        print(f"  slot 1 = {second}")

        spacing = SlotGridManager.spacing_from_two_points(origin, second)
        if abs(spacing[0]) < 8 and abs(spacing[1]) < 8:
            raise ValueError(
                f"Spacing too small {spacing}. "
                "Slots must be distinct — re-run and lock two different icons."
            )

        grid = SlotGridManager(
            origin_xy=origin,
            spacing_xy=spacing,
            slot_count=self._slot_count,
        )
        points_preview = grid.all_hover_points()

        print()
        print(f"Locked SLOT_SPACING_XY: {spacing}")
        print(f"Preview of {self._slot_count} hover points:")
        for i, xy in enumerate(points_preview):
            print(f"  slot {i}: ({xy[0]}, {xy[1]})")
        print()
        print("Paste into ah_price/config.py:")
        print(f"ITEM_HOVER_XY: tuple[int, int] = ({origin[0]}, {origin[1]})")
        print(f"SLOT_SPACING_XY: tuple[int, int] = ({spacing[0]}, {spacing[1]})")
        print(f"SLOT_COUNT: int = {self._slot_count}")
        print()
        return origin, spacing
