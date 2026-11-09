#!/usr/bin/env python3
"""
Minecraft HUD screen reader — passive username + balance logger.

Read-only: captures screen pixels only. Never sends keyboard/mouse input
and never connects to any server.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from screen_reader.calibration import CalibrationManager
from screen_reader.config import POLL_INTERVAL_SECONDS
from screen_reader.glyph_atlas import build_atlas_from_crop
from screen_reader.hud_reader import HudReader, read_once


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main() -> int:
    """
    CLI entry: --calibrate, --build-atlas, or the default poll loop.

    Casual: run this script to calibrate, build templates, or start reading.
    """
    parser = argparse.ArgumentParser(
        description="Passive Minecraft HUD reader (username + balance)."
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Save full-screen + crop images for CAPTURE_REGION setup.",
    )
    parser.add_argument(
        "--build-atlas",
        nargs="+",
        metavar="LINE",
        help=(
            "Capture a fresh HUD crop, then build ./templates/. Pass one ground-truth "
            "string per HUD line (top to bottom) matching what is on screen NOW, "
            "e.g. --build-atlas PlayerName '$ 52.1M'"
        ),
    )
    parser.add_argument(
        "--use-tesseract",
        action="store_true",
        help="Enable LESS ACCURATE pytesseract fallback (requires Tesseract installed).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Read a single frame and exit (useful for testing).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging.",
    )
    args = parser.parse_args()
    _configure_logging(args.verbose)

    if args.calibrate:
        CalibrationManager().run()
        return 0

    if args.build_atlas:
        if len(args.build_atlas) < 1:
            print("Provide ground-truth line label(s), e.g. --build-atlas PlayerName '$ 52.1M'")
            return 1

        # Always snap a new crop first — stale calibration_crop.png + a live
        # balance label is how we used to write 5.png as 6.png, etc.
        calibrator = CalibrationManager()
        try:
            crop_path = calibrator.capture_fresh_crop()
        finally:
            calibrator.close()

        paths = build_atlas_from_crop(crop_path, args.build_atlas)
        print(f"Wrote {len(paths)} template(s) to ./templates/")
        for path in paths:
            print(f"  {path}")
        return 0

    # Default: poll loop -------------------------------------------------
    reader = HudReader(use_tesseract=args.use_tesseract)
    try:
        if args.once:
            result = reader.read_once()
            print(result)
            return 0

        print(f"Reading HUD every {POLL_INTERVAL_SECONDS}s (Ctrl+C to stop)...")
        while True:
            try:
                result = read_once(use_tesseract=args.use_tesseract)
                print(result)
            except Exception as exc:
                logging.getLogger(__name__).warning("Bad frame, skipping: %s", exc)
            time.sleep(POLL_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    finally:
        reader.close()


if __name__ == "__main__":
    sys.exit(main())
