# TOOLTIP_REGION height — long enchant tips clip `$`

**Date:** 2026-07-10  
**Symptom:** Armor arb `/ah netherite boots` — slots 0–1 fail with
`Could not find a non-HUD $ in TOOLTIP_REGION after retries`; later slots
OCR fine (`$6.6M` / `$6.7M` via strip).

## Cause

AH buy-price `$` sits near the **bottom** of the tooltip. Enchant / lore
lines push it down. `TOOLTIP_REGION.height` was trimmed **600 → 420** for
faster full-ROI fallbacks (see `ah-price-compare-timing-research.md`).

Live happy-path `$` was already at upscaled `(24, 570)` with `AH_SCALE_FACTOR=2`
→ ~285px into the crop. Heavily enchanted boots (often the cheapest early
slots) need more vertical room; green durability can still satisfy the
green-ready poll while `$` is **below** the crop → retries still fail.

Strip height tracks `TOOLTIP_REGION.height`, so both strip and full ROI
were short.

## Fix

Bump `TOOLTIP_REGION.height` **420 → 520** (+100px downward). Revisit if
swords / other long tips still flake; prefer height over re-locking Y.
