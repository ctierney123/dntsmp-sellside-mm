# Own-listing skip (don't rebuy what we just /ah sell'd)

## Problem

After sell-after-buy, our undercut often sits in the first AH row. A later
pass can treat it as a snag, left-click it, and DonutSMP sends you to the
collect / achievement UI instead of buying someone else's listing.

Price-only matching is not enough: someone else can list the same coin
amount. We also cannot OCR a seller name from the tooltip today.

## Approach

1. **`OwnListingTracker`** — after a successful `/ah sell`, record
   `{query, sell_coins, listed_at}`. TTL defaults to 6h
   (`OWN_LISTING_TTL_SECONDS`).
2. **Before buy** — if the undercut's price matches a recorded sell for
   that query, re-hover the slot and capture a binary tooltip fingerprint
   (`OwnListingFingerprintCaptureManager` + `TooltipFingerprintMatcher`).
3. **Match rules**
   - First re-sighting (no fingerprint yet): claim the tip as ours → skip.
   - Later: require near-1:1 NCC score ≥ `OWN_LISTING_TOOLTIP_MATCH_THRESHOLD`
     (default 0.92). Same price + different tip → allow buy (someone else).
   - Capture failed but price hits an open sell → skip conservatively.
4. **`UndercutDetector.find_opportunity(..., exclude_slots=...)`** — after
   skipping our slot in a later row position, try the next in-band undercut.
   Market median still uses the full priced row so excluding ourselves does
   not warp the going rate.
5. **Slot 0 abort** — if the own-listing match is **slot 0**, do **not**
   buy slot 1+. Abort that search. Chasing the next undercut after a
   fingerprint hit on slot 0 has clicked our own listing by mistake
   (hover/click drift after re-hover fingerprint capture).

## Knobs (`ah_price/config.py`)

- `OWN_LISTING_SKIP_ENABLED`
- `OWN_LISTING_TTL_SECONDS`
- `OWN_LISTING_TOOLTIP_MATCH_THRESHOLD`
- `OWN_LISTING_FINGERPRINT_HOVER_DELAY_SECONDS`

## Limits

- In-memory only (lost on process restart).
- Fingerprint is claimed on first re-sighting, not at sell time (we Esc
  out of AH before `/ah sell`).
- Does not cover listings placed manually outside the bot.
- Slot 0 own-listing → full search skip (no slot 1+ chase). Tradeoff:
  we may miss a real undercut sitting next to our listing that pass.
