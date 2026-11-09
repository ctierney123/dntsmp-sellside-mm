# Armor arb loop overview + metrics + purchase log

**Date:** 2026-07-09

## Problem

Overnight `--armor-arb-loop` shuffles / subsets the catalog each pass, so the
end-of-pass `=== Armor arb complete ===` overview printed items in search
order and was hard to scan. Also wanted session / rolling metrics and a
timestamped purchase JSON log for post-session analysis.

## Fix

1. **Stable overview** — `ArmorArbManager.run_pass` still executes in planned
   order (`items`), but builds `overview_items` via
   `_items_in_catalog_order` (constructor catalog order) for
   `_print_final_summary`.

2. **Metrics** — `ArmorArbSessionMetricsManager` tracks planned passes +
   purchases; after each overnight lap prints session totals and a rolling
   window (`ARMOR_ARB_METRICS_WINDOW_SECONDS`, default 15 min): avg
   purchases/loop, avg profit/buy, avg profit margin, totals. Recheck buys
   fold into the parent pass's purchase count (do not create a new loop).

3. **Purchase JSON** — `ArmorArbPurchaseLogManager` buffers in memory until
   session purchases **exceed** `ARMOR_ARB_PURCHASE_LOG_MIN_SESSION_PURCHASES`
   (default 10), then writes
   `logs/armor_arb_purchases/purchases_<session_id>.json` and appends after.
   Unit-tested with a temp dir; production path is gitignored under `logs/`.

## Tunables (`ah_price/config.py`)

- `ARMOR_ARB_METRICS_WINDOW_SECONDS`
- `ARMOR_ARB_PURCHASE_LOG_MIN_SESSION_PURCHASES`
- `ARMOR_ARB_PURCHASE_LOG_DIR`
