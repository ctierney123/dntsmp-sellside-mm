# Armor arb order-book / price-check log

**Date:** 2026-07-10

## Problem

Purchase JSON only records books at buy time (`checked_prices`). Overnight
analysis also needs every first-row OCR — including skips, ceiling exits,
and early-buy partial rows.

## Fix

`ArmorArbOrderBookLogManager` appends one JSONL line per item price check
during `--armor-arb-loop` (planned passes + rechecks). Files land in
`logs/armor_arb_order_books/order_books_<session_id>.jsonl`.

Each record includes query, pass/kind, purchased/skip_reason, early_stopped,
opportunity (if any), sell_coins (if sold), and `prices` (slot / price /
price_raw / ok).

## Tunables (`ah_price/config.py`)

- `ARMOR_ARB_ORDER_BOOK_LOG_ENABLED` (default True)
- `ARMOR_ARB_ORDER_BOOK_LOG_DIR`
