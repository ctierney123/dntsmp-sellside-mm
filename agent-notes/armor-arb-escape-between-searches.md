# Armor arb — "herite boots" chat drop between searches

**Date:** 2026-07-09  
**Symptom:** After a good helm compare (slot 0 FAIL, slots 1–8 OK), the next search typed `/ah netherite boots` in logs but Minecraft chat showed **`herite boots`**. All 9 boots slots then failed OCR (wrong / empty AH state).

**Root cause:** `_escape_if_auction_menu_open()` only Esc'd when **slot 0** OCR succeeded. Helm left AH open with a broken/empty leftmost listing, so the boots probe returned `None`, skipped Esc, pressed **T** while the GUI was still up, and the leading `/ah net` keystrokes were eaten by the menu.

**Fix:**
1. Between queries (`index > 0`): **always** Esc + settle — do not gate on slot-0 OCR.
2. Slot-0 probe Esc only on the **first** query (player may have left AH open).
3. Bumped `AFTER_ESCAPE_DELAY_SECONDS` 0.35 → **0.55** and `ARMOR_ARB_BETWEEN_SEARCH_DELAY_SECONDS` 0.20 → **0.35**.

**Log fingerprint:** boots search has no `Auction menu detected … — Esc` / no `Pressing Escape` line before `Pressing chat key (T)`.
