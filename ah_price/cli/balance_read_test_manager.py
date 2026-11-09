"""
Manual HUD balance smoke test — OCR once and print what we saw.

Casual: click Minecraft, then we peek at your scoreboard cash.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import cv2

from ah_price.config import FOCUS_COUNTDOWN_SECONDS
from screen_reader.config import CAPTURE_REGION
from screen_reader.hud_reader import HudReader

logger = logging.getLogger(__name__)

# Written next to the project root so you can eyeball a bad OCR frame.
BALANCE_READ_DEBUG_IMAGE: Path = Path("ah_balance_read_debug.png")


class BalanceReadTestManager:
    """
    One-shot (or N-shot) scoreboard balance read for manual debugging.

    Casual: prove the HUD reader works before we trust the overnight floor.
    Captures CAPTURE_REGION, runs the same HudReader path as the balance
    guard, prints username / raw / coins / timing, and always dumps the
    raw crop to ``ah_balance_read_debug.png`` so a "found 1 line" failure
    is inspectable. No keyboard/mouse injection — clear the AH menu
    yourself before running if you want a clean scoreboard.
    """

    def __init__(
        self,
        *,
        countdown_seconds: float = FOCUS_COUNTDOWN_SECONDS,
        repeats: int = 1,
        interval_seconds: float = 1.0,
        save_debug: bool = True,
        debug_image: Path | None = None,
        reader: HudReader | None = None,
    ) -> None:
        if repeats < 1:
            raise ValueError("repeats must be >= 1")
        if interval_seconds < 0:
            raise ValueError("interval_seconds must be non-negative")
        self._countdown = float(countdown_seconds)
        self._repeats = int(repeats)
        self._interval = float(interval_seconds)
        self._save_debug = bool(save_debug)
        self._debug_image = debug_image or BALANCE_READ_DEBUG_IMAGE
        self._reader = reader or HudReader()
        self._owns_reader = reader is None

    def run(self) -> list[dict[str, Any]]:
        """
        Countdown, then read the HUD balance one or more times.

        Casual: focus Minecraft, then we print what the scoreboard says.
        Returns one result dict per attempt (ok or error). Always writes
        the latest raw crop when ``save_debug`` is on.
        """
        self._print_banner()
        self._sleep_countdown(self._countdown)

        results: list[dict[str, Any]] = []
        for attempt in range(1, self._repeats + 1):
            row = self._read_one(attempt)
            results.append(row)
            self._print_attempt(row)
            if attempt < self._repeats and self._interval > 0:
                time.sleep(self._interval)
        return results

    def _read_one(self, attempt: int) -> dict[str, Any]:
        """
        OCR one HUD frame; always dump the crop when debug is on.

        Casual: one screenshot, one parse, keep the PNG if it blew up.
        ``read_once`` captures internally; we grab a second crop for the
        debug PNG so a failed parse still leaves something to inspect
        (menus / wrong CAPTURE_REGION / GUI scale).
        """
        started = time.perf_counter()
        try:
            snapshot = self._reader.read_once()
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self._write_debug_crop()
            return {
                "attempt": attempt,
                "ok": True,
                "elapsed_ms": elapsed_ms,
                "username": snapshot.get("username"),
                "balance_raw": snapshot.get("balance_raw"),
                "balance": snapshot.get("balance"),
                "error": None,
                "debug_image": str(self._debug_image) if self._save_debug else None,
            }
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self._write_debug_crop()
            logger.warning("Balance read attempt %s failed: %s", attempt, exc)
            return {
                "attempt": attempt,
                "ok": False,
                "elapsed_ms": elapsed_ms,
                "username": None,
                "balance_raw": None,
                "balance": None,
                "error": str(exc),
                "debug_image": str(self._debug_image) if self._save_debug else None,
            }

    def _write_debug_crop(self) -> None:
        """Save the current CAPTURE_REGION pixels next to the project root."""
        if not self._save_debug:
            return
        frame = self._reader.capture()
        cv2.imwrite(str(self._debug_image), frame)

    def _print_banner(self) -> None:
        region = CAPTURE_REGION
        print("=== HUD balance read test ===")
        print(
            f"  CAPTURE_REGION: left={region['left']} top={region['top']} "
            f"w={region['width']} h={region['height']}"
        )
        print(f"  repeats: {self._repeats}")
        if self._save_debug:
            print(f"  debug crop: {self._debug_image}")
        print(
            "  Tip: leave AH / pause menus closed — scoreboard must be visible."
        )
        if self._countdown > 0:
            print(
                f"Click into Minecraft now — balance read in "
                f"{self._countdown:.0f}s"
            )

    @staticmethod
    def _print_attempt(row: dict[str, Any]) -> None:
        attempt = row["attempt"]
        ms = row["elapsed_ms"]
        if row["ok"]:
            print(
                f"  [{attempt}] OK  {row['balance_raw']} → "
                f"{row['balance']:,} coins  "
                f"(user={row['username']!r}, {ms:.1f} ms)"
            )
        else:
            print(f"  [{attempt}] FAIL  ({ms:.1f} ms) — {row['error']}")
            if row.get("debug_image"):
                print(f"         inspect {row['debug_image']}")

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

    def close(self) -> None:
        """Release the HudReader capture handle if we own it."""
        if self._owns_reader:
            self._reader.close()
