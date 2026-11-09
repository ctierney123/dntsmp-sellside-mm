"""
Track overnight armor-arb stats for session + rolling window prints.

Casual: keep score on buys, profit, and how busy the last 15 minutes were.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ArmorArbPurchaseMetric:
    """
    One buy(+sell) event used for rolling / session averages.

    Casual: the numbers we care about from a single snag.
    ``checked_prices`` is the first-row OCR snapshot at buy time (may be
    a partial row when early-buy stopped after slots 0–3).
    """

    timestamp: float
    pass_number: int
    kind: str
    query: str
    buy_coins: int
    sell_coins: int | None
    profit_coins: int | None
    margin: float | None
    checked_prices: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class ArmorArbPassMetric:
    """
    One planned overnight pass (rechecks roll into the same pass number).

    Casual: how many items we poked and how many we bought that lap.
    """

    timestamp: float
    pass_number: int
    items_searched: int
    purchase_count: int
    sell_count: int


class ArmorArbSessionMetricsManager:
    """
    Accumulate pass + purchase metrics and print session / window overviews.

    Casual: after each loop, show how we're doing tonight and lately.
    Planned passes count as loops. Recheck buys attach to the parent pass
    number but do not create a new loop entry. Profit / margin only use
    purchases that have both buy and sell coins.
    """

    def __init__(
        self,
        *,
        window_seconds: float,
        started_at: float | None = None,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._window_seconds = float(window_seconds)
        self._started_at = float(time.time() if started_at is None else started_at)
        self._passes: list[ArmorArbPassMetric] = []
        self._purchases: list[ArmorArbPurchaseMetric] = []

    @property
    def window_seconds(self) -> float:
        return self._window_seconds

    @property
    def purchase_count(self) -> int:
        return len(self._purchases)

    def record_pass_report(
        self,
        *,
        pass_number: int,
        kind: str,
        summary: dict[str, Any],
        now: float | None = None,
    ) -> list[ArmorArbPurchaseMetric]:
        """
        Ingest one pass/recheck summary and return newly recorded purchases.

        Casual: feed the loop report in; get back the buys we just logged.
        """
        stamp = float(time.time() if now is None else now)
        items = list(summary.get("items") or [])
        purchase_count = int(summary.get("purchase_count") or 0)
        sell_count = int(summary.get("sell_count") or 0)

        # Only planned overnight laps count as "loops" for avg purchases/loop.
        if kind == "planned":
            self._passes.append(
                ArmorArbPassMetric(
                    timestamp=stamp,
                    pass_number=int(pass_number),
                    items_searched=len(items),
                    purchase_count=purchase_count,
                    sell_count=sell_count,
                )
            )
        else:
            # Recheck buys still belong to the parent pass's purchase total
            # for "avg purchases per loop" — fold into the matching pass row.
            self._fold_recheck_into_pass(
                pass_number=int(pass_number),
                purchase_count=purchase_count,
                sell_count=sell_count,
            )

        recorded: list[ArmorArbPurchaseMetric] = []
        for row in items:
            metric = self._purchase_from_item_row(
                row,
                pass_number=int(pass_number),
                kind=str(kind),
                timestamp=stamp,
            )
            if metric is None:
                continue
            self._purchases.append(metric)
            recorded.append(metric)
        return recorded

    def print_overview(self, *, now: float | None = None) -> None:
        """
        Print session totals and the rolling window side by side.

        Casual: big-picture scoreboard after each overnight lap.
        """
        stamp = float(time.time() if now is None else now)
        session = self._compute_snapshot(
            passes=self._passes,
            purchases=self._purchases,
            elapsed_seconds=max(0.0, stamp - self._started_at),
        )
        window_passes = [
            row
            for row in self._passes
            if row.timestamp >= stamp - self._window_seconds
        ]
        window_purchases = [
            row
            for row in self._purchases
            if row.timestamp >= stamp - self._window_seconds
        ]
        window = self._compute_snapshot(
            passes=window_passes,
            purchases=window_purchases,
            elapsed_seconds=min(
                self._window_seconds,
                max(0.0, stamp - self._started_at),
            ),
        )

        window_label = self._format_window_label(self._window_seconds)
        print()
        print("=== Armor arb loop metrics ===")
        print(f"Session ({self._format_duration(session['elapsed_seconds'])}):")
        self._print_snapshot_lines(session, indent="  ")
        print(f"Past {window_label}:")
        self._print_snapshot_lines(window, indent="  ")
        print()

    def _fold_recheck_into_pass(
        self,
        *,
        pass_number: int,
        purchase_count: int,
        sell_count: int,
    ) -> None:
        """
        Add recheck buys/sells onto the matching planned pass counters.

        Casual: recheck snags still count toward that loop's purchase rate.
        """
        for index in range(len(self._passes) - 1, -1, -1):
            row = self._passes[index]
            if row.pass_number != pass_number:
                continue
            self._passes[index] = ArmorArbPassMetric(
                timestamp=row.timestamp,
                pass_number=row.pass_number,
                items_searched=row.items_searched,
                purchase_count=row.purchase_count + purchase_count,
                sell_count=row.sell_count + sell_count,
            )
            return

    @staticmethod
    def _purchase_from_item_row(
        row: dict[str, Any],
        *,
        pass_number: int,
        kind: str,
        timestamp: float,
    ) -> ArmorArbPurchaseMetric | None:
        """
        Build a purchase metric from one armor-arb item report row.

        Casual: only real buys become metric points.
        """
        if not row.get("purchased"):
            return None
        opportunity = row.get("opportunity") or {}
        buy_coins = opportunity.get("price")
        if buy_coins is None:
            return None
        buy_coins_int = int(buy_coins)

        sell = row.get("sell") or {}
        sell_coins: int | None = None
        decision = sell.get("decision") or {}
        if sell.get("sold") and decision.get("sell_coins") is not None:
            sell_coins = int(decision["sell_coins"])

        profit_coins: int | None = None
        margin: float | None = None
        if sell_coins is not None:
            profit_coins = sell_coins - buy_coins_int
            if buy_coins_int > 0:
                margin = profit_coins / buy_coins_int

        checked_prices = ArmorArbSessionMetricsManager._checked_prices_from_row(
            row
        )

        return ArmorArbPurchaseMetric(
            timestamp=timestamp,
            pass_number=pass_number,
            kind=kind,
            query=str(row.get("query") or ""),
            buy_coins=buy_coins_int,
            sell_coins=sell_coins,
            profit_coins=profit_coins,
            margin=margin,
            checked_prices=checked_prices,
        )

    @staticmethod
    def _checked_prices_from_row(
        row: dict[str, Any],
    ) -> tuple[dict[str, Any], ...]:
        """
        Pull the compare-row prices that were OCR'd when we bought.

        Casual: remember what the book looked like at click time.
        Keeps slot / price / raw / ok so the JSON log can show partial
        early-buy probes (slots 0–3 only) as well as full 9-slot scans.
        """
        compare = row.get("compare") or {}
        listings = compare.get("listings") or []
        checked: list[dict[str, Any]] = []
        for listing in listings:
            checked.append(
                {
                    "slot": listing.get("slot"),
                    "price": listing.get("price"),
                    "price_raw": listing.get("price_raw"),
                    "ok": bool(listing.get("ok")),
                }
            )
        return tuple(checked)

    @staticmethod
    def _compute_snapshot(
        *,
        passes: list[ArmorArbPassMetric],
        purchases: list[ArmorArbPurchaseMetric],
        elapsed_seconds: float,
    ) -> dict[str, Any]:
        """
        Roll pass/purchase lists into printable averages.

        Casual: turn the event log into the scoreboard numbers.
        """
        loop_count = len(passes)
        purchase_count = len(purchases)
        sell_count = sum(1 for row in purchases if row.sell_coins is not None)
        profits = [
            row.profit_coins
            for row in purchases
            if row.profit_coins is not None
        ]
        margins = [row.margin for row in purchases if row.margin is not None]

        total_profit = sum(profits) if profits else 0
        avg_profit = (sum(profits) / len(profits)) if profits else None
        avg_margin = (sum(margins) / len(margins)) if margins else None
        avg_purchases_per_loop = (
            (sum(row.purchase_count for row in passes) / loop_count)
            if loop_count
            else None
        )

        return {
            "elapsed_seconds": elapsed_seconds,
            "loop_count": loop_count,
            "purchase_count": purchase_count,
            "sell_count": sell_count,
            "total_profit_coins": total_profit,
            "avg_profit_coins": avg_profit,
            "avg_margin": avg_margin,
            "avg_purchases_per_loop": avg_purchases_per_loop,
        }

    @staticmethod
    def _print_snapshot_lines(snapshot: dict[str, Any], *, indent: str) -> None:
        """Pretty-print one metrics snapshot block."""
        loops = snapshot["loop_count"]
        buys = snapshot["purchase_count"]
        sells = snapshot["sell_count"]
        print(f"{indent}loops: {loops}  purchases: {buys}  sells: {sells}")

        avg_buys = snapshot["avg_purchases_per_loop"]
        if avg_buys is None:
            print(f"{indent}avg purchases/loop: n/a")
        else:
            print(f"{indent}avg purchases/loop: {avg_buys:.2f}")

        total_profit = int(snapshot["total_profit_coins"])
        avg_profit = snapshot["avg_profit_coins"]
        avg_margin = snapshot["avg_margin"]
        print(f"{indent}total profit: {total_profit:,} coins")
        if avg_profit is None:
            print(f"{indent}avg profit/buy: n/a")
        else:
            print(f"{indent}avg profit/buy: {avg_profit:,.0f} coins")
        if avg_margin is None:
            print(f"{indent}avg profit margin: n/a")
        else:
            print(f"{indent}avg profit margin: {avg_margin * 100.0:.2f}%")

    @staticmethod
    def _format_window_label(seconds: float) -> str:
        minutes = seconds / 60.0
        if abs(minutes - round(minutes)) < 1e-6:
            return f"{int(round(minutes))} min"
        return f"{minutes:.1f} min"

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total = int(max(0.0, seconds))
        hours, rem = divmod(total, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {secs}s"
        return f"{secs}s"
