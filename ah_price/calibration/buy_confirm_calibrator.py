"""
Interactive calibration for the AH high-price buy confirm dialog.

Casual: lock the Yes button + a tight box, then save a Yes template PNG.
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ah_price.config import BUY_CONFIRM_YES_TEMPLATE, FOCUS_COUNTDOWN_SECONDS
from ah_price.calibration.setup_calibrator import SetupCalibrator
from screen_reader.capture_manager import ScreenCaptureManager
from screen_reader.config import SCALE_FACTOR
from screen_reader.preprocessor import ImagePreprocessor


class BuyConfirmCalibrator:
    """
    Capture Yes click point, OCR region, and a whole-word Yes template.

    Casual: park on Yes, box the Yes text, we snapshot it for matching later.
    Prints paste-ready BUY_CONFIRM_YES_XY / BUY_CONFIRM_YES_REGION for config
    and writes ``templates/buy_confirm_yes.png``.
    """

    def __init__(
        self,
        template_path: Path | None = None,
        countdown_seconds: float = FOCUS_COUNTDOWN_SECONDS,
        scale_factor: int = SCALE_FACTOR,
    ) -> None:
        self._mouse = SetupCalibrator()
        self._template_path = Path(template_path or BUY_CONFIRM_YES_TEMPLATE)
        self._countdown = float(countdown_seconds)
        self._scale = max(1, int(scale_factor))

    def run(self) -> tuple[tuple[int, int], dict[str, int], Path]:
        """
        Interactive buy-confirm setup: click point → region → template snap.

        Casual: three locks + one screenshot of the Yes label.

        Returns
        -------
        (yes_xy, yes_region, template_path)
        """
        print()
        print("=== AH buy-confirm (Yes) setup ===")
        print("1. Open Minecraft and trigger the high-price confirm popup")
        print('   ("Are you sure you want to buy this?" with No / Yes).')
        print("2. We'll lock the Yes BUTTON click point, then a tight box")
        print("   around the Yes LABEL text (not the whole dialog).")
        print("3. Then click back into Minecraft so we can snapshot that box")
        print("   into a Yes template for runtime matching.")
        print()

        yes_xy = self._mouse.capture_point(
            "Move mouse onto the YES button center, then Enter..."
        )
        print(f"  YES click = {yes_xy}")

        corners = self._mouse.capture_points(
            [
                "Move mouse to TOP-LEFT of the Yes text, then Enter...",
                "Move mouse to BOTTOM-RIGHT of the Yes text, then Enter...",
            ]
        )
        top_left, bottom_right = corners[0], corners[1]
        print(f"  Yes text top-left = {top_left}")
        print(f"  Yes text bottom-right = {bottom_right}")

        region = self._region_from_corners(top_left, bottom_right)
        template_path = self._capture_yes_template(region)

        print()
        print(f"Locked BUY_CONFIRM_YES_XY: {yes_xy}")
        print(f"Locked BUY_CONFIRM_YES_REGION: {region}")
        print(f"Wrote Yes template: {template_path}")
        print()
        print("Paste into ah_price/config.py:")
        print(
            f"BUY_CONFIRM_YES_XY: tuple[int, int] = ({yes_xy[0]}, {yes_xy[1]})"
        )
        print("BUY_CONFIRM_YES_REGION: dict[str, int] = {")
        print(f'    "left": {region["left"]},')
        print(f'    "top": {region["top"]},')
        print(f'    "width": {region["width"]},')
        print(f'    "height": {region["height"]},')
        print("}")
        print()
        print(
            "Tip: keep the OCR box on the Yes word only — tighter = fewer "
            "false positives from other GUI text. Re-run this setup if you "
            "change GUI scale."
        )
        print()
        return yes_xy, region, template_path

    @staticmethod
    def _region_from_corners(
        top_left: tuple[int, int],
        bottom_right: tuple[int, int],
    ) -> dict[str, int]:
        """
        Build a left/top/width/height dict from two opposite corners.

        Casual: turn two mouse locks into a screenshot box.
        """
        left = min(top_left[0], bottom_right[0])
        top = min(top_left[1], bottom_right[1])
        width = abs(bottom_right[0] - top_left[0])
        height = abs(bottom_right[1] - top_left[1])
        if width < 8 or height < 8:
            raise ValueError(
                f"Yes OCR region too small ({width}x{height}). "
                "Corners must cover the Yes label with a little padding."
            )
        return {"left": left, "top": top, "width": width, "height": height}

    def _capture_yes_template(self, region: dict[str, int]) -> Path:
        """
        Countdown → screenshot Yes region → save binary template PNG.

        Casual: grab what Yes looks like right now and stash it in templates/.
        Uses HUD SCALE_FACTOR so the detector can rescale to AH_SCALE_FACTOR
        the same way dollar / digit templates do.
        """
        print()
        print(
            "Click into Minecraft with the confirm dialog still open — "
            f"capturing Yes template in {self._countdown:.0f}s..."
        )
        self._sleep_countdown(self._countdown)

        capture = ScreenCaptureManager(region)
        try:
            frame = capture.capture()
        finally:
            capture.close()

        preprocessor = ImagePreprocessor(scale_factor=self._scale)
        binary = preprocessor.preprocess(frame)
        if int(np.count_nonzero(binary)) < 10:
            raise RuntimeError(
                "Yes region capture looks empty (almost no text pixels). "
                "Keep the confirm dialog open and tighten the Yes text box."
            )

        out_path = self._template_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # White-on-black binary PNG, same convention as glyph atlas templates.
        ok = cv2.imwrite(str(out_path), binary)
        if not ok:
            raise RuntimeError(f"Failed to write Yes template to {out_path}")

        # Also drop a color preview next to the project root for eyeballing.
        preview = Path("ah_buy_confirm_yes_calib.png")
        Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).save(preview)
        print(f"  preview (color): {preview}")
        print(f"  template (binary): {out_path}")
        return out_path

    @staticmethod
    def _sleep_countdown(seconds: float) -> None:
        remaining = int(seconds)
        while remaining > 0:
            print(f"  {remaining}...", flush=True)
            time.sleep(1.0)
            remaining -= 1
        frac = seconds - int(seconds)
        if frac > 0:
            time.sleep(frac)
