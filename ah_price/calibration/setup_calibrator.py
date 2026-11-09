"""
Interactive setup: capture hover point + tooltip region from the live mouse.

Casual: park your mouse where you want, hit Enter, get paste-ready config.
Two modes:
  --setup-hover   → single ITEM_HOVER_XY
  --setup-region  → two clicks (top-left, bottom-right) → TOOLTIP_REGION
"""

from __future__ import annotations

import sys
import threading
import time

import pyautogui


class SetupCalibrator:
    """
    Live mouse-position helper that prints config snippets for ah_price.

    Casual: watches your cursor and freezes coords when you press Enter.
    Uses a background poller so the position stays fresh while you move,
    then stdin Enter freezes whatever the poller last saw.
    """

    def __init__(self, poll_interval: float = 0.05) -> None:
        self._poll_interval = poll_interval
        self._latest: tuple[int, int] = (0, 0)
        self._stop = threading.Event()
        # When True, poller still tracks the mouse but skips the \r status line
        # so input() prompts aren't overwritten mid-type.
        self._quiet_display = False

    def run_hover_setup(self) -> tuple[int, int]:
        """
        Capture one screen point for ITEM_HOVER_XY.

        Casual: hover the first AH listing, then press Enter in this terminal.
        """
        print()
        print("=== AH hover point setup ===")
        print("1. Open Minecraft + Auction House with a listing visible.")
        print("2. Move the mouse onto the item slot you want to price-check.")
        print("3. Click THIS terminal so it has focus, then press Enter.")
        print("   (Cursor position is still polled while you move.)")
        print()

        self._start_poller()
        try:
            self._wait_for_enter("Press Enter to lock ITEM_HOVER_XY...")
            xy = self._latest
        finally:
            self._stop_poller()

        print()
        print(f"Locked hover at: ({xy[0]}, {xy[1]})")
        print()
        print("Paste into ah_price/config.py:")
        print(f"ITEM_HOVER_XY: tuple[int, int] = ({xy[0]}, {xy[1]})")
        print()
        return xy

    def run_region_setup(self) -> dict[str, int]:
        """
        Capture a screen rectangle for TOOLTIP_REGION (two corners).

        Casual: freeze top-left, then bottom-right, of the tooltip area.
        Height should cover a heavily enchanted item so the price still fits.
        """
        print()
        print("=== AH tooltip region setup ===")
        print("Hover an item so the tooltip is visible.")
        print("We'll freeze TWO corners of a box that covers the whole tip.")
        print()

        self._start_poller()
        try:
            self._wait_for_enter("Move mouse to TOP-LEFT of tooltip box, then Enter...")
            top_left = self._latest
            print(f"  top-left = {top_left}")

            self._wait_for_enter(
                "Move mouse to BOTTOM-RIGHT of tooltip box, then Enter..."
            )
            bottom_right = self._latest
            print(f"  bottom-right = {bottom_right}")
        finally:
            self._stop_poller()

        left = min(top_left[0], bottom_right[0])
        top = min(top_left[1], bottom_right[1])
        width = abs(bottom_right[0] - top_left[0])
        height = abs(bottom_right[1] - top_left[1])

        if width < 20 or height < 20:
            raise ValueError(
                f"Region too small ({width}x{height}). "
                "Corners must be far enough apart to cover the tooltip."
            )

        region = {"left": left, "top": top, "width": width, "height": height}
        print()
        print(f"Locked TOOLTIP_REGION: {region}")
        print()
        print("Paste into ah_price/config.py:")
        print("TOOLTIP_REGION: dict[str, int] = {")
        print(f'    "left": {left},')
        print(f'    "top": {top},')
        print(f'    "width": {width},')
        print(f'    "height": {height},')
        print("}")
        print()
        print(
            "Tip: keep this box off the scoreboard CAPTURE_REGION if you can, "
            "so the HUD balance $ is never a false positive."
        )
        print()
        return region

    def run_full_setup(self) -> None:
        """
        Run hover setup then region setup back-to-back.

        Casual: one command to calibrate both coords you'll need.
        """
        self.run_hover_setup()
        print("-" * 40)
        self.run_region_setup()

    def capture_point(self, prompt: str) -> tuple[int, int]:
        """
        Freeze the current mouse position after the user presses Enter.

        Casual: "park the cursor, hit Enter, get (x, y)."
        Starts/stops its own poller so callers don't manage threads.
        """
        self._start_poller()
        try:
            self._wait_for_enter(prompt)
            return self._latest
        finally:
            self._stop_poller()

    def capture_points(self, prompts: list[str]) -> list[tuple[int, int]]:
        """
        Freeze several mouse positions under one continuous poller session.

        Casual: lock point A, then B, without restarting the mouse watcher.
        Useful for two-corner regions or adjacent-slot spacing.
        """
        if not prompts:
            return []
        points: list[tuple[int, int]] = []
        self._start_poller()
        try:
            for prompt in prompts:
                self._wait_for_enter(prompt)
                points.append(self._latest)
        finally:
            self._stop_poller()
        return points

    def _start_poller(self) -> None:
        """Background thread that keeps self._latest updated."""
        self._stop.clear()
        thread = threading.Thread(target=self._poll_loop, name="mouse-poller", daemon=True)
        thread.start()
        self._thread = thread

    def _stop_poller(self) -> None:
        self._stop.set()
        thread = getattr(self, "_thread", None)
        if thread is not None:
            thread.join(timeout=1.0)

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            pos = pyautogui.position()
            self._latest = (int(pos.x), int(pos.y))
            if not self._quiet_display:
                # Live status line — \r so it doesn't flood the terminal.
                sys.stdout.write(
                    f"\r  mouse: ({self._latest[0]:4d}, {self._latest[1]:4d})   "
                )
                sys.stdout.flush()
            time.sleep(self._poll_interval)
        sys.stdout.write("\n")
        sys.stdout.flush()

    def _wait_for_enter(self, prompt: str) -> None:
        """
        Block until the user presses Enter in this terminal.

        Casual: freeze whatever the poller currently sees.
        Quiet the live mouse line so the prompt stays readable.
        """
        self._quiet_display = True
        # Clear the leftover status line before showing the prompt.
        sys.stdout.write("\r" + " " * 40 + "\r")
        sys.stdout.flush()
        try:
            input(prompt)
        except EOFError as exc:
            raise RuntimeError("stdin closed before Enter was pressed") from exc
        finally:
            self._quiet_display = False
