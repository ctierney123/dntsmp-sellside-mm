"""
Overnight armor-arb loop with random sleeps and a balance floor.

Casual: keep sniping + selling all night, with human-ish pauses.
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any

from ah_price.armor_arb.manager import ArmorArbManager
from ah_price.armor_arb.pass_planner import ArmorArbPassPlanner
from ah_price.armor_arb.order_book_log_manager import ArmorArbOrderBookLogManager
from ah_price.armor_arb.purchase_log_manager import ArmorArbPurchaseLogManager
from ah_price.armor_arb.session_metrics_manager import ArmorArbSessionMetricsManager
from ah_price.guards.balance_guard_manager import BalanceFloorHalt, BalanceGuardManager
from ah_price.config import (
    ARMOR_ARB_BALANCE_MAX_FAILURES,
    ARMOR_ARB_BALANCE_WAIT_SECONDS,
    ARMOR_ARB_LONG_PAUSE_CHANCE,
    ARMOR_ARB_LONG_PAUSE_MAX_SECONDS,
    ARMOR_ARB_LONG_PAUSE_MIN_SECONDS,
    ARMOR_ARB_LOOP_RECHECK_BOUGHT,
    ARMOR_ARB_LOOP_SLEEP_MAX_SECONDS,
    ARMOR_ARB_LOOP_SLEEP_MIN_SECONDS,
    ARMOR_ARB_METRICS_WINDOW_SECONDS,
    ARMOR_ARB_ORDER_BOOK_LOG_ENABLED,
    ARMOR_ARB_PARSE_MAX_ONE_OFF_FAILURES,
    ARMOR_ARB_PURCHASE_LOG_MIN_SESSION_PURCHASES,
    FOCUS_COUNTDOWN_SECONDS,
)
from ah_price.guards.parse_failure_guard_manager import (
    ParseFailureGuardManager,
    ParseFailureHalt,
)

logger = logging.getLogger(__name__)


class ArmorArbLoopCoordinator:
    """
    Repeat armor-arb passes until halted or interrupted.

    Casual: run forever with shuffled / partial sets and random chill time.
    Each pass:
      1) Plan a shuffled query list (sometimes a random subset).
      2) Run one ArmorArbManager pass (floor check once at pass start,
         then buy → immediate sell per snag — no mid-AH balance OCR).
         Slot OCR FAILs are tracked session-wide: one one-off miss is
         tolerated; any further parse fail raises ParseFailureHalt.
      3) If anything was bought, immediately re-check those same items
         once more (no inter-pass sleep / no second balance OCR) before
         starting the next planned pass.
      4) Print session + rolling-window metrics; append order-book JSONL
         for every price check; maybe unlock purchase JSON.
      5) Sleep a uniform random 5–60s (skipped entirely when
         ``no_sleep`` is set — for tight testing loops).
      6) If the planned pass bought nothing (full skips), ~10% of the
         time add an extra 2–5 minute pause. Buys skip the long pause.
         Long pauses are also skipped when ``no_sleep`` is set.
    """

    def __init__(
        self,
        arb_manager: ArmorArbManager | None = None,
        balance_guard: BalanceGuardManager | None = None,
        parse_failure_guard: ParseFailureGuardManager | None = None,
        pass_planner: ArmorArbPassPlanner | None = None,
        metrics_manager: ArmorArbSessionMetricsManager | None = None,
        purchase_log_manager: ArmorArbPurchaseLogManager | None = None,
        order_book_log_manager: ArmorArbOrderBookLogManager | None = None,
        countdown_seconds: float = FOCUS_COUNTDOWN_SECONDS,
        sleep_min_seconds: float = ARMOR_ARB_LOOP_SLEEP_MIN_SECONDS,
        sleep_max_seconds: float = ARMOR_ARB_LOOP_SLEEP_MAX_SECONDS,
        long_pause_chance: float = ARMOR_ARB_LONG_PAUSE_CHANCE,
        long_pause_min_seconds: float = ARMOR_ARB_LONG_PAUSE_MIN_SECONDS,
        long_pause_max_seconds: float = ARMOR_ARB_LONG_PAUSE_MAX_SECONDS,
        recheck_bought: bool = ARMOR_ARB_LOOP_RECHECK_BOUGHT,
        metrics_window_seconds: float = ARMOR_ARB_METRICS_WINDOW_SECONDS,
        no_sleep: bool = False,
        rng: random.Random | None = None,
    ) -> None:
        if sleep_min_seconds < 0 or sleep_max_seconds < sleep_min_seconds:
            raise ValueError("invalid loop sleep range")
        if not 0.0 <= long_pause_chance <= 1.0:
            raise ValueError("long_pause_chance must be in [0, 1]")
        if (
            long_pause_min_seconds < 0
            or long_pause_max_seconds < long_pause_min_seconds
        ):
            raise ValueError("invalid long pause range")

        self._arb = arb_manager
        self._owns_arb = arb_manager is None
        self._balance = balance_guard or BalanceGuardManager()
        # Shared across every overnight pass / recheck — one freebie OCR miss.
        self._parse_failures = (
            parse_failure_guard or ParseFailureGuardManager()
        )
        self._rng = rng or random.Random()
        # Planner defaults (subset chance / size) come from config.py.
        self._planner = pass_planner or ArmorArbPassPlanner(rng=self._rng)
        self._countdown = float(countdown_seconds)
        self._sleep_min = float(sleep_min_seconds)
        self._sleep_max = float(sleep_max_seconds)
        self._long_chance = float(long_pause_chance)
        self._long_min = float(long_pause_min_seconds)
        self._long_max = float(long_pause_max_seconds)
        self._recheck_bought = bool(recheck_bought)
        # Testing: skip 5–60s + long coffee breaks between passes.
        self._no_sleep = bool(no_sleep)
        self._pass_count = 0
        started_at = time.time()
        self._metrics = metrics_manager or ArmorArbSessionMetricsManager(
            window_seconds=metrics_window_seconds,
            started_at=started_at,
        )
        self._purchase_log = purchase_log_manager or ArmorArbPurchaseLogManager(
            started_at=started_at,
        )
        # Separate from purchases: every first-row OCR (buy or skip).
        self._order_book_log = (
            order_book_log_manager
            or ArmorArbOrderBookLogManager(started_at=started_at)
        )

    def run(self) -> dict[str, Any]:
        """
        Countdown once, then loop armor-arb until halt / Ctrl+C.

        Casual: click Minecraft, then we grind overnight for you.
        """
        arb = self._ensure_arb()
        self._print_start_banner()
        ArmorArbManager._sleep_countdown(self._countdown)

        pass_reports: list[dict[str, Any]] = []
        halted_reason: str | None = None

        try:
            while True:
                self._pass_count += 1
                planned = self._planner.plan()
                print()
                print(f"=== Armor arb overnight pass {self._pass_count} ===")

                # Balance floor lives inside run_pass (once per lap, clear HUD).
                # run_pass Escs after a trailing skip so AH is closed before
                # the next pass-start balance OCR / inter-pass sleep.
                summary = arb.run_pass(
                    probe_escape=True,
                    queries=planned,
                    check_balance=True,
                    label=f"pass {self._pass_count}",
                )
                pass_reports.append(
                    {
                        "pass": self._pass_count,
                        "kind": "planned",
                        "summary": summary,
                    }
                )
                self._ingest_pass_report(
                    pass_number=self._pass_count,
                    kind="planned",
                    summary=summary,
                )

                # Snagged something? Peek those same items again right away
                # before the long inter-pass sleep — books refill fast.
                recheck = self._maybe_recheck_bought(arb, summary)
                if recheck is not None:
                    pass_reports.append(recheck)
                    self._ingest_pass_report(
                        pass_number=self._pass_count,
                        kind="recheck_bought",
                        summary=recheck["summary"],
                    )

                self._metrics.print_overview()
                # Long coffee-break pause only after a dry (all-skip) pass —
                # if we bought anything, stick to the normal 5–60s gap.
                self._inter_pass_sleep(
                    allow_long_pause=self._pass_had_no_purchases(summary)
                )
        except BalanceFloorHalt as exc:
            halted_reason = str(exc)
            logger.error("%s", halted_reason)
        except ParseFailureHalt as exc:
            halted_reason = str(exc)
            logger.error("%s", halted_reason)
        except KeyboardInterrupt:
            halted_reason = "keyboard_interrupt"
            print("\nOvernight loop interrupted.")
            raise
        finally:
            if self._owns_arb and self._arb is not None:
                self._arb.close()

        return {
            "passes": self._pass_count,
            "pass_reports": pass_reports,
            "halted_reason": halted_reason,
            "parse_failures": self._parse_failures.failed_slot_count,
            "purchase_log": {
                "enabled": self._purchase_log.logging_enabled,
                "path": (
                    str(self._purchase_log.log_path)
                    if self._purchase_log.log_path
                    else None
                ),
                "session_purchase_count": (
                    self._purchase_log.session_purchase_count
                ),
            },
            "order_book_log": {
                "enabled": self._order_book_log.enabled,
                "path": (
                    str(self._order_book_log.log_path)
                    if self._order_book_log.log_path
                    else None
                ),
                "record_count": self._order_book_log.record_count,
            },
        }

    def _ingest_pass_report(
        self,
        *,
        pass_number: int,
        kind: str,
        summary: dict[str, Any],
    ) -> None:
        """
        Feed one pass/recheck into metrics + order-book + purchase logs.

        Casual: update the scoreboard, stash every book we scanned, and
        maybe start writing snags to the purchase JSON.
        """
        recorded = self._metrics.record_pass_report(
            pass_number=pass_number,
            kind=kind,
            summary=summary,
        )
        # Always log the OCR'd books (buys + skips) when enabled.
        order_book_status = self._order_book_log.record_pass_report(
            pass_number=pass_number,
            kind=kind,
            summary=summary,
        )
        newly_books = int(order_book_status.get("newly_written") or 0)
        if order_book_status.get("enabled") and newly_books > 0:
            print(
                f"Logged {newly_books} order book check(s) → "
                f"{order_book_status.get('log_path')}"
            )

        log_status = self._purchase_log.record_purchases(recorded)
        if log_status.get("just_unlocked"):
            print(
                "Purchase JSON logging unlocked "
                f"(>{ARMOR_ARB_PURCHASE_LOG_MIN_SESSION_PURCHASES} session buys) "
                f"→ {log_status.get('log_path')}"
            )
        elif (
            log_status.get("logging_enabled")
            and int(log_status.get("newly_written") or 0) > 0
        ):
            print(
                f"Logged {log_status['newly_written']} purchase(s) → "
                f"{log_status.get('log_path')}"
            )

    def _maybe_recheck_bought(
        self,
        arb: ArmorArbManager,
        summary: dict[str, Any],
    ) -> dict[str, Any] | None:
        """
        Immediately re-scan items that were bought on the pass that just ended.

        Casual: if we snagged a piece, look again before the next chill sleep.
        Skips balance OCR (HUD was already cleared by end-of-pass Esc / sell)
        and does not count as a new overnight pass number — it's a follow-up
        of the pass that just finished. Recheck buys do not chain into another
        recheck (one immediate peek only).
        """
        if not self._recheck_bought:
            return None

        bought_queries = self._bought_queries(summary)
        if not bought_queries:
            return None

        print()
        print(
            f"=== Immediate recheck after buys "
            f"({len(bought_queries)} item(s)) ==="
        )
        recheck_summary = arb.run_pass(
            probe_escape=True,
            queries=bought_queries,
            # Floor was just checked at the parent pass start; stay on HUD.
            check_balance=False,
            label=f"recheck after pass {self._pass_count}",
        )
        return {
            "pass": self._pass_count,
            "kind": "recheck_bought",
            "summary": recheck_summary,
        }

    @staticmethod
    def _bought_queries(summary: dict[str, Any]) -> tuple[str, ...]:
        """
        Collect unique queries that actually purchased on this pass.

        Casual: only the items we snagged — ignore skips.
        Preserves first-seen order from the pass report.
        """
        seen: set[str] = set()
        ordered: list[str] = []
        for row in summary.get("items") or []:
            if not row.get("purchased"):
                continue
            query = str(row.get("query") or "").strip()
            if not query or query in seen:
                continue
            seen.add(query)
            ordered.append(query)
        return tuple(ordered)

    def _ensure_arb(self) -> ArmorArbManager:
        if self._arb is None:
            # Countdown is owned by the loop; each pass should not re-count.
            self._arb = ArmorArbManager(
                countdown_seconds=0.0,
                balance_guard=self._balance,
                parse_failure_guard=self._parse_failures,
            )
        return self._arb

    @staticmethod
    def _pass_had_no_purchases(summary: dict[str, Any]) -> bool:
        """
        True when the pass bought nothing (full skips).

        Casual: dry lap with zero snags — long-pause eligible.
        Prefers purchase_count when present; otherwise scans item rows.
        """
        if "purchase_count" in summary:
            return int(summary.get("purchase_count") or 0) == 0
        return not any(
            row.get("purchased") for row in (summary.get("items") or [])
        )

    def _inter_pass_sleep(self, *, allow_long_pause: bool = True) -> None:
        """
        Human-ish gap between full armor-set passes.

        Casual: chill 5–60s; on dry (all-skip) passes, sometimes coffee longer.
        The random 2–5 min pause only rolls when allow_long_pause is True
        (planned pass had zero purchases). After buys we only take the base sleep.
        With ``--no-sleep``, both the base gap and long pause are skipped so
        passes can back-to-back for testing.
        """
        # Fast-test mode: zero delay between iterations (still prints so logs
        # make it obvious why the loop is hammering without pauses).
        if self._no_sleep:
            print("Inter-pass sleep: skipped (--no-sleep)")
            return

        base = self._rng.uniform(self._sleep_min, self._sleep_max)
        print(f"Inter-pass sleep: {base:.1f}s")
        time.sleep(base)

        if not allow_long_pause:
            return

        if self._rng.random() < self._long_chance:
            long_pause = self._rng.uniform(self._long_min, self._long_max)
            print(
                f"Random long pause ({self._long_chance:.0%} chance): "
                f"{long_pause / 60.0:.1f} min"
            )
            time.sleep(long_pause)

    def _print_start_banner(self) -> None:
        wait_min = ARMOR_ARB_BALANCE_WAIT_SECONDS / 60.0
        catalog_len = len(self._planner.catalog)
        window_min = self._metrics.window_seconds / 60.0
        print(
            "Click into Minecraft now — overnight armor arb starts in "
            f"{self._countdown:.0f}s"
        )
        print(
            f"  balance floor: {self._balance.min_balance_coins:,} "
            f"(wait {wait_min:.0f}m; "
            f"halt after {ARMOR_ARB_BALANCE_MAX_FAILURES} fails)"
        )
        print(
            "  parse fails: tolerate "
            f"{ARMOR_ARB_PARSE_MAX_ONE_OFF_FAILURES} one-off slot OCR miss "
            f"on slots {sorted(self._parse_failures.counted_slots)}; "
            "any further counted FAIL halts the night "
            "(slot 5+ tall-tooltip misses ignored)"
        )
        if self._no_sleep:
            print(
                "  inter-pass sleep: OFF (--no-sleep; no 5–60s gap, "
                "no long pause)"
            )
        else:
            print(
                f"  inter-pass sleep: {self._sleep_min:.0f}–"
                f"{self._sleep_max:.0f}s; "
                f"after full-skip passes only, {self._long_chance:.0%} "
                f"chance of {self._long_min / 60.0:.0f}–"
                f"{self._long_max / 60.0:.0f} min pause"
            )
        print(
            f"  pass plan: shuffle {catalog_len} catalog item(s); "
            f"{self._planner.subset_chance:.0%} chance of a "
            f"{self._planner.subset_min_items}–"
            f"{self._planner.subset_max_items} item subset"
        )
        print(
            "  after buys: "
            + (
                "immediate recheck of purchased items before next sleep"
                if self._recheck_bought
                else "no immediate recheck"
            )
        )
        print(
            f"  metrics: session + past {window_min:.0f} min after each pass"
        )
        if ARMOR_ARB_ORDER_BOOK_LOG_ENABLED:
            order_book_path = (
                str(self._order_book_log.log_path)
                if self._order_book_log.log_path
                else "logs/armor_arb_order_books/"
            )
            print(f"  order-book JSONL: every price check → {order_book_path}")
        else:
            print("  order-book JSONL: off")
        print(
            "  purchase JSON log: starts after "
            f">{ARMOR_ARB_PURCHASE_LOG_MIN_SESSION_PURCHASES} session buys"
        )
