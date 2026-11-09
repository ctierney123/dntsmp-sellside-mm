"""
Keyboard / mouse injection for Minecraft chat + Auction House clicks.

Casual: presses T, types (or pastes) the AH command, and parks the mouse on an item.
Uses pyautogui. Minecraft must already be focused before you call these —
the orchestrator countdown is what buys you that focus window.
"""

from __future__ import annotations

import logging
import time

import pyautogui
import pyperclip

from ah_price.config import (
    AFTER_BUY_CONFIRM_CLICK_DELAY_SECONDS,
    AFTER_ENTER_DELAY_SECONDS,
    AFTER_ESCAPE_DELAY_SECONDS,
    AFTER_HOTBAR_SELECT_DELAY_SECONDS,
    AFTER_HOVER_DELAY_SECONDS,
    AFTER_PURCHASE_CLICK_DELAY_SECONDS,
    AFTER_SELL_COMMAND_DELAY_SECONDS,
    BUY_CONFIRM_YES_XY,
    CHAT_OPEN_DELAY_SECONDS,
    ITEM_HOVER_XY,
    TYPE_INTERVAL_SECONDS,
)
from ah_price.automation.query_normalizer import AhSearchQueryNormalizer

logger = logging.getLogger(__name__)

# Fail-safe: yank mouse to a screen corner to abort runaway automation.
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.02


class InputManager:
    """
    Sends chat keystrokes and mouse moves for AH price tests.

    Casual: the hands that type /ah and hover the listing.
    One responsibility: input injection. No screenshots, no OCR.
    """

    def __init__(
        self,
        chat_open_delay: float = CHAT_OPEN_DELAY_SECONDS,
        type_interval: float = TYPE_INTERVAL_SECONDS,
        after_enter_delay: float = AFTER_ENTER_DELAY_SECONDS,
        after_hover_delay: float = AFTER_HOVER_DELAY_SECONDS,
    ) -> None:
        self._chat_open_delay = chat_open_delay
        self._type_interval = type_interval
        self._after_enter_delay = after_enter_delay
        self._after_hover_delay = after_hover_delay

    def press_chat_key(self) -> None:
        """
        Press T to open Minecraft chat.

        Casual: hits the chat key and waits a beat for the bar to appear.
        """
        logger.info("Pressing chat key (T)")
        pyautogui.press("t")
        time.sleep(self._chat_open_delay)

    def type_text(self, text: str) -> None:
        """
        Type a string character-by-character into the focused window.

        Casual: slowly types whatever you pass (like the /ah command).
        Prefer paste_text() for long item names when speed matters.
        """
        logger.info("Typing %r", text)
        # interval keeps AH / chat from dropping characters under load
        pyautogui.write(text, interval=self._type_interval)

    def paste_text(self, text: str, *, restore_clipboard: bool = False) -> str | None:
        """
        Paste a string via clipboard + Ctrl+V (instant, no per-char delay).

        Casual: slam the whole command into chat in one shot.
        Used by market-making where long names like "enchanted golden apple"
        would waste hundreds of ms if typed character-by-character.

        IMPORTANT: do NOT restore the clipboard immediately after Ctrl+V —
        Minecraft reads the clipboard asynchronously, so restoring too soon
        pastes the old contents (or nothing) and the /ah never opens.
        Returns the previous clipboard text so callers can restore later
        (e.g. after Enter). Set ``restore_clipboard=True`` only for one-offs
        that are not followed by an immediate Enter.
        """
        payload = str(text)
        if not payload:
            raise ValueError("paste_text requires non-empty text")

        logger.info("Pasting %r", payload)
        previous_clipboard: str | None = None
        try:
            previous_clipboard = pyperclip.paste()
        except Exception as exc:
            # Clipboard can be empty / locked; still paste our command.
            logger.debug("Could not read previous clipboard: %s", exc)

        pyperclip.copy(payload)
        # Tiny beat so the OS clipboard is ready before Ctrl+V.
        time.sleep(0.05)
        pyautogui.hotkey("ctrl", "v")
        # Give the game a moment to pull from the clipboard before we touch it.
        time.sleep(0.05)

        if restore_clipboard and previous_clipboard is not None:
            self.restore_clipboard(previous_clipboard)
            return None
        return previous_clipboard

    @staticmethod
    def restore_clipboard(previous: str | None) -> None:
        """
        Put the caller's old clipboard text back.

        Casual: undo our temporary paste payload once chat is submitted.
        """
        if previous is None:
            return
        try:
            pyperclip.copy(previous)
        except Exception as exc:
            logger.debug("Could not restore clipboard: %s", exc)

    def press_enter(self, settle_seconds: float | None = None) -> None:
        """
        Submit chat / confirm the AH search.

        Casual: hits Enter and optionally waits for the GUI to catch up.
        Pass settle_seconds=0 for market-making (snap mouse immediately).
        """
        delay = (
            self._after_enter_delay if settle_seconds is None else float(settle_seconds)
        )
        logger.info("Pressing Enter (settle=%.3fs)", delay)
        pyautogui.press("enter")
        if delay > 0:
            time.sleep(delay)

    def hover_item(self, xy: tuple[int, int] | None = None) -> None:
        """
        Move the mouse onto a listing so the tooltip pops up.

        Casual: parks the cursor on the item slot you calibrated.
        """
        target = xy or ITEM_HOVER_XY
        logger.info("Hovering item at %s", target)
        pyautogui.moveTo(target[0], target[1], duration=0.15)
        time.sleep(self._after_hover_delay)

    def hover_item_instant(
        self,
        xy: tuple[int, int] | None = None,
        *,
        settle_seconds: float = 0.10,
        move_duration: float = 0.0,
    ) -> None:
        """
        Snap the mouse onto a listing with no slow glide.

        Casual: teleport onto slot 0 and wait a tiny beat for the tip.
        Market-making uses this because the AH/order menu is up within ~0.1s.
        """
        target = xy or ITEM_HOVER_XY
        logger.info(
            "Instant hover at %s (move=%.3fs settle=%.3fs)",
            target,
            move_duration,
            settle_seconds,
        )
        pyautogui.moveTo(target[0], target[1], duration=float(move_duration))
        if settle_seconds > 0:
            time.sleep(float(settle_seconds))

    def open_ah_search(self, query: str | None = None) -> None:
        """
        Full chat sequence: T → type query → Enter.

        Casual: opens chat and runs your /ah search in one shot.
        Does not move the mouse — call hover_item() after the GUI loads.
        """
        self.press_chat_key()
        command = AhSearchQueryNormalizer.normalize(query)
        self.type_text(command)
        self.press_enter()

    def open_chat_command_paste(
        self,
        command: str,
        *,
        after_enter_delay: float | None = None,
    ) -> None:
        """
        Full chat sequence: T → paste command → Enter (no per-char typing).

        Casual: paste /ah or /order instantly, then submit.
        Used by spread-check so long item names don't burn typing time.
        Keeps our clipboard payload until after Enter so Minecraft can read it.
        """
        cleaned = str(command).strip()
        if not cleaned:
            raise ValueError("chat command must be non-empty")
        settle = (
            self._after_enter_delay
            if after_enter_delay is None
            else float(after_enter_delay)
        )
        self.press_chat_key()
        previous = self.paste_text(cleaned, restore_clipboard=False)
        self.press_enter(settle_seconds=settle)
        # Safe to restore now — Enter already consumed the pasted command.
        self.restore_clipboard(previous)

    def press_escape(self, settle_seconds: float | None = None) -> None:
        """
        Hit Escape to close the current GUI (AH results, confirm, etc.).

        Casual: backs out of whatever menu you're stuck in.
        Used before a fresh /ah search when a previous auction screen is open.
        """
        delay = (
            AFTER_ESCAPE_DELAY_SECONDS
            if settle_seconds is None
            else float(settle_seconds)
        )
        logger.info("Pressing Escape (settle=%.3fs)", delay)
        pyautogui.press("esc")
        if delay > 0:
            time.sleep(delay)

    def left_click_at(
        self,
        xy: tuple[int, int],
        *,
        settle_seconds: float | None = None,
        after_click_delay: float | None = None,
    ) -> None:
        """
        Hover a screen point, then left-click once (AH purchase).

        Casual: park on the cheap listing and click buy.
        Moves first so the tooltip / slot highlight is on the intended item,
        then issues a single left click — no double-click, no drag.
        """
        hover_settle = (
            self._after_hover_delay if settle_seconds is None else float(settle_seconds)
        )
        click_settle = (
            AFTER_PURCHASE_CLICK_DELAY_SECONDS
            if after_click_delay is None
            else float(after_click_delay)
        )
        logger.info("Left-click purchase at %s", xy)
        pyautogui.moveTo(xy[0], xy[1], duration=0.08)
        if hover_settle > 0:
            time.sleep(hover_settle)
        pyautogui.click(xy[0], xy[1], button="left", clicks=1)
        if click_settle > 0:
            time.sleep(click_settle)

    def click_buy_confirm_yes(
        self,
        xy: tuple[int, int] | None = None,
        *,
        after_click_delay: float | None = None,
    ) -> None:
        """
        Left-click the Yes button on the high-price confirm dialog.

        Casual: smash Yes when the are-you-sure popup shows up.
        Uses a short move so the cursor lands on the calibrated button before
        the click; settle after so the dialog can close before the next search.
        """
        target = xy or BUY_CONFIRM_YES_XY
        click_settle = (
            AFTER_BUY_CONFIRM_CLICK_DELAY_SECONDS
            if after_click_delay is None
            else float(after_click_delay)
        )
        logger.info("Clicking buy-confirm Yes at %s", target)
        pyautogui.moveTo(target[0], target[1], duration=0.05)
        pyautogui.click(target[0], target[1], button="left", clicks=1)
        if click_settle > 0:
            time.sleep(click_settle)

    def select_hotbar_slot(
        self,
        slot: int,
        *,
        settle_seconds: float | None = None,
    ) -> None:
        """
        Press a hotbar number key (1–9) so that slot is held.

        Casual: hit 1 so the just-bought item is in our hand.
        Bought AH items land in the first empty hotbar slot; we keep slot 1
        empty on purpose so purchases always land there for an immediate sell.
        """
        if slot < 1 or slot > 9:
            raise ValueError(f"hotbar slot must be 1..9, got {slot}")
        delay = (
            AFTER_HOTBAR_SELECT_DELAY_SECONDS
            if settle_seconds is None
            else float(settle_seconds)
        )
        logger.info("Selecting hotbar slot %s", slot)
        pyautogui.press(str(slot))
        if delay > 0:
            time.sleep(delay)

    def open_ah_sell(
        self,
        price_text: str,
        *,
        after_enter_delay: float | None = None,
    ) -> None:
        """
        Chat sequence: T → /ah sell <price> → Enter.

        Casual: list whatever we're holding at the given price string.
        ``price_text`` should already be compact (e.g. ``7.6m``) — we do not
        reformat here. Caller must have the item selected in the hotbar.
        """
        cleaned = str(price_text).strip()
        if not cleaned:
            raise ValueError("sell price text must be non-empty")
        command = f"/ah sell {cleaned}"
        settle = (
            AFTER_SELL_COMMAND_DELAY_SECONDS
            if after_enter_delay is None
            else float(after_enter_delay)
        )
        logger.info("Opening AH sell: %r", command)
        self.press_chat_key()
        self.type_text(command)
        # press_enter uses AFTER_ENTER_DELAY; override with sell-specific settle.
        logger.info("Pressing Enter (sell settle=%.3fs)", settle)
        pyautogui.press("enter")
        if settle > 0:
            time.sleep(settle)
