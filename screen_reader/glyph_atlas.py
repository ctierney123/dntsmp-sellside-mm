"""
Build and load per-glyph template atlases for template matching OCR.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from screen_reader.config import (
    BALANCE_CHARSET,
    TEMPLATES_DIR,
    USERNAME_CHARSET,
)
from screen_reader.glyph_segmenter import GlyphSegmenter
from screen_reader.preprocessor import ImagePreprocessor

logger = logging.getLogger(__name__)

# Digits + money punctuation that MUST exist or OCR silently maps unknowns
# to lookalikes (classic bug: missing 0.png → every 0 becomes 8).
_REQUIRED_BALANCE_CHARS: str = "$0123456789."
# Suffixes we expect for DonutSMP balances; warn (don't hard-fail) if absent.
_OPTIONAL_BALANCE_SUFFIXES: str = "KMB"


class GlyphAtlas:
    """
    Dictionary of character → binary template image, loaded from ./templates/.

    Casual: a folder of tiny letter pictures the matcher compares against.
    Each PNG should be white glyphs on a black background, one file per character
    (filename stem = the character, e.g. `5.png`, `M.png`, `_.png`).
    """

    def __init__(self, templates_dir: Path = TEMPLATES_DIR) -> None:
        self._dir = Path(templates_dir)
        self._balance: dict[str, np.ndarray] = {}
        self._username: dict[str, np.ndarray] = {}
        self._segmenter = GlyphSegmenter()
        self._preprocessor = ImagePreprocessor()

    @property
    def balance_templates(self) -> dict[str, np.ndarray]:
        return dict(self._balance)

    @property
    def username_templates(self) -> dict[str, np.ndarray]:
        return dict(self._username)

    def load(self, *, require_balance_digits: bool = True) -> None:
        """
        Load all PNG templates from disk into balance / username sets.

        Casual: read the templates/ folder into memory.
        When ``require_balance_digits`` is True (default), raise if any of
        ``$0123456789.`` is missing — otherwise a lone ``0`` silently becomes
        ``8`` and the arb bot buys at the wrong price.
        """
        self._balance.clear()
        self._username.clear()
        self._dir.mkdir(parents=True, exist_ok=True)

        for path in sorted(self._dir.glob("*.png")):
            char = self._char_from_filename(path.stem)
            # buy_confirm_yes.png etc. are multi-char stems — skip those.
            if len(char) != 1:
                continue
            template = self._load_binary_template(path)
            if char in BALANCE_CHARSET:
                self._balance[char] = template
            if char in USERNAME_CHARSET:
                self._username[char] = template

        if require_balance_digits:
            self.assert_required_balance_templates()

    def assert_required_balance_templates(self) -> None:
        """
        Fail loud if money OCR templates are incomplete.

        Casual: don't start the bot if we're missing a digit sticker.
        Missing ``0.png`` historically made every ``10.xM`` read as ``18.xM``.
        """
        missing = [ch for ch in _REQUIRED_BALANCE_CHARS if ch not in self._balance]
        if missing:
            pretty = ", ".join(repr(ch) for ch in missing)
            raise FileNotFoundError(
                f"Missing required balance glyph template(s) in {self._dir}: {pretty}. "
                "Rebuild with a HUD balance that contains every digit you need, e.g. "
                "python -m screen_reader --build-atlas PlayerName \"$ 10.2M\" "
                "(label must match the live HUD — a missing 0.png makes OCR read 0 as 8)."
            )
        missing_suffix = [
            ch for ch in _OPTIONAL_BALANCE_SUFFIXES if ch not in self._balance
        ]
        if missing_suffix:
            # Soft warning only — K/B may be unused if everything is in M.
            pretty = ", ".join(repr(ch) for ch in missing_suffix)
            logger.warning(
                "Optional balance suffix template(s) missing in %s: %s",
                self._dir,
                pretty,
            )

    def save_template(self, char: str, bitmap: np.ndarray) -> Path:
        """
        Write one glyph template PNG (white on black).

        Casual: save a single letter image to templates/.
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        safe_name = self._filename_for_char(char)
        out_path = self._dir / f"{safe_name}.png"
        Image.fromarray(bitmap).save(out_path)
        return out_path

    def _char_from_filename(self, stem: str) -> str:
        """Map filename stem back to a single character."""
        special = {"dollar": "$", "dot": ".", "space": " ", "underscore": "_"}
        if stem in special:
            return special[stem]
        if len(stem) == 1:
            return stem
        return stem

    def _filename_for_char(self, char: str) -> str:
        """Make a filesystem-safe template filename for a character."""
        mapping = {"$": "dollar", ".": "dot", " ": "space", "_": "underscore"}
        return mapping.get(char, char)

    def _load_binary_template(self, path: Path) -> np.ndarray:
        """Load PNG and normalize to single-channel 0/255."""
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise FileNotFoundError(f"Could not read template: {path}")
        _, binary = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
        return binary


def _align_label_to_glyphs(label: str, glyphs: list[np.ndarray]) -> list[tuple[str, np.ndarray]]:
    """
    Pair label characters with segmented glyph crops.

    Casual: match letters to blobs, skipping spaces (they have no pixels).
    Minecraft's bitmap font leaves gaps for spaces instead of drawing ink,
    so "$ 53.2M" has 7 characters but only 6 visible glyph blobs.
    """
    visible_chars = [ch for ch in label if not ch.isspace()]
    if len(visible_chars) != len(glyphs):
        raise ValueError(
            f"Line {label!r}: segmented {len(glyphs)} glyph(s) but label has "
            f"{len(visible_chars)} visible character(s) "
            f"({len(label)} total including spaces). "
            "Check GUI scale / crop box / ground-truth text."
        )

    pairs: list[tuple[str, np.ndarray]] = []
    glyph_idx = 0
    for ch in label:
        if ch.isspace():
            continue
        pairs.append((ch, glyphs[glyph_idx]))
        glyph_idx += 1
    return pairs


def build_atlas_from_crop(
    crop_path: Path | str,
    line_labels: list[str],
    templates_dir: Path = TEMPLATES_DIR,
    scale_factor: int | None = None,
) -> list[Path]:
    """
    Generate template PNGs from a clean calibration crop.

    Casual: you give it a screenshot snippet + the exact text on each line;
    it saves one template PNG per character into ./templates/.

    Parameters
    ----------
    crop_path:
        Path to calibration_crop.png (or any HUD crop with known text).
    line_labels:
        Ground-truth strings, one per visual line, top to bottom.
        Example: ["PlayerName", "$ 52.1M"]
    templates_dir:
        Output folder for glyph PNGs.
    scale_factor:
        Override upscale factor (defaults to config SCALE_FACTOR).

    Returns
    -------
    List of paths written.
    """
    crop_path = Path(crop_path)
    atlas = GlyphAtlas(templates_dir)
    preprocessor = ImagePreprocessor(scale_factor=scale_factor) if scale_factor else ImagePreprocessor()
    segmenter = GlyphSegmenter()

    bgr = cv2.imread(str(crop_path), cv2.IMREAD_COLOR)
    if bgr is None:
        raise FileNotFoundError(f"Could not read crop image: {crop_path}")

    binary = preprocessor.preprocess(bgr)
    lines = segmenter.split_lines(binary)

    if len(lines) != len(line_labels):
        raise ValueError(
            f"Found {len(lines)} text line(s) in crop but got {len(line_labels)} label(s). "
            "Adjust CAPTURE_REGION or line_labels."
        )

    written: list[Path] = []
    for line_img, label in zip(lines, line_labels):
        glyphs = segmenter.segment_line(line_img)
        pairs = _align_label_to_glyphs(label, glyphs)

        for char, glyph_bitmap in pairs:
            out = atlas.save_template(char, glyph_bitmap)
            written.append(out)
            # Keep in-memory atlases warm if caller reuses this object later.
            if char in BALANCE_CHARSET:
                atlas._balance[char] = glyph_bitmap
            if char in USERNAME_CHARSET:
                atlas._username[char] = glyph_bitmap

    return written
