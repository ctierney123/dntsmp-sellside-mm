"""
Live spread check: open sell + buy books, OCR slot 0, print ask/bid/spread.

Casual: peek /ah and /order for one item and tell you the gap.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import pyautogui

from ah_price.automation.input_manager import InputManager
from ah_price.config import (
    COMPARE_PYAUTOGUI_PAUSE_SECONDS,
    FOCUS_COUNTDOWN_SECONDS,
    MARKET_MAKING_AFTER_ENTER_DELAY_SECONDS,
    MARKET_MAKING_AFTER_ESCAPE_DELAY_SECONDS,
    MARKET_MAKING_DEFAULT_ITEM,
    MARKET_MAKING_MOUSE_MOVE_DURATION_SECONDS,
    MARKET_MAKING_PARK_OFFSET_XY,
    MARKET_MAKING_SLOT0_HOVER_DELAY_SECONDS,
)
from ah_price.market_making.command_builder import MarketMakingCommandBuilder
from ah_price.market_making.spread_calculator import SpreadCalculator, SpreadSnapshot
from ah_price.pricing.ah_price_formatter import AhPriceFormatter
from ah_price.scan.price_compare_manager import PriceCompareManager
from ah_price.scan.slot_grid_manager import SlotGridManager
from ah_price.tooltip.tooltip_price_reader import TooltipPriceReader

logger = logging.getLogger(__name__)


class SpreadCheckManager:
    """
    Orchestrates a single-item bid/ask spread probe.

    Casual: paste /ah, read slot 0 ask; Esc; paste /order, read slot 0 bid.
    Reuses calibrated slot-0 coords + tooltip OCR from the AH scan stack.
    Chat uses clipboard paste (instant). Flow per book:
      1) park mouse OFF the listing grid
      2) paste command + Enter
      3) wait ~0.1s for the menu to paint
      4) snap onto slot 0 (so Minecraft fires a real hover)
      5) OCR the tooltip
    """

    def __init__(
        self,
        *,
        countdown_seconds: float = FOCUS_COUNTDOWN_SECONDS,
        after_enter_delay: float = MARKET_MAKING_AFTER_ENTER_DELAY_SECONDS,
        slot0_hover_delay: float = MARKET_MAKING_SLOT0_HOVER_DELAY_SECONDS,
        after_escape_delay: float = MARKET_MAKING_AFTER_ESCAPE_DELAY_SECONDS,
        mouse_move_duration: float = MARKET_MAKING_MOUSE_MOVE_DURATION_SECONDS,
        park_offset_xy: tuple[int, int] = MARKET_MAKING_PARK_OFFSET_XY,
        save_debug: bool = False,
        input_manager: InputManager | None = None,
        command_builder: MarketMakingCommandBuilder | None = None,
        spread_calculator: SpreadCalculator | None = None,
        price_formatter: AhPriceFormatter | None = None,
        slot_grid: SlotGridManager | None = None,
        price_reader: TooltipPriceReader | None = None,
        compare_manager: PriceCompareManager | None = None,
    ) -> None:
        self._countdown = float(countdown_seconds)
        self._after_enter_delay = float(after_enter_delay)
        self._slot0_hover_delay = float(slot0_hover_delay)
        self._after_escape_delay = float(after_escape_delay)
        self._mouse_move_duration = float(mouse_move_duration)
        self._park_offset_xy = (int(park_offset_xy[0]), int(park_offset_xy[1]))
        self._input = input_manager or InputManager()
        self._commands = command_builder or MarketMakingCommandBuilder()
        self._spreads = spread_calculator or SpreadCalculator()
        self._fmt = price_formatter or AhPriceFormatter()
        self._grid = slot_grid or SlotGridManager(slot_count=1)
        self._reader = price_reader or TooltipPriceReader(save_debug=save_debug)
        # Compare manager is only used to detect a leftover open AH menu.
        self._compare = compare_manager or PriceCompareManager(
            slot_count=1,
            countdown_seconds=0.0,
            save_debug=save_debug,
        )
        self._owns_compare = compare_manager is None
        self._owns_reader = price_reader is None

    def run(self, item_name: str | None = None) -> dict[str, Any]:
        """
        Focus countdown → sell book → buy book → print spread summary.

        Casual: the full one-shot spread check for whatever item you pass.
        Defaults to enchanted golden apple. Returns a dict with ask/bid/spread
        plus the raw OCR strings for debugging.
        """
        item = (item_name or MARKET_MAKING_DEFAULT_ITEM).strip()
        if not item:
            raise ValueError("item_name must be non-empty")

        sell_cmd = self._commands.sell_book_command(item)
        buy_cmd = self._commands.buy_book_command(item)

        print(
            f"Spread check for {item!r}\n"
            f"  sell book: {sell_cmd}\n"
            f"  buy book:  {buy_cmd}"
        )
        self._countdown_message()
        self._sleep_countdown(self._countdown)

        # If a previous AH/order GUI is still open, Esc so T opens chat cleanly.
        self._escape_if_auction_menu_open()

        ask_side = self._open_book_and_read_slot0(
            command=sell_cmd,
            side_label="ask (cheapest sell)",
        )
        self._input.press_escape(settle_seconds=self._after_escape_delay)

        bid_side = self._open_book_and_read_slot0(
            command=buy_cmd,
            side_label="bid (highest buy)",
        )
        # Leave HUD clear for the next tool / manual play.
        self._input.press_escape(settle_seconds=self._after_escape_delay)

        snapshot = self._spreads.calculate(
            item_name=item,
            ask_coins=int(ask_side["price"]),
            bid_coins=int(bid_side["price"]),
            ask_raw=ask_side.get("price_raw"),
            bid_raw=bid_side.get("price_raw"),
        )
        self._print_snapshot(snapshot)

        return {
            "item_name": snapshot.item_name,
            "ask_coins": snapshot.ask_coins,
            "bid_coins": snapshot.bid_coins,
            "spread_coins": snapshot.spread_coins,
            "is_crossed": snapshot.is_crossed,
            "ask_raw": snapshot.ask_raw,
            "bid_raw": snapshot.bid_raw,
            "ask_elapsed_ms": ask_side.get("elapsed_ms"),
            "bid_elapsed_ms": bid_side.get("elapsed_ms"),
            "sell_command": sell_cmd,
            "buy_command": buy_cmd,
        }

    def close(self) -> None:
        """
        Release owned OCR / compare resources.

        Casual: shut down screenshot handles when we're done.
        """
        if self._owns_compare:
            close_fn = getattr(self._compare, "close", None)
            if callable(close_fn):
                close_fn()
        if self._owns_reader:
            close_fn = getattr(self._reader, "close", None)
            if callable(close_fn):
                close_fn()

    def _open_book_and_read_slot0(
        self,
        *,
        command: str,
        side_label: str,
    ) -> dict[str, Any]:
        """
        Park off-grid, paste a book command, then snap onto slot 0 + OCR.

        Casual: open one side of the book and grab the top-left listing $.
        Parking first is required — if the cursor is already on slot 0 when
        the GUI appears, Minecraft never fires a hover tooltip.
        """
        print(f"Opening {side_label}: {command}")
        # Get off slot 0 BEFORE the menu opens (probe / prior hover may be there).
        self._park_mouse_off_listings()
        self._input.open_chat_command_paste(
            command,
            after_enter_delay=self._after_enter_delay,
        )
        return self._read_slot0_price(side_label=side_label)

    def _park_mouse_off_listings(self) -> None:
        """
        Move the cursor away from the AH first-row slots.

        Casual: stand next to the shelf so we can walk onto slot 0 after.
        """
        slot0 = self._grid.hover_xy_for_slot(0)
        park_xy = (
            slot0[0] + self._park_offset_xy[0],
            slot0[1] + self._park_offset_xy[1],
        )
        logger.info("Parking mouse off listings at %s (slot0=%s)", park_xy, slot0)
        print(f"  parking mouse at {park_xy} (off slot 0)")
        self._input.hover_item_instant(
            park_xy,
            settle_seconds=0.0,
            move_duration=self._mouse_move_duration,
        )

    def _read_slot0_price(self, *, side_label: str) -> dict[str, Any]:
        """
        Snap from the park point onto slot 0 and OCR the tooltip price.

        Casual: teleport onto top-left and read the green $ line.
        Uses the same ROI shift math as the multi-slot compare scanner.
        """
        previous_pause = pyautogui.PAUSE
        pyautogui.PAUSE = COMPARE_PYAUTOGUI_PAUSE_SECONDS
        t0 = time.perf_counter()
        try:
            hover_xy = self._grid.hover_xy_for_slot(0)
            print(f"  snapping to slot 0 at {hover_xy}")
            self._input.hover_item_instant(
                hover_xy,
                settle_seconds=self._slot0_hover_delay,
                move_duration=self._mouse_move_duration,
            )
            region = self._grid.tooltip_region_for_hover(hover_xy)
            result = self._reader.read_price(region=region)
            price = result.get("price")
            if price is None or int(price) <= 0:
                raise RuntimeError(
                    f"Could not parse a positive {side_label} price "
                    f"(raw={result.get('price_raw')!r})"
                )
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            row = {
                "slot": 0,
                "hover_xy": hover_xy,
                "price": int(price),
                "price_raw": result.get("price_raw"),
                "elapsed_ms": elapsed_ms,
                "side_label": side_label,
            }
            print(
                f"  {side_label}: {result.get('price_raw')} "
                f"({int(price)})  [{elapsed_ms} ms]"
            )
            return row
        finally:
            pyautogui.PAUSE = previous_pause

    def _escape_if_auction_menu_open(self) -> bool:
        """
        Probe slot 0; Escape when a listing price is readable.

        Casual: if AH/order is already open, Esc before we paste a new search.
        After Esc we park off the grid so the next open gets a real hover.
        """
        probe = self._compare.try_read_first_listing()
        if probe is None:
            logger.debug("Auction menu probe: closed / no listing tooltip")
            # Probe still may have parked us on slot 0 — get off it.
            self._park_mouse_off_listings()
            return False

        print(
            "Auction menu detected "
            f"(slot 0 {probe.get('price_raw')} / {probe.get('price')}) — Esc"
        )
        self._input.press_escape(settle_seconds=self._after_escape_delay)
        self._park_mouse_off_listings()
        return True

    def _print_snapshot(self, snapshot: SpreadSnapshot) -> None:
        """
        Pretty-print ask / bid / spread for the terminal.

        Casual: the final scoreboard after both books are read.
        """
        ask_txt = self._fmt.format_coins(snapshot.ask_coins)
        bid_txt = self._fmt.format_coins(snapshot.bid_coins)
        spread_txt = self._fmt.format_coins(abs(snapshot.spread_coins))
        sign = "-" if snapshot.spread_coins < 0 else ""
        crossed = "  [CROSSED]" if snapshot.is_crossed else ""
        print(
            "\n=== Market spread ===\n"
            f"  item:   {snapshot.item_name}\n"
            f"  ask:    {snapshot.ask_raw} ({ask_txt} / {snapshot.ask_coins})\n"
            f"  bid:    {snapshot.bid_raw} ({bid_txt} / {snapshot.bid_coins})\n"
            f"  spread: {sign}{spread_txt} ({snapshot.spread_coins} coins)"
            f"{crossed}"
        )

    def _countdown_message(self) -> None:
        """Tell the user to click into Minecraft before input starts."""
        print(
            f"Click into Minecraft — starting in {self._countdown:.1f}s "
            "(Ctrl+C to abort)…"
        )

    @staticmethod
    def _sleep_countdown(seconds: float) -> None:
        """
        Sleep the focus countdown in small chunks so Ctrl+C stays responsive.

        Casual: the 3-2-1 before we start pasting commands.
        """
        remaining = float(seconds)
        while remaining > 0:
            chunk = min(0.25, remaining)
            time.sleep(chunk)
            remaining -= chunk
