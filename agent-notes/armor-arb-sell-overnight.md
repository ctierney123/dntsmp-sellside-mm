# Armor arb sell-after-buy + overnight loop

**Date:** 2026-07-09  
**Goal:** After each undercut buy, immediately `/ah sell` so hotbar slot 1 stays empty; loop overnight with a 30m balance floor.

## Sell price rule

- Default: **100k under the 2nd-lowest** remaining listing (we bought the lowest).
- Stacked snags: skip remaining prices that are still **≥199k under the row median** (same floor as buy), then undercut the first competitive price.
- Example book `7m, 7.1m, 7.7×4, 7.8×3` after buying `7m` → skip `7.1m` → sell **`7.6m`**.

Implemented in `SellPriceCalculator` + `AhPriceFormatter` (`7.6m` chat form).

## Hotbar / sequencing

- Purchases land in **hotbar 1** (must stay empty between buys).
- Flow: buy (+ Yes if needed) → Esc AH → key `1` → `/ah sell <price>`.
- Never start the next search buy until that sell attempt finishes.
- Inter-search Esc only when the previous query did **not** purchase (skip path leaves AH open). After sell we are already on the HUD — a second Esc would open pause.

## Balance floor

- HUD `read_once()` balance must stay **≥ 30m** — checked **once per pass**
  at `run_pass()` start (clear HUD), never mid-AH before a buy.
- Under floor → wait **5 min**, re-check.
- **3 consecutive** under-floor (or failed) checks → `BalanceFloorHalt` / program exit.
- See `agent-notes/balance-hud-read-vs-menu.md`.
  Smoke test: `python -m ah_price --test-balance`.

## Parse-failure halt

- First-row tooltip OCR `FAIL` slots are counted for the whole overnight
  session (`ParseFailureGuardManager`).
- Only **slots 0–4** count (`ARMOR_ARB_PARSE_COUNTED_SLOTS`). Slots **5+**
  often miss `$` on very tall tooltips (ROI clips) — those FAILs are
  accepted and never burn the one-off / halt budget.
- **1 one-off** failed counted slot is tolerated (printed, continue).
- Any **further** counted FAIL (same search or later) → `ParseFailureHalt`
  and the overnight loop exits. Repeated left/center parse fails mean
  focus / calibration / region is wrong — do not keep buying blind.
- Tunable: `ARMOR_ARB_PARSE_MAX_ONE_OFF_FAILURES` (default `1`).
- Single-shot `--armor-arb` does not attach this guard (overnight only).

## Overnight loop

`python -m ah_price --armor-arb-loop`

- Each pass: **shuffle** `ARMOR_ARB_SEARCH_QUERIES`; **~35%** chance of a
  random **subset** (`ARMOR_ARB_LOOP_SUBSET_*`, default 2..(catalog-1)).
- If the pass bought anything: **immediate recheck** of those queries
  before inter-pass sleep (`ARMOR_ARB_LOOP_RECHECK_BOUGHT`). No second
  balance OCR; recheck purchases do not trigger another recheck.
- Between passes: uniform **5–60s** sleep.
- **10%** chance of extra **2–5 min** pause.
- `--no-sleep`: skip both inter-pass sleeps (testing; default keeps delays).
- Planner: `ArmorArbPassPlanner`. Tunables in `ah_price/config.py`
  (`ARMOR_ARB_SELL_*`, `ARMOR_ARB_MIN_BALANCE_*`, `ARMOR_ARB_LOOP_*`,
  `ARMOR_ARB_PARSE_MAX_ONE_OFF_FAILURES`).

## End-of-pass Esc (clear HUD)

**Symptom:** Pass 1 ends on a skip (e.g. ingot); pass 2 balance OCR fails with
`Expected 2 HUD text lines … found 0` because AH results were still open.

**Fix:** `run_pass()` Escs after the last query when that query did **not**
purchase (same rule as inter-search). Buy+sell already left the HUD — do not
Esc again (pause menu).
