# Armor arb undercut max band + early slot-0 buy

**Date:** 2026-07-10

**Symptom:** Live row `5.0M, 6.7M×8` printed `first_is_lowest: True` then
`No undercut in band [199,000 .. 1,500,000]`. Discount vs median was
**1.7M**, above the old 1.5M ceiling.

**Fix:**
- `ARMOR_ARB_UNDERCUT_MAX_COINS` raised to **2.5M**.
- After OCR'ing slots **0–3**, `EarlySlot0BuyDetector` may stop the compare
  early when slot 0 is clearly under 1/2/3 (in-band vs neighbor median, and
  ≥199k under the next-cheapest so stacked 6.0/6.1/6.2 books still scan the
  full row for sell pricing).
- Purchase JSON now includes `checked_prices` (the OCR'd row at buy time).
