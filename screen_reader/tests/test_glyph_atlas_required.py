"""Tests for GlyphAtlas required-digit fail-fast."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from screen_reader.glyph_atlas import GlyphAtlas


class GlyphAtlasRequiredTemplatesTest(unittest.TestCase):
    """Casual: make sure we refuse to run without a zero sticker."""

    def test_load_raises_when_zero_missing(self) -> None:
        """Missing 0.png must hard-fail (historically became 8)."""
        with tempfile.TemporaryDirectory() as tmp:
            templates_dir = Path(tmp)
            # Write every required char except 0.
            for char, stem in [
                ("$", "dollar"),
                (".", "dot"),
                *[(str(d), str(d)) for d in range(1, 10)],
            ]:
                bitmap = np.zeros((8, 8), dtype=np.uint8)
                bitmap[2:6, 2:6] = 255
                Image.fromarray(bitmap).save(templates_dir / f"{stem}.png")

            atlas = GlyphAtlas(templates_dir)
            with self.assertRaises(FileNotFoundError) as ctx:
                atlas.load()
            self.assertIn("0", str(ctx.exception))

    def test_load_ok_with_full_digit_set(self) -> None:
        """Full $0123456789. set should load cleanly."""
        with tempfile.TemporaryDirectory() as tmp:
            templates_dir = Path(tmp)
            for char, stem in [
                ("$", "dollar"),
                (".", "dot"),
                *[(str(d), str(d)) for d in range(10)],
                ("M", "M"),
            ]:
                bitmap = np.zeros((8, 8), dtype=np.uint8)
                bitmap[1:7, 1:7] = 255
                Image.fromarray(bitmap).save(templates_dir / f"{stem}.png")

            atlas = GlyphAtlas(templates_dir)
            atlas.load()
            self.assertIn("0", atlas.balance_templates)
            self.assertIn("8", atlas.balance_templates)


if __name__ == "__main__":
    unittest.main()
