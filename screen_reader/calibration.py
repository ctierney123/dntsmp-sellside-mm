"""
Calibration workflow: full-screen grab + crop preview for CAPTURE_REGION tuning.
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2

from screen_reader.capture_manager import ScreenCaptureManager
from screen_reader.config import (
    CALIBRATION_CROP_IMAGE,
    CALIBRATION_FULL_IMAGE,
    CAPTURE_REGION,
)


class CalibrationManager:
    """
    Saves calibration images and prints coordinate instructions.

    Casual: helps you figure out where the HUD text is on your screen.
    Also used by --build-atlas to grab a *fresh* HUD crop so templates
    match whatever balance is on screen right now (not a stale PNG).
    """

    def __init__(
        self,
        region: dict[str, int] | None = None,
        screen_width: int = 1920,
        screen_height: int = 1080,
    ) -> None:
        self._region = region or CAPTURE_REGION
        self._screen_width = screen_width
        self._screen_height = screen_height
        self._capture = ScreenCaptureManager(self._region)

    def run(self) -> None:
        """
        Grab full screen + current crop, save PNGs, print next steps.

        Casual: run once with --calibrate, then edit config with your coords.
        """
        full = self._capture.capture_full_screen(self._screen_width, self._screen_height)
        cv2.imwrite(str(CALIBRATION_FULL_IMAGE), full)

        self.capture_fresh_crop()
        self._capture.close()
        self._print_instructions()

    def capture_fresh_crop(
        self,
        out_path: Path | None = None,
        countdown_seconds: float = 3.0,
    ) -> Path:
        """
        Screenshot CAPTURE_REGION right now and overwrite the crop PNG.

        Casual: snap a new HUD picture so --build-atlas isn't using yesterday's balance.

        Gives a short countdown so you can click into Minecraft first. Writes
        calibration_crop.png (or `out_path`) and returns that path.

        Parameters
        ----------
        out_path:
            Where to save the BGR crop. Defaults to CALIBRATION_CROP_IMAGE.
        countdown_seconds:
            Seconds to wait (with printed ticks) before grabbing. Use 0 to
            capture immediately (e.g. from automated tests).
        """
        dest = Path(out_path) if out_path is not None else CALIBRATION_CROP_IMAGE
        self._countdown(countdown_seconds)

        crop = self._capture.capture()
        cv2.imwrite(str(dest), crop)
        print(f"Fresh crop saved to: {dest.resolve()}")
        return dest

    def close(self) -> None:
        """Release the screen-capture handle."""
        self._capture.close()

    @staticmethod
    def _countdown(seconds: float) -> None:
        """
        Print a short focus countdown, or no-op if seconds <= 0.

        Casual: "3… 2… 1…" so you can alt-tab into Minecraft.
        """
        if seconds <= 0:
            return

        total = int(round(seconds))
        print(
            f"Focus Minecraft with the HUD visible. Capturing crop in {total}s..."
        )
        for remaining in range(total, 0, -1):
            print(f"  {remaining}...")
            time.sleep(1.0)

    def _print_instructions(self) -> None:
        """Tell the user how to measure CAPTURE_REGION from the saved full image."""
        r = self._region
        print()
        print("=" * 60)
        print("CALIBRATION MODE")
        print("=" * 60)
        print(f"Full screen saved to: {CALIBRATION_FULL_IMAGE.resolve()}")
        print(f"Current crop saved to: {CALIBRATION_CROP_IMAGE.resolve()}")
        print()
        print("Next steps:")
        print("  1. Open calibration_full.png in an image viewer.")
        print("  2. Find the scoreboard / HUD box showing your username and balance.")
        print("  3. Note the TOP-LEFT corner (left, top) and the box size (width, height).")
        print("  4. Paste those values into CAPTURE_REGION in screen_reader/config.py:")
        print('       CAPTURE_REGION = {"left": ..., "top": ..., "width": ..., "height": ...}')
        print("  5. Re-run --calibrate and check calibration_crop.png - both text lines")
        print("     should be fully visible with a little margin.")
        print()
        print(f"Current CAPTURE_REGION: {r}")
        print()
        print("GUI scale reminder: set Minecraft GUI Scale to an INTEGER (2, 3, 4, …)")
        print("before building templates. Fractional scale blurs pixels and breaks matching.")
        print("=" * 60)
        print()
