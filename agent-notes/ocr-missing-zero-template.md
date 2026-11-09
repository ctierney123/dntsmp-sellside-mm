# OCR: missing `0.png` → `10.xM` read as `18.xM`

## Symptom

Armor arb bought netherite ingots after reading the whole first row as `$18.xM`
when the true AH prices were `$10.xM`. Undercut math looked fine on the wrong
numbers, so it purchased and listed near the bogus “market.”

Example log (2026-07-09):

```text
slot 0: $18.1M … slot 8: $18.5M
Undercut hit: slot 0 @ $18.1M … below market (18500000)
Purchasing slot 0 …
Sell price: 18.3m …
```

## Root cause

`templates/0.png` was **missing**. Atlas only had `1`–`9`.

`LineRecognizer` always picks the best template match above
`MATCH_SCORE_THRESHOLD` (0.55). A Minecraft `0` glyph correlates ~0.66 with
`8.png` when `0` is not in the atlas — so every zero becomes an eight:

| Atlas | Zero glyph best match |
|-------|------------------------|
| no `0.png` | `8` @ ~0.66 |
| with `0.png` | `0` @ 1.0 |

Atlas was built from HUD balances that never contained a `0` (e.g. `$ 62.1M`,
`$ 52.1M`), so `--build-atlas` never wrote `0.png`.

## Fix

1. Ensure `templates/0.png` exists (extracted from a live `$70M` HUD crop, or
   rebuild atlas when balance shows a zero).
2. `GlyphAtlas.load()` now **fail-fast** if any of `$0123456789.` is missing,
   so the bot cannot start in this state again.

## Rebuild tips

```powershell
# HUD must currently show a balance that includes 0 (and ideally other digits)
python -m screen_reader --build-atlas PlayerName "$ 70.2M"
```

Wrong live label still mis-names files (README warning). Prefer a balance that
contains every digit you care about, or merge templates across multiple builds
without deleting existing digit PNGs you still need.

## Related

- `screen_reader/glyph_atlas.py` — load + `assert_required_balance_templates`
- `screen_reader/recognizer.py` — best-match OCR (no “unknown digit” path)
- `ah_price/tooltip_price_reader.py` — AH price OCR uses the same atlas
