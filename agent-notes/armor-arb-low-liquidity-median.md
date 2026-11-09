# Armor arb — low-liquidity front-window median

**Date:** 2026-07-09  
**Symptom:** Thin staircase books like `5.1 5.2 5.3 5.4 5.5 5.6…` (few/no repeated prices) made the full-row median sit far right. Buying the left snag vs that median looked profitable, then sell had to undercut the next real listing and ate the edge (slippage).

**Root cause:** `MarketPriceEstimator` always used median of **all** priced slots. That is correct for thick walls (`6.4×6`), wrong when the book is a smooth ascending staircase with no cluster.

**Fix:**
- `OrderBookLiquidityClassifier` — low liquidity when the busiest exact price repeats ≤ `ARMOR_ARB_LOW_LIQUIDITY_MAX_PRICE_REPEAT` (default **2**).
- On low liquidity, median uses only the **cheapest N** prices (`ARMOR_ARB_LOW_LIQUIDITY_MEDIAN_WINDOW`, default **4**).
- Buy + sell both go through the same estimator, so outlier / competitive-ref logic stays consistent.

**Example:** `5.1…5.9` → front median `5.25M` → `5.1M` is only 150k under → below 199k floor → skip. Thick `6.0 / 6.1 / 6.4×6` unchanged (full median `6.4M`).
