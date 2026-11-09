# Armor arb undercut — median vs next-cheapest

**Date:** 2026-07-09  
**Symptom:** Live row like `6.0M, 6.1M, 6.3M, 6.4M×6` printed "No undercut" even though slot 0 was clearly a snag.

**Root cause:** `UndercutDetector` measured discount as `min(others) - candidate`. Slot 0 vs slot 1 was only **100k**, below `ARMOR_ARB_UNDERCUT_MIN_COINS` (199k). Stacked left-side undercuts cancelled each other.

**Fix:** Market reference is now the **median** of all priced slots (`MarketPriceEstimator`). Discount = `median - candidate`. Still buys **one** listing (cheapest in-band; leftmost on ties). Same 199k–1.5m band.

**Your example:** median = 6.4M → slot 0 discount = 400k → buy slot 0.

**Follow-up:** Thin staircase books (no price wall) now use a front-of-book median window instead of the full row — see `armor-arb-low-liquidity-median.md`.
