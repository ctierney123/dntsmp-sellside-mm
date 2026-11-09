"""
Hover the first N AH listings, OCR each price, check if slot 0 is cheapest.

Casual: skim the top row fast and say whether the left item wins on price.
Designed for a tight loop (instant mouse moves + adaptive tooltip settle).
Slot 0 uses the full tooltip ROI; later slots use a two-stage capture:
  1) tall narrow $ column (X locked; Y free for enchants)
  2) tiny price-line crop for digit OCR
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

import pyautogui

from ah_price.config import (
    COMPARE_AFTER_HOVER_DELAY_SECONDS,
    COMPARE_FIRST_HOVER_DELAY_SECONDS,
    COMPARE_MOUSE_MOVE_DURATION_SECONDS,
    COMPARE_OCR_RETRY_COUNT,
    COMPARE_OCR_RETRY_DELAY_SECONDS,
    COMPARE_PYAUTOGUI_PAUSE_SECONDS,
    COMPARE_TOOLTIP_POLL_INTERVAL_SECONDS,
    COMPARE_TOOLTIP_POLL_SECONDS,
    COMPARE_TOOLTIP_READY_GREEN_PIXELS,
    FOCUS_COUNTDOWN_SECONDS,
    SLOT_COUNT,
)
from ah_price.automation.input_manager import InputManager
from ah_price.tooltip.price_band_tracker import PriceBandTracker
from ah_price.automation.query_normalizer import AhSearchQueryNormalizer
from ah_price.scan.slot_grid_manager import SlotGridManager
from ah_price.tooltip.tooltip_price_reader import TooltipPriceReader

logger = logging.getLogger(__name__)


class PriceCompareManager:
    """
    Multi-slot AH price scan + "is leftmost cheapest?" verdict.

    Casual: hover slots 0..N-1, read $, compare, print a summary.
    Reuses TooltipPriceReader but retargets the capture ROI per hover so
    tooltips that follow the cursor still land inside the OCR box.
    """

    def __init__(
        self,
        slot_count: int = SLOT_COUNT,
        countdown_seconds: float = FOCUS_COUNTDOWN_SECONDS,
        after_hover_delay: float = COMPARE_AFTER_HOVER_DELAY_SECONDS,
        first_hover_delay: float = COMPARE_FIRST_HOVER_DELAY_SECONDS,
        mouse_move_duration: float = COMPARE_MOUSE_MOVE_DURATION_SECONDS,
        save_debug: bool = False,
        query: str | None = None,
    ) -> None:
        self._grid = SlotGridManager(slot_count=slot_count)
        self._countdown = countdown_seconds
        self._after_hover_delay = after_hover_delay
        self._first_hover_delay = first_hover_delay
        self._mouse_move_duration = mouse_move_duration
        self._query = AhSearchQueryNormalizer.normalize(query) if query else None
        self._input = InputManager()
        # Debug PNGs every slot would thrash disk — off by default for speed.
        self._reader = TooltipPriceReader(save_debug=save_debug)
        self._band = PriceBandTracker(scale_factor=self._reader.scale_factor)

    def run_compare_only(self) -> dict[str, Any]:
        """
        Assume AH is already open; scan slots and return the compare result.

        Casual: you opened the book, we just race across the first row.
        """
        self._countdown_message("compare-only (AH already open)")
        self._sleep_countdown(self._countdown)
        return self.scan_open_ah()

    def run_full(self, query: str | None = None) -> dict[str, Any]:
        """
        Full path: focus → /ah search → scan first-row prices → verdict.

        Casual: type the search, then price-check the top row in one go.
        """
        command = AhSearchQueryNormalizer.normalize(query or self._query)
        self._countdown_message(f"full search query={command!r}")
        self._sleep_countdown(self._countdown)
        self._input.open_ah_search(command)
        return self.scan_open_ah()

    def scan_open_ah(
        self,
        *,
        should_stop_after: Callable[[list[dict[str, Any]]], bool] | None = None,
    ) -> dict[str, Any]:
        """
        Scan the open AH first row with no countdown / no new search.

        Casual: AH is already up — just price the top row and summarize.
        Used by armor-arb between searches so we don't re-countdown each item.
        ``should_stop_after`` is checked after each slot OCR; when it returns
        True we bail early (e.g. obvious slot-0 snag after slots 0–3).
        """
        return self._scan_and_summarize(should_stop_after=should_stop_after)

    def try_read_first_listing(self) -> dict[str, Any] | None:
        """
        Probe slot 0 only — used to detect an open auction menu.

        Casual: peek the leftmost listing; if OCR works, AH is probably open.
        Returns the price dict on success, or None when the tooltip / $ is
        missing (chat, world, empty GUI, etc.).
        """
        previous_pause = pyautogui.PAUSE
        pyautogui.PAUSE = COMPARE_PYAUTOGUI_PAUSE_SECONDS
        try:
            hover_xy = self._grid.hover_xy_for_slot(0)
            self._fast_hover(hover_xy, settle_seconds=self._first_hover_delay)
            result = self._read_slot_price(hover_xy)
            return {
                "slot": 0,
                "hover_xy": hover_xy,
                "price_raw": result["price_raw"],
                "price": result["price"],
                "capture_mode": result.get("capture_mode"),
            }
        except Exception as exc:
            logger.debug("First-listing probe failed (AH likely closed): %s", exc)
            return None
        finally:
            pyautogui.PAUSE = previous_pause

    def _scan_and_summarize(
        self,
        *,
        should_stop_after: Callable[[list[dict[str, Any]]], bool] | None = None,
    ) -> dict[str, Any]:
        """
        Hover each slot, OCR prices, decide if slot 0 is the lowest.

        Casual: the actual compare loop + printed report.
        Restores pyautogui.PAUSE afterward so other callers stay normal.
        """
        self._band.clear()
        previous_pause = pyautogui.PAUSE
        pyautogui.PAUSE = COMPARE_PYAUTOGUI_PAUSE_SECONDS
        t0 = time.perf_counter()
        try:
            listings, early_stopped = self._read_all_slot_prices(
                should_stop_after=should_stop_after,
            )
        finally:
            pyautogui.PAUSE = previous_pause

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        summary = self._build_summary(
            listings,
            elapsed_ms,
            early_stopped=early_stopped,
            planned_slot_count=self._grid.slot_count,
        )
        self._print_summary(summary)
        return summary

    def _read_all_slot_prices(
        self,
        *,
        should_stop_after: Callable[[list[dict[str, Any]]], bool] | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """
        Walk the grid left → right and OCR each tooltip.

        Casual: move, capture ASAP, retry if tooltip isn't painted yet.
        Slot 0 does a full tooltip search and locks the $ column X offset;
        later slots use two-stage column + price-line capture.
        Optional ``should_stop_after`` can cut the walk short (early buy).
        """
        listings: list[dict[str, Any]] = []
        early_stopped = False
        for index, hover_xy in enumerate(self._grid.all_hover_points()):
            slot_t0 = time.perf_counter()
            try:
                # Tiny fixed settle only for slot 0 (first tooltip spawn).
                # Later slots rely on adaptive retries instead of sleeping.
                settle = (
                    self._first_hover_delay if index == 0 else self._after_hover_delay
                )
                self._fast_hover(hover_xy, settle_seconds=settle)
                result = self._read_slot_price(hover_xy)
                listings.append(
                    {
                        "slot": index,
                        "hover_xy": hover_xy,
                        "price_raw": result["price_raw"],
                        "price": result["price"],
                        "ok": True,
                        "error": None,
                        "elapsed_ms": round((time.perf_counter() - slot_t0) * 1000.0, 1),
                        "capture_mode": result.get("capture_mode"),
                    }
                )
            except Exception as exc:
                logger.warning("Slot %d failed at %s: %s", index, hover_xy, exc)
                listings.append(
                    {
                        "slot": index,
                        "hover_xy": hover_xy,
                        "price_raw": None,
                        "price": None,
                        "ok": False,
                        "error": str(exc),
                        "elapsed_ms": round((time.perf_counter() - slot_t0) * 1000.0, 1),
                        "capture_mode": None,
                    }
                )

            # Armor-arb early buy: stop once slot 0 is clearly a snag vs 1–3.
            if should_stop_after is not None and should_stop_after(listings):
                early_stopped = True
                logger.info(
                    "Price compare early-stop after %d slot(s)",
                    len(listings),
                )
                break
        return listings, early_stopped

    def _read_slot_price(self, hover_xy: tuple[int, int]) -> dict[str, Any]:
        """
        OCR one slot via strip when locked, else full tooltip ROI.

        Casual: try OCR immediately after settle; only green-poll on a miss.
        """
        full_region = self._grid.tooltip_region_for_hover(hover_xy)
        column_region = self._band.dollar_column_region_for_hover(
            hover_xy,
            tooltip_region=full_region,
        )

        if column_region is not None:
            result = self._ocr_with_retry(
                lambda: self._reader.read_price_two_stage(column_region),
                hover_xy=hover_xy,
                mode="strip",
                lock_region=column_region,
                probe_region=column_region,
            )
            if result is not None:
                return result

        result = self._ocr_with_retry(
            lambda: self._reader.read_price(region=full_region),
            hover_xy=hover_xy,
            mode="full",
            lock_region=full_region,
            probe_region=full_region,
        )
        if result is not None:
            return result
        raise RuntimeError(
            "Could not find a non-HUD $ in TOOLTIP_REGION after retries. "
            "Widen the region, re-hover the item, or check dollar.png."
        )

    def _wait_for_green_tooltip(self, region: dict[str, int]) -> None:
        """
        Cheap poll until green tip pixels appear (or budget expires).

        Casual: tip not painted? peek for green before burning another OCR.
        """
        deadline = time.perf_counter() + COMPARE_TOOLTIP_POLL_SECONDS
        while True:
            green = self._reader.count_green_pixels(region)
            if green >= COMPARE_TOOLTIP_READY_GREEN_PIXELS:
                return
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                logger.debug(
                    "Green-ready poll timed out (last_green=%d, need=%d)",
                    green,
                    COMPARE_TOOLTIP_READY_GREEN_PIXELS,
                )
                return
            time.sleep(min(COMPARE_TOOLTIP_POLL_INTERVAL_SECONDS, remaining))

    def _ocr_with_retry(
        self,
        read_fn,
        hover_xy: tuple[int, int],
        mode: str,
        lock_region: dict[str, int],
        probe_region: dict[str, int],
    ) -> dict[str, Any] | None:
        """
        Run OCR; on miss, green-poll then retry once.

        Casual: tip flickered? wait for green, try one more shot, then bail.
        """
        attempts = max(1, COMPARE_OCR_RETRY_COUNT + 1)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                result = read_fn()
                dollar = result.get("dollar")
                if dollar is not None:
                    self._band.lock_from_match(dollar, lock_region, hover_xy)
                result["capture_mode"] = mode
                return result
            except Exception as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    break
                logger.debug(
                    "%s OCR miss at %s attempt %d/%d (%s) — waiting for green",
                    mode,
                    hover_xy,
                    attempt + 1,
                    attempts,
                    exc,
                )
                self._wait_for_green_tooltip(probe_region)
                time.sleep(COMPARE_OCR_RETRY_DELAY_SECONDS)

        logger.debug("%s OCR failed at %s (%s)", mode, hover_xy, last_error)
        return None

    def _fast_hover(
        self,
        xy: tuple[int, int],
        settle_seconds: float | None = None,
    ) -> None:
        """
        Instant (or near-instant) mouse park + optional tiny settle.

        Casual: teleport onto the icon; green-poll handles the rest.
        """
        settle = self._after_hover_delay if settle_seconds is None else settle_seconds
        logger.debug(
            "Fast-hover %s (move=%.3fs settle=%.3fs)",
            xy,
            self._mouse_move_duration,
            settle,
        )
        pyautogui.moveTo(xy[0], xy[1], duration=self._mouse_move_duration)
        if settle > 0:
            time.sleep(settle)

    @staticmethod
    def _build_summary(
        listings: list[dict[str, Any]],
        elapsed_ms: float,
        *,
        early_stopped: bool = False,
        planned_slot_count: int | None = None,
    ) -> dict[str, Any]:
        """
        Compute cheapest slot + whether the leftmost listing wins.

        Casual: turn the price list into a yes/no for "is #1 cheapest?"
        """
        priced = [row for row in listings if row.get("ok") and row.get("price") is not None]
        first = next((row for row in listings if row.get("slot") == 0), None)
        first_price = first.get("price") if first and first.get("ok") else None

        cheapest_price: int | None = None
        cheapest_slots: list[int] = []
        if priced:
            cheapest_price = min(int(row["price"]) for row in priced)
            cheapest_slots = [
                int(row["slot"]) for row in priced if int(row["price"]) == cheapest_price
            ]

        first_is_lowest = (
            first_price is not None
            and cheapest_price is not None
            and int(first_price) == int(cheapest_price)
        )

        planned = (
            int(planned_slot_count)
            if planned_slot_count is not None
            else len(listings)
        )
        return {
            "listings": listings,
            "first_price": first_price,
            "cheapest_price": cheapest_price,
            "cheapest_slots": cheapest_slots,
            "first_is_lowest": first_is_lowest,
            "ok_count": len(priced),
            "slot_count": len(listings),
            "planned_slot_count": planned,
            "early_stopped": bool(early_stopped),
            "elapsed_ms": round(elapsed_ms, 1),
        }

    @staticmethod
    def _print_summary(summary: dict[str, Any]) -> None:
        """Pretty-print the compare result for the terminal."""
        print()
        print("=== AH first-row price compare ===")
        for row in summary["listings"]:
            if row["ok"]:
                mode = row.get("capture_mode") or "?"
                print(
                    f"  slot {row['slot']}: {row['price_raw']} "
                    f"({row['price']})  [{row['elapsed_ms']} ms, {mode}]"
                )
            else:
                print(
                    f"  slot {row['slot']}: FAIL — {row['error']} "
                    f"[{row['elapsed_ms']} ms]"
                )
        print()
        print(f"first_price:     {summary['first_price']}")
        print(f"cheapest_price:  {summary['cheapest_price']}")
        print(f"cheapest_slots:  {summary['cheapest_slots']}")
        print(f"first_is_lowest: {summary['first_is_lowest']}")
        if summary.get("early_stopped"):
            print(
                "early_stop:      True "
                f"(scanned {summary['slot_count']}/"
                f"{summary.get('planned_slot_count', summary['slot_count'])})"
            )
        print(
            f"timing:          {summary['elapsed_ms']} ms "
            f"({summary['ok_count']}/{summary['slot_count']} ok)"
        )
        print()

    def _countdown_message(self, mode: str) -> None:
        print(
            f"Click into Minecraft now — {mode} starts in "
            f"{self._countdown:.0f}s "
            f"(slots={self._grid.slot_count}, origin={self._grid.origin_xy}, "
            f"spacing={self._grid.spacing_xy})"
        )

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
        """Release OCR / capture resources."""
        self._reader.close()
