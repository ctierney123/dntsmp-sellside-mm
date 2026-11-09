# AH first-row price compare — timing research

**Date:** 2026-07-09  
**Scope:** `ah_price` multi-slot `--compare-only` / `--compare` path  
**Goal:** Scan 9 first-row AH listings and decide if slot 0 is cheapest, as fast as possible without flaking.

---

## Constraints (from product / game UI)

These are hard rules that shaped every design choice:

1. **AH price `$` is always green.**
2. **Other tooltip text can also be green** (armor durability, some armor lines). Never pick “first green pixel” — green is a filter, not an identity.
3. **`$` Y position changes per item** because enchant / lore lines change tooltip height. Locking Y from slot 0 will miss on later slots.

---

## Timeline of approaches (what we tried)

### 1. Full tooltip ROI every slot
- Capture `TOOLTIP_REGION` (~646×600) per slot, `matchTemplate` for `$`, OCR price strip.
- **Cost:** ~600–1000ms/slot → multi-second row scans.
- Correct but too slow.

### 2. Lock X+Y “price band” after slot 0
- After first `$` hit, later slots used a short horizontal band around expected `$` line.
- **Failed constraint #3:** enchant height moved `$` vertically → frequent band miss → expensive full-ROI fallback.
- Log pattern: slot 0 `full`, some `band` ~100ms, many `full` ~600–1000ms. Totals ~4–4.6s.

### 3. X-only vertical strip + green gate
- Lock **cursor → `$` X only**; capture tall skinny strip (full tooltip height × narrow width).
- Green-mask AND into binary before `$` template match; still require `$` glyph so green durability cannot win.
- **Worked when tooltip was painted.** Strip hits ~150–300ms; misses still fell back to full ROI.
- Totals improved to ~1.8s when strip stuck, but early settle was too aggressive and caused total failures.

### 4. Aggressive “zero settle + retries” / two-stage capture / scale-2
- Tried near-zero hover delay + many OCR retries → **burned time on empty frames** (tooltip not painted yet).
- Tried two-stage (narrow `$` column → second price-line grab) → second mss grab often not worth it; one wider strip is simpler.
- `AH_SCALE_FACTOR=2` with nearest-neighbor rescaled templates **works** when the tip is visible (live scores ~1.0). Scale-2 itself was not the total-failure cause.

### 5. Current winning shape (as of this note)
- **Seeded default `$` X offset** (`COMPARE_DEFAULT_DOLLAR_OFFSET_X_PX ≈ 45`) so slot 0 can start in strip mode.
- **One-grab strip:** tall narrow region wide enough for `$` + digits (~160px + pad).
- **AH scale 2** (HUD stays at 4); `$` + digit templates rescaled at runtime.
- **Short fixed settle** (~100ms slot 0 / ~60ms later) so first OCR usually succeeds.
- **On miss only:** cheap green-pixel poll, then one OCR retry; full ROI as last resort.
- **Green-row guided `$` search** inside the strip/ROI so blank rows are skipped.
- Trimmed `TOOLTIP_REGION` height (600 → 420) for cheaper full-ROI fallbacks.

**Live results (Minecraft AH open, netherite chestplate row):**  
- Consistently **9/9 ok**, all `strip` when offset is correct.  
- Best totals ~**980–1100ms**; typical ~1.0–1.3s.  
- Happy-path strip slot ~**90–100ms** (capture + preprocess + locate + OCR).

---

## Timing breakdown (happy path, scale 2, strip)

Approximate costs measured live:

| Stage | Full ROI (~646×420) | Strip (~184×420) |
|-------|---------------------|------------------|
| mss capture | ~30ms | ~20ms |
| preprocess (upscale+threshold) | ~45ms | ~5ms |
| `$` locate (green + template) | ~40ms | ~9ms |
| digit OCR + parse | ~13ms | ~17ms |
| **Subtotal (no settle)** | ~130ms | ~50ms |

Fixed sleeps dominate remaining budget:  
`0.10 + 8×0.06 ≈ 0.58s` settle alone. Failed OCR attempts (empty tip) cost more than a slightly longer settle.

---

## Design rules that held up

| Do | Don't |
|----|--------|
| Lock **X** of `$` relative to cursor | Lock **Y** across slots |
| Green-gate **then** `$` template | “First green blob” = price |
| Prefer short settle + one good OCR | Zero settle + many full OCR retries |
| Seed a default `$` X offset for strip-from-slot-0 | Force slot 0 through huge full ROI every time |
| Use AH-only lower scale (2) with rescaled templates | Assume HUD `SCALE_FACTOR=4` templates match AH binary without resize |
| Green-poll **after** OCR miss | Extra green capture on every happy-path slot |

---

## Config knobs that matter (`ah_price/config.py`)

| Knob | Role |
|------|------|
| `COMPARE_DEFAULT_DOLLAR_OFFSET_X_PX` | Seeded `$` X; enables strip on slot 0. Recalibrate if GUI scale / layout changes. |
| `COMPARE_DOLLAR_COLUMN_WIDTH_PX` / `PAD_X` | Strip must fit `$` + price digits. |
| `COMPARE_FIRST_HOVER_DELAY_SECONDS` / `COMPARE_AFTER_HOVER_DELAY_SECONDS` | Primary flake vs speed tradeoff. |
| `AH_SCALE_FACTOR` | 2 = fast; bump to 3–4 if `$`/digit match flakes. |
| `DOLLAR_GREEN_*` | Green gate for `$` search only (OCR still uses unmasked binary). |
| `TOOLTIP_REGION` height | Keep tall enough for long enchant tips; trim empty bottom for speed. |
| `COMPARE_TOOLTIP_POLL_*` / `COMPARE_OCR_RETRY_*` | Miss path only. |

---

## Failure modes we hit

1. **Tooltip not painted yet** — looks like “No non-HUD `$` matches.” Fix: settle / green-poll / retry. Not a template bug.
2. **Y-locked band** — enchant height change → systematic strip/band miss → full ROI storm.
3. **Green-only selection** — would confuse durability with price (avoided by keeping `$` template).
4. **Scale mismatch** — templates authored at HUD scale 4; AH at scale 2 needs nearest-neighbor resize + re-binarize.
5. **Polling with full OCR** — empty-frame OCR retries made totals *worse* than a fixed 50–60ms settle.

---

## Further speedups (not yet shipped / mixed results)

Worth revisiting if we need sub‑800ms:

1. **Early-exit when any later slot is cheaper than slot 0** — speeds the arb “buy” case; still need all 9 when slot 0 wins.
2. **Per-stage timers in the summary** — capture / prep / locate / OCR / settle / retry so tuning isn’t guesswork.
3. **Skip `$` in digit OCR** — already located; crop starting just right of `$` (parser already accepts optional `$`).
4. **Tighter strip height after first `$` Y sample with large pad** — risky vs constraint #3; only if Y variance is bounded in practice.
5. **Avoid `np.array(mss).copy()`** if profiling shows capture still hot.

Low value: parallel OCR (mouse is serial), GPU CV, cutting settle without readiness checks.

---

## Key modules

- `ah_price/price_compare_manager.py` — hover loop, settle, green-poll-on-miss, strip vs full.
- `ah_price/price_band_tracker.py` — X-only offset + strip region (seeded default).
- `ah_price/dollar_locator.py` — green gate, green-row bands, `$` template (AH-scale aware).
- `ah_price/tooltip_price_reader.py` — capture → locate → OCR; strip path `read_price_two_stage`.
- `ah_price/config.py` — all tunables above.

---

## Bottom line

The row scan is limited by **tooltip spawn latency** and **pixels processed per slot**, not by mouse move duration. Respecting “green `$` but not first-green” and “X locked, Y free” got us from ~4.5s → ~1s with reliable 9/9. Further gains should attack settle waste and per-slot pixel work, not reintroduce Y locking.
