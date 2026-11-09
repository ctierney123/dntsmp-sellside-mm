"""
Segment binary text images into individual glyph crops.
"""

from __future__ import annotations

import cv2
import numpy as np

from screen_reader.config import MIN_GLYPH_AREA


class GlyphSegmenter:
    """
    Split a binary line image into left-to-right glyph bitmaps.

    Casual: chops a line of text into one small image per letter.
    Uses connected components first; falls back to fixed-width columns if needed.
    """

    def segment_line(self, binary_line: np.ndarray) -> list[np.ndarray]:
        """
        Return glyph crops sorted left-to-right.

        Casual: list of little letter pictures from one text row.
        """
        glyphs = self._segment_connected_components(binary_line)
        if glyphs:
            return glyphs
        return self._segment_fixed_width(binary_line)

    def split_lines(self, binary: np.ndarray) -> list[np.ndarray]:
        """
        Split a multi-line binary crop into individual horizontal text bands.

        Casual: if username is on top and balance below, this gives two strips.
        Uses horizontal projection (count of white pixels per row).
        """
        if binary.size == 0:
            return []

        row_sums = np.sum(binary > 0, axis=1)
        if not np.any(row_sums):
            return []

        # Rows with ink belong to a line; blank rows separate lines.
        ink_rows = row_sums > 0
        lines: list[np.ndarray] = []
        start: int | None = None

        for row_idx, has_ink in enumerate(ink_rows):
            if has_ink and start is None:
                start = row_idx
            elif not has_ink and start is not None:
                lines.append(binary[start:row_idx, :])
                start = None

        if start is not None:
            lines.append(binary[start:, :])

        return lines

    def _segment_connected_components(self, binary_line: np.ndarray) -> list[np.ndarray]:
        """Find each blob of white pixels and crop it."""
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
            binary_line, connectivity=8
        )

        candidates: list[tuple[int, int, np.ndarray]] = []
        for label_idx in range(1, num_labels):
            x = int(stats[label_idx, cv2.CC_STAT_LEFT])
            y = int(stats[label_idx, cv2.CC_STAT_TOP])
            w = int(stats[label_idx, cv2.CC_STAT_WIDTH])
            h = int(stats[label_idx, cv2.CC_STAT_HEIGHT])
            area = int(stats[label_idx, cv2.CC_STAT_AREA])

            if area < MIN_GLYPH_AREA:
                continue

            mask = (labels[y : y + h, x : x + w] == label_idx).astype(np.uint8) * 255
            candidates.append((x, y, mask))

        candidates.sort(key=lambda item: item[0])
        return [crop for _, _, crop in candidates]

    def _segment_fixed_width(self, binary_line: np.ndarray) -> list[np.ndarray]:
        """
        Fallback: assume monospace font with uniform advance width.

        Casual: equal-width slices when blob detection fails.
        """
        height, width = binary_line.shape[:2]
        if height == 0 or width == 0:
            return []

        col_sums = np.sum(binary_line > 0, axis=0)
        if not np.any(col_sums):
            return []

        # Estimate glyph width from the widest ink column run.
        ink_cols = np.where(col_sums > 0)[0]
        if len(ink_cols) == 0:
            return []

        # Heuristic: Minecraft default font cell is ~6–8 px at 1x; we use projection gaps.
        gaps = self._find_column_gaps(col_sums)
        if len(gaps) < 2:
            advance = max(1, width // max(1, len(ink_cols)))
            return self._slice_by_advance(binary_line, advance)

        glyphs: list[np.ndarray] = []
        prev = 0
        for gap_start in gaps:
            if gap_start > prev:
                glyphs.append(binary_line[:, prev:gap_start])
            prev = gap_start + 1
        if prev < width:
            glyphs.append(binary_line[:, prev:width])

        return [g for g in glyphs if np.sum(g > 0) >= MIN_GLYPH_AREA]

    def _find_column_gaps(self, col_sums: np.ndarray) -> list[int]:
        """Return x positions where a full blank column separates glyphs."""
        gaps: list[int] = []
        in_gap = False
        for x, count in enumerate(col_sums):
            if count == 0 and not in_gap:
                in_gap = True
                gaps.append(x)
            elif count > 0:
                in_gap = False
        return gaps

    def _slice_by_advance(self, binary_line: np.ndarray, advance: int) -> list[np.ndarray]:
        """Slice the line every `advance` pixels."""
        glyphs: list[np.ndarray] = []
        width = binary_line.shape[1]
        for x in range(0, width, advance):
            chunk = binary_line[:, x : x + advance]
            if np.sum(chunk > 0) >= MIN_GLYPH_AREA:
                glyphs.append(chunk)
        return glyphs
