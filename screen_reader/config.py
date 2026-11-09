"""
Configuration for the Minecraft HUD screen reader.

All tunables live here so you can calibrate once and forget the rest of the code.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Screen capture box (pixels, absolute screen coordinates on your monitor).
# Run with --calibrate first, open calibration_full.png, measure the HUD text
# rectangle, then paste {left, top, width, height} here.
# ---------------------------------------------------------------------------
CAPTURE_REGION: dict[str, int] = {
    "left": 1660,
    "top": 460,
    "width": 260,
    "height": 75,
}

# Upscale factor before OCR. Nearest-neighbor keeps Minecraft pixels crisp.
SCALE_FACTOR: int = 4

# How often the main loop calls read_once() (seconds).
POLL_INTERVAL_SECONDS: float = 1.0

# Folder where per-glyph template PNGs are stored (binary white-on-black images).
TEMPLATES_DIR: Path = Path(__file__).resolve().parent.parent / "templates"

# Minimum normalized cross-correlation score to accept a glyph match (0.0–1.0).
# Lower = more lenient; raise if you get wrong characters.
MATCH_SCORE_THRESHOLD: float = 0.55

# Minimum connected-component area (in upscaled pixels) to count as a glyph.
MIN_GLYPH_AREA: int = 8

# ---------------------------------------------------------------------------
# GUI scale note (Minecraft video settings → GUI Scale)
# ---------------------------------------------------------------------------
# Recognition assumes an INTEGER GUI scale (2, 3, 4, …) so each font pixel
# stays a sharp square. Fractional / auto scale anti-aliases text and breaks
# template matching. Set GUI Scale to a whole number before calibrating.
# ---------------------------------------------------------------------------

# Character sets used when building / loading the template atlas.
BALANCE_CHARSET: str = "$0123456789.KMB "
USERNAME_CHARSET: str = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"

# Calibration output filenames (written next to the project root).
CALIBRATION_FULL_IMAGE: Path = Path("calibration_full.png")
CALIBRATION_CROP_IMAGE: Path = Path("calibration_crop.png")
