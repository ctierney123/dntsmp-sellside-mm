"""
HUD balance floor for overnight armor-arb — pause when cash is too low.

Casual: if we're under 30m, wait for listings to sell before buying more.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from ah_price.config import (
    ARMOR_ARB_BALANCE_MAX_FAILURES,
    ARMOR_ARB_BALANCE_WAIT_SECONDS,
    ARMOR_ARB_MIN_BALANCE_COINS,
)
from screen_reader import read_once

logger = logging.getLogger(__name__)


class BalanceFloorHalt(RuntimeError):
    """
    Raised when balance stays under the floor for too many wait cycles.

    Casual: we tried waiting; cash never recovered — stop the bot.
    """


class BalanceGuardManager:
    """
    Read the scoreboard balance and enforce a minimum cash floor.

    Casual: don't keep sniping if our liquid money is too low.
    While sell orders are outstanding, liquid balance drops. Before each
    overnight / armor-arb pass (clear HUD only — never mid-AH), we require
    ``balance >= ARMOR_ARB_MIN_BALANCE_COINS``. Under the floor → wait
    ``ARMOR_ARB_BALANCE_WAIT_SECONDS`` and re-check. After
    ``ARMOR_ARB_BALANCE_MAX_FAILURES`` consecutive under-floor reads,
    raise ``BalanceFloorHalt`` so the overnight loop exits cleanly.
    """

    def __init__(
        self,
        min_balance_coins: int = ARMOR_ARB_MIN_BALANCE_COINS,
        wait_seconds: float = ARMOR_ARB_BALANCE_WAIT_SECONDS,
        max_failures: int = ARMOR_ARB_BALANCE_MAX_FAILURES,
        reader: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        if min_balance_coins < 0:
            raise ValueError("min_balance_coins must be non-negative")
        if wait_seconds < 0:
            raise ValueError("wait_seconds must be non-negative")
        if max_failures < 1:
            raise ValueError("max_failures must be >= 1")
        self._min_balance = int(min_balance_coins)
        self._wait_seconds = float(wait_seconds)
        self._max_failures = int(max_failures)
        self._reader = reader or read_once
        self._consecutive_failures = 0

    @property
    def min_balance_coins(self) -> int:
        return self._min_balance

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    def read_balance(self) -> dict[str, Any]:
        """
        Snapshot the HUD balance via the screen reader.

        Casual: peek at how much cash we still have liquid.
        """
        result = self._reader()
        balance = result.get("balance")
        if balance is None:
            raise RuntimeError(
                f"HUD read missing balance field: {result!r}"
            )
        return {
            "username": result.get("username"),
            "balance_raw": result.get("balance_raw"),
            "balance": int(balance),
        }

    def ensure_above_floor(self, *, context: str = "pass") -> dict[str, Any]:
        """
        Block until balance is above the floor, or halt after N failures.

        Casual: wait for sells to clear if we're broke; quit if stuck.
        A successful above-floor read resets the consecutive failure counter.
        OCR / read errors count as a failure cycle (same wait + retry).
        """
        while True:
            try:
                snapshot = self.read_balance()
            except Exception as exc:
                self._consecutive_failures += 1
                logger.warning(
                    "Balance read failed (%s/%s) during %s: %s",
                    self._consecutive_failures,
                    self._max_failures,
                    context,
                    exc,
                )
                print(
                    f"Balance read failed ({self._consecutive_failures}/"
                    f"{self._max_failures}) — {exc}"
                )
                self._raise_if_exhausted(context)
                self._sleep_wait()
                continue

            balance = int(snapshot["balance"])
            raw = snapshot.get("balance_raw")
            print(
                f"Balance check ({context}): {raw} / {balance:,} "
                f"(floor {self._min_balance:,})"
            )

            if balance >= self._min_balance:
                self._consecutive_failures = 0
                return snapshot

            self._consecutive_failures += 1
            print(
                f"Balance below floor "
                f"({self._consecutive_failures}/{self._max_failures}) — "
                f"waiting {self._wait_seconds:.0f}s for sells to clear"
            )
            self._raise_if_exhausted(context)
            self._sleep_wait()

    def _raise_if_exhausted(self, context: str) -> None:
        if self._consecutive_failures < self._max_failures:
            return
        message = (
            f"Balance stayed under {self._min_balance:,} for "
            f"{self._max_failures} consecutive checks ({context}) — halting."
        )
        print(message)
        raise BalanceFloorHalt(message)

    def _sleep_wait(self) -> None:
        if self._wait_seconds > 0:
            time.sleep(self._wait_seconds)
