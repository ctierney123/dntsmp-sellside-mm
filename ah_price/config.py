"""
Configuration for AH tooltip price reading + input automation.

Casual: coords and timings you calibrate once, then leave alone.
Separate from the HUD reader's CAPTURE_REGION so scoreboard OCR and
auction-house tooltip OCR don't fight over the same box.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Where to hover the first Auction House listing (absolute screen pixels).
# Capture with: python -m ah_price --setup
# ---------------------------------------------------------------------------
ITEM_HOVER_XY: tuple[int, int] = (683, 184)

# ROI big enough for the whole floating tooltip (enchants change height).
# Prefer a box that does NOT include the scoreboard CAPTURE_REGION.
# During multi-slot compare this box is shifted with the cursor (see
# SlotGridManager.tooltip_region_for_hover) so right-side slots still work.
TOOLTIP_REGION: dict[str, int] = {
    "left": 716,
    "top": 136,
    "width": 646,
    # Tall enough for long enchant tooltips (boots/swords can push $ near the
    # bottom). Was 420 after a speed trim; heavily enchanted netherite boots
    # clipped the price line → "no non-HUD $" on early slots. +100px headroom.
    "height": 520,
}

# ---------------------------------------------------------------------------
# First-row AH slot grid (usually 9 listings across).
# Capture spacing with: python -m ah_price --setup-slots
# SLOT_SPACING_XY is the pixel delta from slot 0 → slot 1 (typically ~dx, 0).
# ---------------------------------------------------------------------------
SLOT_COUNT: int = 9
SLOT_SPACING_XY: tuple[int, int] = (72, 0)

# Chat command typed after pressing T.
AH_SEARCH_QUERY: str = "/ah netherite chestplate"

# ---------------------------------------------------------------------------
# Netherite armor arb loop (--armor-arb): search each piece, compare row,
# buy when the cheapest listing is undercut vs the row's median price.
# ---------------------------------------------------------------------------
ARMOR_ARB_SEARCH_QUERIES: tuple[str, ...] = (
    "netherite chestplate",
    "netherite leggings",
    "netherite helm",
    "netherite boots",
    "netherite sword",
    "netherite ingot",
)
# Discount vs the row's market median must sit in this inclusive band.
# Median (not next-cheapest) so 1–3 stacked undercuts still qualify.
ARMOR_ARB_UNDERCUT_MIN_COINS: int = 299_000
ARMOR_ARB_UNDERCUT_MAX_COINS: int = 4_500_000

# Early buy: after probing slots 0..N-1, if slot 0 is clearly cheap vs
# slots 1..N-1 (in-band undercut + ≥min gap to the next-cheapest), skip
# the rest of the row and buy immediately. Saves ~5 slot OCR round-trips
# on obvious snags like 5.0 / 5.6 / 5.6 / 5.7.
ARMOR_ARB_EARLY_BUY_PROBE_SLOT_COUNT: int = 3

# Per-item slot-0 price ceilings: if slot 0 is STRICTLY above the cap,
# skip the whole search (no buy). Keys match the item name after `/ah `
# (case-insensitive). Netherite ingots normally sit ~10m; >10.1m is either
# a dead/weird book or OCR garbage (historically 10.x → 18.x without 0.png).
ARMOR_ARB_SLOT0_PRICE_CEILINGS: dict[str, int] = {
    "netherite ingot": 10_100_000,
    # Swords above ~7.1m rarely leave sellable edge after undercut/fees.
    "netherite sword": 7_100_000,
}

# Low-liquidity books (staircase of mostly unique prices, e.g. 5.1…5.6)
# have no thick price wall. Full-row median sits too far right and invents
# buy edge you cannot sell into. When the busiest price repeats at most
# this many times, market median uses only the cheapest N listings.
ARMOR_ARB_LOW_LIQUIDITY_MAX_PRICE_REPEAT: int = 2
ARMOR_ARB_LOW_LIQUIDITY_MEDIAN_WINDOW: int = 4

# ---------------------------------------------------------------------------
# Sell-after-buy: list the purchased hotbar item immediately.
# Sell = competitive_reference - 100k. Competitive = first remaining listing
# that is NOT an egregious undercut vs the row median (same 199k floor as buy).
# ---------------------------------------------------------------------------
ARMOR_ARB_SELL_UNDERCUT_COINS: int = 100_000
# Hotbar slot that receives the bought item (Minecraft key 1–9).
ARMOR_ARB_SELL_HOTBAR_SLOT: int = 1
AFTER_HOTBAR_SELECT_DELAY_SECONDS: float = 0.20
AFTER_SELL_COMMAND_DELAY_SECONDS: float = 1.0

# ---------------------------------------------------------------------------
# Own-listing skip: after /ah sell, remember query+price so we don't click
# our own listing later (DonutSMP sends you to the collect/achievement UI).
# On a price hit we re-hover and require a near-1:1 tooltip fingerprint match
# (or claim the first sighting when we have no fingerprint yet).
# ---------------------------------------------------------------------------
OWN_LISTING_SKIP_ENABLED: bool = True
# How long to keep a recorded sell in memory (AH listings expire eventually).
OWN_LISTING_TTL_SECONDS: float = 6 * 60 * 60.0
# Normalized cross-correlation peak required to treat two binary tooltips as
# the same listing. High on purpose — user asked for near-1:1 visual match.
OWN_LISTING_TOOLTIP_MATCH_THRESHOLD: float = 0.92
# Tiny settle before capturing a fingerprint on a candidate buy slot.
OWN_LISTING_FINGERPRINT_HOVER_DELAY_SECONDS: float = 0.10

# ---------------------------------------------------------------------------
# Overnight loop (--armor-arb-loop): keep running passes with human-ish gaps.
# Balance floor: never keep buying if HUD balance drops below 30m; wait and
# re-check. Three consecutive failed checks halt the whole program.
# ---------------------------------------------------------------------------
ARMOR_ARB_MIN_BALANCE_COINS: int = 30_000_000
ARMOR_ARB_BALANCE_WAIT_SECONDS: float = 5 * 60.0
ARMOR_ARB_BALANCE_MAX_FAILURES: int = 3
# Overnight tooltip OCR: tolerate this many failed slot parses for the whole
# session (default 1 = one flaky miss). Any further FAIL halts the night —
# repeated parse fails mean calibration / focus / region is wrong.
ARMOR_ARB_PARSE_MAX_ONE_OFF_FAILURES: int = 1
# Only FAILs on these first-row slots count toward the overnight halt.
# Slots 5+ often miss $ on very tall tooltips (ROI clips) — ignore those.
ARMOR_ARB_PARSE_COUNTED_SLOTS: tuple[int, ...] = (0, 1, 2, 3, 4)
ARMOR_ARB_LOOP_SLEEP_MIN_SECONDS: float = 5.0
ARMOR_ARB_LOOP_SLEEP_MAX_SECONDS: float = 60.0
# Extra 2–5 min pause only after a planned pass with zero purchases
# (full skips). Passes that bought something never roll this.
ARMOR_ARB_LONG_PAUSE_CHANCE: float = 0.10
ARMOR_ARB_LONG_PAUSE_MIN_SECONDS: float = 2 * 60.0
ARMOR_ARB_LONG_PAUSE_MAX_SECONDS: float = 5 * 60.0
# Mix up search order every overnight pass; sometimes only poke a few items.
ARMOR_ARB_LOOP_SUBSET_CHANCE: float = 0.35
ARMOR_ARB_LOOP_SUBSET_MIN_ITEMS: int = 2
# None → cap at len(catalog)-1 so a subset pass is actually shorter.
ARMOR_ARB_LOOP_SUBSET_MAX_ITEMS: int | None = None
# After a pass that bought something, re-check those items once before sleep.
ARMOR_ARB_LOOP_RECHECK_BOUGHT: bool = True
# Rolling window for "past N minutes" metrics printed after each overnight pass.
ARMOR_ARB_METRICS_WINDOW_SECONDS: float = 15 * 60.0
# Purchase JSON log: buffer in memory until the session exceeds this many
# buys, then flush + keep appending (avoids tiny one-off session files).
ARMOR_ARB_PURCHASE_LOG_MIN_SESSION_PURCHASES: int = 10
ARMOR_ARB_PURCHASE_LOG_DIR: Path = (
    Path(__file__).resolve().parent.parent / "logs" / "armor_arb_purchases"
)
# Order-book JSONL: one line per price check (buys + skips), always on by
# default so overnight sessions keep a full scan history separate from buys.
ARMOR_ARB_ORDER_BOOK_LOG_ENABLED: bool = True
ARMOR_ARB_ORDER_BOOK_LOG_DIR: Path = (
    Path(__file__).resolve().parent.parent / "logs" / "armor_arb_order_books"
)

# ---------------------------------------------------------------------------
# High-price "Are you sure?" buy confirm dialog.
# Capture with: python -m ah_price --setup-buy-confirm
# Detector OCRs BUY_CONFIRM_YES_REGION for the word Yes, then clicks YES_XY.
# Leave region width/height at 0 until calibrated (detector stays disabled).
# ---------------------------------------------------------------------------
BUY_CONFIRM_YES_XY: tuple[int, int] = (1262, 428)
BUY_CONFIRM_YES_REGION: dict[str, int] = {
    "left": 1222,
    "top": 407,
    "width": 87,
    "height": 38,
}
# Whole-word Yes binary template written by --setup-buy-confirm.
BUY_CONFIRM_YES_TEMPLATE: Path = (
    Path(__file__).resolve().parent.parent / "templates" / "buy_confirm_yes.png"
)
BUY_CONFIRM_MATCH_THRESHOLD: float = 0.55
BUY_CONFIRM_POLL_SECONDS: float = 0.70
BUY_CONFIRM_POLL_INTERVAL_SECONDS: float = 0.05
AFTER_BUY_CONFIRM_CLICK_DELAY_SECONDS: float = 0.25
BUY_CONFIRM_DEBUG_IMAGE: Path = Path("ah_buy_confirm_yes_debug.png")

# ---------------------------------------------------------------------------
# Timing knobs (seconds) — bump these if Minecraft / AH feels laggy.
# ---------------------------------------------------------------------------
FOCUS_COUNTDOWN_SECONDS: float = 3.0
CHAT_OPEN_DELAY_SECONDS: float = 0.25
TYPE_INTERVAL_SECONDS: float = 0.03
AFTER_ENTER_DELAY_SECONDS: float = 1.0
AFTER_HOVER_DELAY_SECONDS: float = 0.45
# Escape settle must clear the AH GUI before T opens chat; too short and the
# leading "/ah net…" keystrokes get eaten (chat posts "herite boots").
AFTER_ESCAPE_DELAY_SECONDS: float = 0.70
AFTER_PURCHASE_CLICK_DELAY_SECONDS: float = 0.25
ARMOR_ARB_BETWEEN_SEARCH_DELAY_SECONDS: float = 0.35

# ---------------------------------------------------------------------------
# Market making / spread check (--spread-check).
# Sell book = /ah <item> (slot 0 = cheapest ask).
# Buy book  = /order <item> (slot 0 = highest bid).
# Spread    = ask - bid. Paste chat text; snap to slot 0 ASAP.
# ---------------------------------------------------------------------------
MARKET_MAKING_DEFAULT_ITEM: str = "enchanted golden apple"
# After Enter: let the AH/order GUI paint before we move onto slot 0.
MARKET_MAKING_AFTER_ENTER_DELAY_SECONDS: float = 0.10
# Extra settle once the cursor is sitting on slot 0 (tooltip spawn).
MARKET_MAKING_SLOT0_HOVER_DELAY_SECONDS: float = 0.10
# Escape settle between /ah and /order (must clear GUI before next chat).
MARKET_MAKING_AFTER_ESCAPE_DELAY_SECONDS: float = 0.70
# Instant mouse teleport onto slot 0 (same idea as compare scan).
MARKET_MAKING_MOUSE_MOVE_DURATION_SECONDS: float = 0.0
# Park this many pixels left/up of slot 0 so the menu can open under a
# cursor that is NOT already on the listing (Minecraft skips tooltips if
# the mouse never "enters" the slot after the GUI paints).
MARKET_MAKING_PARK_OFFSET_XY: tuple[int, int] = (-120, -80)

# Fast multi-slot compare: settle enough that the tip is usually ready on the
# first OCR attempt (failed captures cost more than a short sleep).
COMPARE_MOUSE_MOVE_DURATION_SECONDS: float = 0.0
COMPARE_FIRST_HOVER_DELAY_SECONDS: float = 0.10
COMPARE_AFTER_HOVER_DELAY_SECONDS: float = 0.06
COMPARE_PYAUTOGUI_PAUSE_SECONDS: float = 0.0

# After (or before) the first $, slots capture a tall narrow strip that fits
# both the $ glyph and the price digits. X is locked; Y is free for enchants.
# DEFAULT offset lets slot 0 start in strip mode (calibrate if your GUI scale differs).
COMPARE_DEFAULT_DOLLAR_OFFSET_X_PX: float = 45.0
COMPARE_DOLLAR_COLUMN_WIDTH_PX: int = 160
COMPARE_DOLLAR_COLUMN_PAD_X_PX: int = 12
# Kept for optional / debug price-line crops.
COMPARE_PRICE_LINE_WIDTH_PX: int = 140
COMPARE_PRICE_LINE_HEIGHT_PX: int = 28
COMPARE_PRICE_LINE_PAD_X_PX: int = 4
COMPARE_PRICE_LINE_PAD_Y_PX: int = 8

# On OCR miss: green-poll briefly, then one retry (avoids full ROI when possible).
COMPARE_TOOLTIP_POLL_SECONDS: float = 0.08
COMPARE_TOOLTIP_POLL_INTERVAL_SECONDS: float = 0.015
COMPARE_TOOLTIP_READY_GREEN_PIXELS: int = 40
COMPARE_OCR_RETRY_COUNT: int = 1
COMPARE_OCR_RETRY_DELAY_SECONDS: float = 0.02

# AH tooltip OCR upscale (HUD reader keeps SCALE_FACTOR=4). Lower = faster.
# Templates are built at SCALE_FACTOR; DollarLocator rescales the $ glyph to match.
AH_SCALE_FACTOR: int = 2

# Dollar-sign template match threshold over the tooltip / strip ROI.
DOLLAR_MATCH_THRESHOLD: float = 0.55

# Green gate for AH price `$` (BGR). Durability can also be green, so the
# `$` glyph template is still required — this only drops white tooltip text.
DOLLAR_GREEN_MIN_G: int = 120
DOLLAR_GREEN_MAX_RB: int = 140
DOLLAR_GREEN_MIN_G_MINUS_RB: int = 40
# Upscaled green pixels required on a row before we search that band for `$`.
DOLLAR_GREEN_ROW_MIN_PIXELS: int = 3

# Extra pixels padded around the $-line strip before glyph OCR.
PRICE_LINE_PAD_PX: int = 4

# Max width (screen pixels) to the right of $ used for the price strip.
PRICE_STRIP_MAX_WIDTH_PX: int = 220

# Debug images written next to the project root during tests / setup.
TOOLTIP_DEBUG_IMAGE: Path = Path("ah_tooltip_debug.png")
PRICE_STRIP_DEBUG_IMAGE: Path = Path("ah_price_strip_debug.png")
