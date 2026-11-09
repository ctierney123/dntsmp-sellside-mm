# Balance floor — HUD OCR vs in-menu reads

**Date:** 2026-07-09  
**Symptom:** Pre-buy balance check during `--armor-arb` logged  
`Expected 2 HUD text lines … found 0/1` right after a successful first-row
compare (AH still open). Sword undercut hit this while chest/legs/helm/boots
had already skipped with no buy.

## Cause

`ensure_above_floor(context="pre-buy …")` ran **while AH was open**. The
scoreboard `CAPTURE_REGION` is covered / empty in that GUI, so line-split
fails.

## Fix (implemented)

- **Removed** mid-AH pre-buy balance OCR from `ArmorArbManager._run_one_query`.
- **Once per pass:** `run_pass()` calls `ensure_above_floor(context="pass start")`
  before any `/ah` search (clear HUD). Covers both `--armor-arb` and
  `--armor-arb-loop` (loop no longer double-checks before `run_pass`).

Smoke-test:

```text
python -m ah_price --test-balance
python -m ah_price --test-balance --balance-repeats 5
```

## Follow-up (optional)

Track cash in memory within a pass (subtract buys / account for listed sells)
so a long pass with many snags cannot drift under the floor without waiting
for the next pass-start OCR. Not required to stop the menu OCR bug.
