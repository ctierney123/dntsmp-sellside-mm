"""
Loop netherite armor AH searches, compare prices, buy undercuts, sell ASAP.

Casual: search each armor piece, snag the cheap one, list it right back.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ah_price.guards.balance_guard_manager import BalanceGuardManager
from ah_price.automation.buy_confirm_detector import BuyConfirmDetector
from ah_price.config import (
    ARMOR_ARB_BETWEEN_SEARCH_DELAY_SECONDS,
    ARMOR_ARB_SEARCH_QUERIES,
    ARMOR_ARB_UNDERCUT_MAX_COINS,
    ARMOR_ARB_UNDERCUT_MIN_COINS,
    FOCUS_COUNTDOWN_SECONDS,
    OWN_LISTING_SKIP_ENABLED,
    SLOT_COUNT,
)
from ah_price.armor_arb.early_slot0_buy_detector import EarlySlot0BuyDetector
from ah_price.automation.input_manager import InputManager
from ah_price.listings.own_listing_fingerprint_capture_manager import (
    OwnListingFingerprintCaptureManager,
)
from ah_price.listings.own_listing_tracker import OwnListingTracker
from ah_price.guards.parse_failure_guard_manager import ParseFailureGuardManager
from ah_price.scan.price_compare_manager import PriceCompareManager
from ah_price.automation.query_normalizer import AhSearchQueryNormalizer
from ah_price.automation.sell_order_manager import SellOrderManager
from ah_price.pricing.sell_price_calculator import SellPriceDecision
from ah_price.armor_arb.slot0_price_ceiling_skip_manager import (
    Slot0PriceCeilingSkipManager,
)
from ah_price.pricing.undercut_detector import UndercutDetector, UndercutOpportunity

logger = logging.getLogger(__name__)


class ArmorArbManager:
    """
    Multi-query AH undercut buyer + immediate reseller for netherite gear.

    Casual: search armor pieces, snag the cheap one, list it right back.
    Flow per item:
      1) First query: probe slot 0 and Esc if AH looks open. Later queries:
         always Esc (slot-0 OCR can miss while the menu is still open).
      2) /ah search the item name.
      3) First-row price compare. After slots 0–3, if slot 0 is clearly
         cheap vs 1/2/3 (in-band undercut + ≥199k gap to next-cheapest),
         skip slots 4–8 and treat that as the buy candidate immediately.
      4) If the cheapest listing is 199k–2.5m below the row median, and the
         planned /ah sell (competitive_ref - 100k) is strictly above the
         buy price, buy it. Same buy+sell coins → skip (no profit).
         Also skip when the candidate matches an own listing we recorded
         after a prior sell — price + near-1:1 tooltip fingerprint — so we
         don't click our own AH item into the collect / achievement UI.
         If that match is slot 0, abort the search (do not buy slot 1+).
         Own listings in later slots still try the next in-band snag.
         Also skip whole searches when slot 0 is above a per-item ceiling
         (e.g. netherite ingot > 10.1m) — dead book / OCR garbage guard.
      5) If the high-price confirm popup appears (Yes template match), click Yes.
      6) Immediately Esc → hotbar 1 → /ah sell at competitive_ref - 100k
         (skipping other egregious undercuts on the book). Record the sell
         in OwnListingTracker. Never buy again until that sell attempt
         finishes — hotbar slot 1 must stay clear.
    After the last query: Esc when that query was a skip so overnight
    pass-start balance OCR sees a clear HUD (buy+sell already left HUD).
    Overnight passes may pass a shuffled / partial ``queries`` override into
    ``run_pass``; single-shot ``--armor-arb`` still uses the config order.
    """

    def __init__(
        self,
        queries: tuple[str, ...] | list[str] | None = None,
        slot_count: int = SLOT_COUNT,
        countdown_seconds: float = FOCUS_COUNTDOWN_SECONDS,
        save_debug: bool = False,
        min_discount_coins: int = ARMOR_ARB_UNDERCUT_MIN_COINS,
        max_discount_coins: int = ARMOR_ARB_UNDERCUT_MAX_COINS,
        between_search_delay: float = ARMOR_ARB_BETWEEN_SEARCH_DELAY_SECONDS,
        balance_guard: BalanceGuardManager | None = None,
        parse_failure_guard: ParseFailureGuardManager | None = None,
        sell_enabled: bool = True,
        own_listing_tracker: OwnListingTracker | None = None,
        own_listing_skip_enabled: bool = OWN_LISTING_SKIP_ENABLED,
    ) -> None:
        raw_queries = tuple(queries) if queries is not None else ARMOR_ARB_SEARCH_QUERIES
        if not raw_queries:
            raise ValueError("armor arb needs at least one search query")
        self._queries = tuple(
            AhSearchQueryNormalizer.normalize(q) for q in raw_queries
        )
        self._countdown = float(countdown_seconds)
        self._between_search_delay = float(between_search_delay)
        self._sell_enabled = bool(sell_enabled)
        self._balance_guard = balance_guard
        # Overnight only: one-off OCR miss OK; repeated FAILs halt the night.
        self._parse_failure_guard = parse_failure_guard
        self._input = InputManager()
        self._compare = PriceCompareManager(
            slot_count=slot_count,
            countdown_seconds=0.0,
            save_debug=save_debug,
        )
        self._detector = UndercutDetector(
            min_discount_coins=min_discount_coins,
            max_discount_coins=max_discount_coins,
        )
        # Same band as full-row detector; peeks slots 0–3 then may skip 4–8.
        self._early_buy = EarlySlot0BuyDetector(
            min_discount_coins=min_discount_coins,
            max_discount_coins=max_discount_coins,
        )
        self._buy_confirm = BuyConfirmDetector(save_debug=save_debug)
        self._sell = SellOrderManager(input_manager=self._input)
        # Shared across overnight passes so sells from pass N protect pass N+1.
        self._own_listings = own_listing_tracker or OwnListingTracker(
            enabled=own_listing_skip_enabled,
        )
        # Same SLOT_* / TOOLTIP_REGION defaults as PriceCompareManager.
        self._own_fingerprint = OwnListingFingerprintCaptureManager()
        # Per-item "slot 0 already too expensive" early exits (ingot, etc.).
        self._slot0_ceilings = Slot0PriceCeilingSkipManager()

    def run(self) -> dict[str, Any]:
        """
        Countdown once, then search / compare / buy / sell each armor query.

        Casual: click Minecraft, then we walk the whole armor set for you.
        Returns a per-query report plus purchase count for the CLI.
        """
        self._print_start_banner()
        self._sleep_countdown(self._countdown)
        return self.run_pass(probe_escape=True)

    def run_pass(
        self,
        *,
        probe_escape: bool = True,
        queries: tuple[str, ...] | list[str] | None = None,
        check_balance: bool = True,
        label: str | None = None,
    ) -> dict[str, Any]:
        """
        One walk of the (optional override) armor query list — no countdown.

        Casual: one lap for the overnight loop; order/subset can change.
        Used by ``ArmorArbLoopCoordinator`` so the countdown only fires once
        at the start of the night, not before every pass.
        Balance is OCR'd once here on a clear HUD (not mid-AH before buys)
        unless ``check_balance`` is False (immediate post-buy rechecks).
        """
        # Overnight can shuffle / subset; single --armor-arb keeps defaults.
        active_queries = self._resolve_pass_queries(queries)

        # Scoreboard OCR only works with menus closed — never re-check mid-buy.
        if check_balance and self._balance_guard is not None:
            self._balance_guard.ensure_above_floor(context="pass start")

        if label:
            print(f"Pass plan ({label}): {len(active_queries)} item(s)")
            for query in active_queries:
                print(f"  - {query}")

        item_reports: list[dict[str, Any]] = []
        for index, query in enumerate(active_queries):
            if index > 0:
                if self._between_search_delay > 0:
                    time.sleep(self._between_search_delay)
                # Skip path leaves AH results open → must Esc before T/chat.
                # Buy+sell already Esc'd out to list the item; another Esc
                # would open the pause menu on a clear HUD.
                prev = item_reports[-1]
                if not prev.get("purchased"):
                    print("Leaving previous AH menu — Esc")
                    self._input.press_escape()
            report = self._run_one_query(
                query,
                probe_escape=(probe_escape and index == 0),
            )
            item_reports.append(report)

        # Last query skip leaves AH open. Overnight pass 2 needs a clear HUD
        # for balance OCR; a bare Esc after buy+sell would open the pause menu.
        self._escape_after_pass_if_ah_open(item_reports)

        # Keep execution order in `items` (for recheck / Esc logic), but print
        # the end-of-pass overview in stable catalog order so shuffled overnight
        # passes are still easy to scan.
        overview_items = self._items_in_catalog_order(item_reports)
        summary = {
            "queries": list(active_queries),
            "items": item_reports,
            "overview_items": overview_items,
            "purchase_count": sum(
                1 for row in item_reports if row.get("purchased")
            ),
            "sell_count": sum(
                1
                for row in item_reports
                if (row.get("sell") or {}).get("sold")
            ),
            "undercut_band": (
                self._detector.min_discount_coins,
                self._detector.max_discount_coins,
            ),
            "label": label,
        }
        self._print_final_summary(summary)
        return summary

    def _resolve_pass_queries(
        self,
        queries: tuple[str, ...] | list[str] | None,
    ) -> tuple[str, ...]:
        """
        Pick the query list for this pass (override or constructor default).

        Casual: overnight hands us a shuffled subset; otherwise use defaults.
        """
        if queries is None:
            return self._queries
        resolved = tuple(
            AhSearchQueryNormalizer.normalize(q) for q in queries if str(q).strip()
        )
        if not resolved:
            raise ValueError("run_pass needs at least one search query")
        return resolved

    def _items_in_catalog_order(
        self,
        item_reports: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """
        Reorder pass item rows to match the constructor catalog.

        Casual: print chestplate→…→ingot even when we searched boots first.
        Unknown queries (shouldn't happen) append after the catalog in the
        order they appeared. Duplicate hits for the same query keep relative
        order under that catalog slot.
        """
        by_query: dict[str, list[dict[str, Any]]] = {}
        for row in item_reports:
            query = str(row.get("query") or "")
            by_query.setdefault(query, []).append(row)

        ordered: list[dict[str, Any]] = []
        seen: set[str] = set()
        for catalog_query in self._queries:
            if catalog_query not in by_query:
                continue
            ordered.extend(by_query[catalog_query])
            seen.add(catalog_query)

        for row in item_reports:
            query = str(row.get("query") or "")
            if query in seen:
                continue
            ordered.extend(by_query[query])
            seen.add(query)
        return ordered

    def _run_one_query(
        self,
        query: str,
        *,
        probe_escape: bool = True,
    ) -> dict[str, Any]:
        """
        Search one item, compare the row, buy+sell if undercut rules match.

        Casual: one armor piece end-to-end, including the immediate relist.
        probe_escape: only the first query probes slot 0 (user may have left
        AH open). Later queries already Esc'd in run_pass() before we get here.
        """
        print()
        print(f"=== Armor arb search: {query} ===")
        logger.info("Armor arb searching %r", query)

        # First item only: maybe the player still has AH open from before.
        if probe_escape:
            self._escape_if_auction_menu_open()

        self._input.open_ah_search(query)
        compare_summary = self._compare.scan_open_ah(
            should_stop_after=self._early_buy.should_stop_after,
        )
        if compare_summary.get("early_stopped"):
            early_opp = self._early_buy.evaluate(compare_summary["listings"])
            if early_opp is not None:
                print(
                    "Early buy probe — slot 0 looks like a snag vs "
                    f"slots 1–{self._early_buy.probe_slot_count - 1} "
                    f"(-{early_opp.discount_coins:,} vs median "
                    f"{early_opp.market_price:,}); skipping remaining slots."
                )
        # Overnight: one flaky slot is fine; a second FAIL means we screwed up.
        if self._parse_failure_guard is not None:
            self._parse_failure_guard.note_compare_summary(
                compare_summary,
                context=f"search {query}",
            )

        # Cheap early exit: e.g. netherite ingot with slot 0 > 10.1m.
        ceiling_skip = self._slot0_ceilings.evaluate(
            query,
            compare_summary["listings"],
        )
        if ceiling_skip is not None:
            print(
                "Slot 0 price ceiling — "
                f"{ceiling_skip.item_key} slot 0 @ "
                f"{ceiling_skip.slot0_price:,} > "
                f"{ceiling_skip.ceiling_coins:,}; skipping this search."
            )
            return {
                "query": query,
                "compare": compare_summary,
                "opportunity": None,
                "purchased": False,
                "skip_reason": ceiling_skip.reason,
                "slot0_price_ceiling": {
                    "item_key": ceiling_skip.item_key,
                    "slot0_price": ceiling_skip.slot0_price,
                    "ceiling_coins": ceiling_skip.ceiling_coins,
                },
                "own_listing_skips": [],
                "buy_confirm": {
                    "visible": False,
                    "score": 0.0,
                    "clicked": False,
                },
                "sell": None,
            }

        opportunity, own_skip_notes = self._select_opportunity_skipping_own(
            query,
            compare_summary["listings"],
        )

        purchased = False
        skip_reason: str | None = None
        confirm_status: dict[str, Any] = {
            "visible": False,
            "score": 0.0,
            "clicked": False,
        }
        sell_status: dict[str, Any] | None = None
        if opportunity is not None:
            # Floor was already checked at pass start (clear HUD). Do not OCR
            # balance here — AH is open and CAPTURE_REGION often fails.
            self._print_opportunity(opportunity)

            # Pre-buy: if sell-after-buy would list at <= buy price, skip.
            # Classic trap: buy 7.6m (200k under median) while next real
            # listing is 7.7m → sell 7.6m → zero edge. Don't click that.
            planned_sell = None
            if self._sell_enabled:
                profitable, planned_sell = self._sell.would_profit_after_buy(
                    compare_summary["listings"],
                    purchased_slot=opportunity.slot,
                    buy_coins=opportunity.price,
                )
                if not profitable:
                    skip_reason = self._skip_reason_for_unprofitable_sell(
                        opportunity.price, planned_sell
                    )
                    self._print_unprofitable_skip(
                        opportunity.price, planned_sell, skip_reason
                    )

            if skip_reason is None:
                confirm_status = self._purchase_opportunity(opportunity)
                purchased = True
                # CRITICAL: sell before any later query can buy again. Hotbar
                # slot 1 must be empty going into the next purchase.
                if self._sell_enabled:
                    sell_status = self._sell.sell_purchased_item(
                        compare_summary["listings"],
                        purchased_slot=opportunity.slot,
                        escape_ah_first=True,
                        decision=planned_sell,
                    )
                    # Hotbar 1 still holds the item if sell failed — do not buy
                    # anything else this pass (would stack into later hotbar slots).
                    if not sell_status.get("sold"):
                        raise RuntimeError(
                            "Sell-after-buy failed "
                            f"({sell_status.get('reason')}) — stopping this pass "
                            "so hotbar slot 1 is not overwritten by another buy."
                        )
                    self._record_own_listing_after_sell(query, sell_status)
                else:
                    # Still leave AH so the next search can type into chat.
                    print("Sell disabled — Esc after purchase")
                    self._input.press_escape()
                    sell_status = {"sold": False, "reason": "sell_disabled"}
        else:
            if own_skip_notes and any(
                note.get("slot") == 0 for note in own_skip_notes
            ):
                # Slot-0 fingerprint abort already printed the reason above.
                pass
            elif own_skip_notes:
                print(
                    "No undercut in band after skipping own listing(s) "
                    f"[{self._detector.min_discount_coins:,} .. "
                    f"{self._detector.max_discount_coins:,}] coins."
                )
            else:
                print(
                    "No undercut in band "
                    f"[{self._detector.min_discount_coins:,} .. "
                    f"{self._detector.max_discount_coins:,}] coins."
                )
            if own_skip_notes and skip_reason is None:
                skip_reason = "own_listing"

        return {
            "query": query,
            "compare": compare_summary,
            "opportunity": self._opportunity_to_dict(opportunity),
            "purchased": purchased,
            "skip_reason": skip_reason,
            "own_listing_skips": own_skip_notes,
            "buy_confirm": confirm_status,
            "sell": sell_status,
        }

    def _select_opportunity_skipping_own(
        self,
        query: str,
        listings: list[dict[str, Any]],
    ) -> tuple[UndercutOpportunity | None, list[dict[str, Any]]]:
        """
        Find the best undercut that is not one of our open listings.

        Casual: skip our own listing; if it's slot 0, bail on this search.
        Re-hovers each price-matched candidate, fingerprints the tooltip, and
        asks OwnListingTracker whether it is ours. Slot 0 own-listing matches
        abort the whole query (buying slot 1+ after seeing ourselves in slot 0
        has clicked the wrong tip before). Own listings in later slots still
        exclude and try the next in-band undercut.
        """
        excluded: set[int] = set()
        skip_notes: list[dict[str, Any]] = []

        while True:
            opportunity = self._detector.find_opportunity(
                listings,
                exclude_slots=excluded,
            )
            if opportunity is None:
                return None, skip_notes

            if not self._own_listings.enabled:
                return opportunity, skip_notes

            fingerprint = self._own_fingerprint.capture_for_hover(
                opportunity.hover_xy
            )
            is_own, score, reason = self._own_listings.matches_own_listing(
                query,
                opportunity.price,
                fingerprint,
            )
            if not is_own:
                return opportunity, skip_notes

            note = {
                "slot": opportunity.slot,
                "price": opportunity.price,
                "price_raw": opportunity.price_raw,
                "match_score": score,
                "reason": reason,
            }
            skip_notes.append(note)
            excluded.add(opportunity.slot)
            score_note = (
                f" score={score:.3f}" if score is not None else ""
            )

            # Slot 0 is the hover/click "home" of the first row. If we just
            # confirmed our own tip there, do not chase slot 1+ on this pass —
            # that path has bought our listing by mistake after a fingerprint
            # skip. Safer to leave the search and move on.
            if opportunity.slot == 0:
                print(
                    "Own listing in slot 0 — "
                    f"{opportunity.price_raw} ({opportunity.price:,}) "
                    f"[{reason}{score_note}]; skipping this search "
                    "(not buying later slots)."
                )
                return None, skip_notes

            print(
                "Own listing skipped — "
                f"slot {opportunity.slot} @ {opportunity.price_raw} "
                f"({opportunity.price:,}) [{reason}{score_note}]; "
                "trying next undercut."
            )

    def _record_own_listing_after_sell(
        self,
        query: str,
        sell_status: dict[str, Any],
    ) -> None:
        """
        After a successful sell, remember query+price for later skip checks.

        Casual: jot down what we just listed so we don't click it again.
        Fingerprint is claimed on the first re-sighting (we already Esc'd out
        of AH before /ah sell, so we cannot snap the tip at list time).
        """
        if not sell_status.get("sold"):
            return
        decision = sell_status.get("decision") or {}
        sell_coins = decision.get("sell_coins")
        if sell_coins is None:
            logger.warning(
                "Sold without sell_coins in status — cannot track own listing"
            )
            return
        record = self._own_listings.record_sell(query, int(sell_coins))
        if record is not None:
            print(
                "Own listing tracked — "
                f"{query} @ {int(sell_coins):,} "
                f"(active={self._own_listings.active_count})"
            )

    def _escape_after_pass_if_ah_open(
        self,
        item_reports: list[dict[str, Any]],
    ) -> bool:
        """
        Esc after the last query when a skip left the AH results GUI open.

        Casual: close the menu when the pass ends on a no-buy, so overnight
        balance OCR / the next pass see a clear HUD.
        Same rule as inter-search Esc: only when the previous step did not
        purchase. Buy+sell (or sell-disabled Esc) already returned to the HUD;
        another Esc would open the pause menu and break scoreboard OCR.
        """
        if not item_reports:
            return False
        if item_reports[-1].get("purchased"):
            logger.debug(
                "Pass ended on a purchase — HUD should already be clear"
            )
            return False

        print("Pass complete — Esc to clear AH for HUD / next pass")
        self._input.press_escape()
        return True

    def _escape_if_auction_menu_open(self) -> bool:
        """
        Probe slot 0; Escape when a listing price is readable.

        Casual: if AH is open, hit Esc so we can start a clean search.
        A successful first-item price check is our "we're in auction UI" signal.
        """
        probe = self._compare.try_read_first_listing()
        if probe is None:
            logger.debug("Auction menu probe: closed / no listing tooltip")
            return False

        print(
            "Auction menu detected "
            f"(slot 0 {probe.get('price_raw')} / {probe.get('price')}) — Esc"
        )
        self._input.press_escape()
        return True

    def _purchase_opportunity(self, opportunity: UndercutOpportunity) -> dict[str, Any]:
        """
        Re-hover the undercut slot, left-click buy, then auto-Yes if needed.

        Casual: click the cheap listing; if are-you-sure pops up, hit Yes.
        Compare already left the cursor on the last scanned slot, so we
        explicitly re-park on the opportunity before the purchase click.
        """
        print(
            f"Purchasing slot {opportunity.slot} at {opportunity.hover_xy} "
            f"({opportunity.price_raw} / {opportunity.price})"
        )
        self._input.left_click_at(opportunity.hover_xy)
        return self._confirm_buy_if_prompted()

    def _confirm_buy_if_prompted(self) -> dict[str, Any]:
        """
        After a listing click, poll for the Yes confirm dialog and click it.

        Casual: expensive items sometimes ask again — answer Yes for them.
        No-ops (with a log) when --setup-buy-confirm hasn't been pasted yet.
        """
        if not self._buy_confirm.is_calibrated:
            print(
                "Buy-confirm detector not calibrated — skipping Yes poll. "
                "Run: python -m ah_price --setup-buy-confirm"
            )
            return {"visible": False, "score": 0.0, "clicked": False}

        detection = self._buy_confirm.wait_for_confirm()
        if detection is None:
            logger.debug("No buy-confirm popup after purchase click")
            return BuyConfirmDetector.to_status_dict(None, clicked=False)

        print(
            f"Buy-confirm detected (score={detection.score:.3f}) — clicking Yes "
            f"at {detection.yes_xy}"
        )
        self._input.click_buy_confirm_yes(detection.yes_xy)
        return BuyConfirmDetector.to_status_dict(detection, clicked=True)

    def _print_start_banner(self) -> None:
        band_lo = self._detector.min_discount_coins
        band_hi = self._detector.max_discount_coins
        print(
            "Click into Minecraft now — armor arb starts in "
            f"{self._countdown:.0f}s"
        )
        print(f"  queries: {len(self._queries)}")
        for query in self._queries:
            print(f"    - {query}")
        print(f"  undercut band: {band_lo:,} .. {band_hi:,} coins")
        print(
            "  early buy probe: slots 0–"
            f"{self._early_buy.probe_slot_count - 1} "
            "(skip rest when slot 0 is clearly under)"
        )
        print(
            "  sell-after-buy: "
            + ("ON (hotbar 1 → /ah sell ref-100k)" if self._sell_enabled else "OFF")
        )
        if self._own_listings.enabled:
            print(
                "  own-listing skip: ON "
                f"(active={self._own_listings.active_count}, "
                "price + tooltip fingerprint)"
            )
        else:
            print("  own-listing skip: OFF")
        ceilings = self._slot0_ceilings.ceilings
        if ceilings:
            print("  slot-0 price ceilings (skip search if slot 0 > cap):")
            for item_key, coins in sorted(ceilings.items()):
                print(f"    - {item_key}: {coins:,}")
        if self._balance_guard is not None:
            print(
                f"  balance floor: {self._balance_guard.min_balance_coins:,}"
            )
        if self._buy_confirm.is_calibrated:
            print(
                f"  buy-confirm Yes: calibrated @ {self._buy_confirm.yes_xy}"
            )
        else:
            print(
                "  buy-confirm Yes: NOT calibrated "
                "(python -m ah_price --setup-buy-confirm)"
            )

    @staticmethod
    def _print_opportunity(opportunity: UndercutOpportunity) -> None:
        print(
            "Undercut hit: "
            f"slot {opportunity.slot} @ {opportunity.price_raw} "
            f"({opportunity.price}) is "
            f"{opportunity.discount_coins:,} below market "
            f"({opportunity.market_price})"
        )

    @staticmethod
    def _skip_reason_for_unprofitable_sell(
        buy_coins: int,
        planned_sell: SellPriceDecision | None,
    ) -> str:
        """
        Label why we refused a median-band undercut before clicking.

        Casual: same price or can't price the sell → don't buy.
        """
        if planned_sell is None:
            return "no_sell_price"
        if int(planned_sell.sell_coins) == int(buy_coins):
            return "buy_equals_sell"
        return "sell_not_above_buy"

    @staticmethod
    def _print_unprofitable_skip(
        buy_coins: int,
        planned_sell: SellPriceDecision | None,
        skip_reason: str,
    ) -> None:
        """
        Tell the operator we saw a snag but refused the zero-edge flip.

        Casual: print why we're walking away from this undercut.
        """
        if planned_sell is None:
            print(
                "Undercut skipped — cannot compute a sell price above the "
                f"buy ({buy_coins:,}); leaving it on the book."
            )
            return
        sell_coins = int(planned_sell.sell_coins)
        print(
            "Undercut skipped — no profit: "
            f"buy {buy_coins:,} → planned sell {sell_coins:,} "
            f"({skip_reason}); not buying."
        )

    @staticmethod
    def _print_final_summary(summary: dict[str, Any]) -> None:
        print()
        print("=== Armor arb complete ===")
        print(
            f"purchases: {summary['purchase_count']}/{len(summary['items'])}  "
            f"sells: {summary.get('sell_count', 0)}"
        )
        # Prefer catalog-stable overview when present (overnight shuffle).
        overview_rows = summary.get("overview_items") or summary["items"]
        for row in overview_rows:
            opp = row.get("opportunity")
            if row.get("purchased") and opp:
                confirm = row.get("buy_confirm") or {}
                confirm_note = (
                    " +Yes" if confirm.get("clicked") else ""
                )
                sell = row.get("sell") or {}
                if sell.get("sold"):
                    sell_note = f" → sell {sell.get('price_text')}"
                else:
                    sell_note = f" → sell FAILED ({sell.get('reason')})"
                print(
                    f"  BUY  {row['query']}: slot {opp['slot']} "
                    f"{opp['price_raw']} (-{opp['discount_coins']:,})"
                    f"{confirm_note}{sell_note}"
                )
            elif opp and row.get("skip_reason"):
                print(
                    f"  skip {row['query']}: slot {opp['slot']} "
                    f"{opp['price_raw']} (-{opp['discount_coins']:,}) "
                    f"[{row['skip_reason']}]"
                )
            elif row.get("skip_reason") == "own_listing":
                own_skips = row.get("own_listing_skips") or []
                slots = ", ".join(
                    str(note.get("slot")) for note in own_skips
                ) or "?"
                print(f"  skip {row['query']}: own listing (slots {slots})")
            elif row.get("skip_reason") == "slot0_price_ceiling":
                ceiling = row.get("slot0_price_ceiling") or {}
                print(
                    f"  skip {row['query']}: slot 0 "
                    f"{ceiling.get('slot0_price', '?')} > "
                    f"ceiling {ceiling.get('ceiling_coins', '?')}"
                )
            else:
                print(f"  skip {row['query']}")
        print()

    @staticmethod
    def _opportunity_to_dict(
        opportunity: UndercutOpportunity | None,
    ) -> dict[str, Any] | None:
        if opportunity is None:
            return None
        return {
            "slot": opportunity.slot,
            "hover_xy": opportunity.hover_xy,
            "price": opportunity.price,
            "price_raw": opportunity.price_raw,
            "market_price": opportunity.market_price,
            "discount_coins": opportunity.discount_coins,
        }

    @staticmethod
    def _sleep_countdown(seconds: float) -> None:
        remaining = int(seconds)
        while remaining > 0:
            print(f"  {remaining}...", flush=True)
            time.sleep(1.0)
            remaining -= 1
        frac = seconds - int(seconds)
        if frac > 0:
            time.sleep(frac)

    def close(self) -> None:
        """Release OCR / capture resources held by compare + confirm detectors."""
        self._compare.close()
        self._buy_confirm.close()
        self._own_fingerprint.close()
