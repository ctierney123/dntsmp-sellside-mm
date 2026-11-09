"""
Detect the AH high-price buy confirm dialog via a Yes-word template.

Casual: match the saved Yes label; if it lights up, the popup is open.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from ah_price.config import (
    AH_SCALE_FACTOR,
    BUY_CONFIRM_DEBUG_IMAGE,
    BUY_CONFIRM_MATCH_THRESHOLD,
    BUY_CONFIRM_POLL_INTERVAL_SECONDS,
    BUY_CONFIRM_POLL_SECONDS,
    BUY_CONFIRM_YES_REGION,
    BUY_CONFIRM_YES_TEMPLATE,
    BUY_CONFIRM_YES_XY,
)
from screen_reader.capture_manager import ScreenCaptureManager
from screen_reader.config import SCALE_FACTOR
from screen_reader.preprocessor import ImagePreprocessor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuyConfirmDetection:
    """
    Result of probing the Yes OCR / template region.

    Casual: did we see Yes, and how strong was the match?
    """

    visible: bool
    score: float
    yes_xy: tuple[int, int]


class BuyConfirmDetector:
    """
    Template-match the calibrated Yes label to detect the confirm popup.

    Casual: screenshot the Yes box; if it looks like our saved Yes, click it.
    Uses a whole-word binary template written by ``--setup-buy-confirm`` so we
    don't depend on having Y/e/s glyphs in the HUD atlas.
    """

    def __init__(
        self,
        yes_xy: tuple[int, int] | None = None,
        yes_region: dict[str, int] | None = None,
        template_path: Path | None = None,
        scale_factor: int = AH_SCALE_FACTOR,
        match_threshold: float = BUY_CONFIRM_MATCH_THRESHOLD,
        save_debug: bool = False,
        debug_image: Path = BUY_CONFIRM_DEBUG_IMAGE,
        template_native_scale: int = SCALE_FACTOR,
    ) -> None:
        self._yes_xy = yes_xy if yes_xy is not None else BUY_CONFIRM_YES_XY
        self._region = dict(yes_region or BUY_CONFIRM_YES_REGION)
        self._template_path = Path(template_path or BUY_CONFIRM_YES_TEMPLATE)
        self._scale = max(1, int(scale_factor))
        self._native_scale = max(1, int(template_native_scale))
        self._threshold = float(match_threshold)
        self._save_debug = save_debug
        self._debug_image = Path(debug_image)

        self._capture: ScreenCaptureManager | None = None
        self._preprocessor: ImagePreprocessor | None = None
        self._template: np.ndarray | None = None

    @property
    def is_calibrated(self) -> bool:
        """
        True when Yes click, OCR box, and template file all look usable.

        Casual: did you finish --setup-buy-confirm and paste the coords?
        """
        if self._yes_xy[0] <= 0 or self._yes_xy[1] <= 0:
            return False
        if (
            int(self._region.get("width", 0)) < 8
            or int(self._region.get("height", 0)) < 8
        ):
            return False
        return self._template_path.is_file()

    @property
    def yes_xy(self) -> tuple[int, int]:
        return self._yes_xy

    def probe(self) -> BuyConfirmDetection:
        """
        One-shot template match over the Yes region.

        Casual: peek once — is the confirm dialog showing Yes right now?
        """
        if not self.is_calibrated:
            return BuyConfirmDetection(
                visible=False,
                score=0.0,
                yes_xy=self._yes_xy,
            )

        self._ensure_vision()
        assert self._capture is not None
        assert self._preprocessor is not None
        assert self._template is not None

        frame = self._capture.capture()
        if self._save_debug:
            self._write_bgr(self._debug_image, frame)

        binary = self._preprocessor.preprocess(frame)
        score = self._best_match_score(binary, self._template)
        visible = score >= self._threshold
        logger.debug(
            "Buy-confirm probe score=%.3f threshold=%.3f visible=%s",
            score,
            self._threshold,
            visible,
        )
        return BuyConfirmDetection(
            visible=visible,
            score=score,
            yes_xy=self._yes_xy,
        )

    def wait_for_confirm(
        self,
        timeout_seconds: float = BUY_CONFIRM_POLL_SECONDS,
        poll_interval: float = BUY_CONFIRM_POLL_INTERVAL_SECONDS,
    ) -> BuyConfirmDetection | None:
        """
        Poll until Yes appears or the timeout expires.

        Casual: after a buy click, watch briefly for the are-you-sure popup.
        Returns the detection when visible, else None if it never showed.
        """
        if not self.is_calibrated:
            logger.debug("Buy-confirm detector not calibrated — skipping poll")
            return None

        deadline = time.perf_counter() + max(0.0, float(timeout_seconds))
        while True:
            detection = self.probe()
            if detection.visible:
                return detection
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                return None
            time.sleep(min(float(poll_interval), remaining))

    def close(self) -> None:
        """Release mss resources if they were created."""
        if self._capture is not None:
            self._capture.close()
            self._capture = None

    def _ensure_vision(self) -> None:
        """
        Lazy-init capture + Yes template on first probe.

        Casual: don't load vision gear until we actually need Yes detection.
        """
        if self._capture is not None:
            return

        self._capture = ScreenCaptureManager(self._region)
        self._preprocessor = ImagePreprocessor(scale_factor=self._scale)
        self._template = self._load_template(self._template_path)

    def _load_template(self, path: Path) -> np.ndarray:
        """
        Load the saved Yes binary template and rescale to AH preprocess scale.

        Casual: pull yes.png off disk and zoom it to match live captures.
        Templates are authored at HUD SCALE_FACTOR during setup capture.
        """
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None:
            raise FileNotFoundError(
                f"Could not read Yes template: {path}. "
                "Re-run: python -m ah_price --setup-buy-confirm"
            )
        _, binary = cv2.threshold(image, 127, 255, cv2.THRESH_BINARY)
        if self._native_scale == self._scale:
            return binary

        ratio = self._scale / self._native_scale
        new_w = max(1, int(round(binary.shape[1] * ratio)))
        new_h = max(1, int(round(binary.shape[0] * ratio)))
        resized = cv2.resize(binary, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
        _, out = cv2.threshold(resized, 127, 255, cv2.THRESH_BINARY)
        return out

    @staticmethod
    def _best_match_score(binary: np.ndarray, template: np.ndarray) -> float:
        """
        Normalized cross-correlation peak of template inside the binary crop.

        Casual: how much does this box look like our saved Yes?
        """
        th, tw = template.shape[:2]
        bh, bw = binary.shape[:2]
        if bh < th or bw < tw:
            logger.debug(
                "Yes region %sx%s smaller than template %sx%s",
                bw,
                bh,
                tw,
                th,
            )
            return 0.0
        result = cv2.matchTemplate(binary, template, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, _max_loc = cv2.minMaxLoc(result)
        return float(max_val)

    @staticmethod
    def _write_bgr(path: Path, frame: np.ndarray) -> None:
        Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).save(path)

    @staticmethod
    def to_status_dict(
        detection: BuyConfirmDetection | None,
        *,
        clicked: bool = False,
    ) -> dict[str, Any]:
        """Small printable dict for armor-arb reports."""
        if detection is None:
            return {"visible": False, "score": 0.0, "clicked": clicked}
        return {
            "visible": detection.visible,
            "score": round(detection.score, 3),
            "yes_xy": detection.yes_xy,
            "clicked": clicked,
        }
