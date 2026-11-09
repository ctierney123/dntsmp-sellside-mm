"""
Unit tests for overnight session + rolling-window metrics.

Casual: prove averages and the 15-minute window behave.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from ah_price.armor_arb.session_metrics_manager import ArmorArbSessionMetricsManager


def _buy_row(
    query: str,
    *,
    buy: int,
    sell: int,
    purchased: bool = True,
    checked_listings: list[dict] | None = None,
) -> dict:
    listings = checked_listings
    if listings is None:
        listings = [
            {
                "slot": 0,
                "price": buy,
                "price_raw": f"${buy}",
                "ok": True,
            },
            {
                "slot": 1,
                "price": sell + 100_000,
                "price_raw": f"${sell + 100_000}",
                "ok": True,
            },
        ]
    return {
        "query": query,
        "purchased": purchased,
        "opportunity": {"price": buy, "price_raw": f"${buy}", "slot": 0},
        "compare": {"listings": listings},
        "sell": {
            "sold": True,
            "price_text": "x",
            "decision": {"sell_coins": sell},
        },
    }


class ArmorArbSessionMetricsManagerTests(unittest.TestCase):
    """Metrics should track session totals and a rolling time window."""

    def test_records_profit_margin_and_avg_purchases_per_loop(self) -> None:
        metrics = ArmorArbSessionMetricsManager(
            window_seconds=15 * 60,
            started_at=1_000.0,
        )
        metrics.record_pass_report(
            pass_number=1,
            kind="planned",
            summary={
                "items": [
                    _buy_row("/ah boots", buy=6_200_000, sell=6_300_000),
                    {"query": "/ah helm", "purchased": False},
                ],
                "purchase_count": 1,
                "sell_count": 1,
            },
            now=1_010.0,
        )
        metrics.record_pass_report(
            pass_number=1,
            kind="recheck_bought",
            summary={
                "items": [
                    _buy_row("/ah boots", buy=6_400_000, sell=6_500_000),
                ],
                "purchase_count": 1,
                "sell_count": 1,
            },
            now=1_020.0,
        )
        metrics.record_pass_report(
            pass_number=2,
            kind="planned",
            summary={
                "items": [{"query": "/ah ingot", "purchased": False}],
                "purchase_count": 0,
                "sell_count": 0,
            },
            now=1_030.0,
        )

        # Two planned loops; recheck buy folded into pass 1 → 2 buys on loop 1.
        self.assertEqual(metrics.purchase_count, 2)
        self.assertEqual(
            metrics._purchases[0].checked_prices,
            (
                {
                    "slot": 0,
                    "price": 6_200_000,
                    "price_raw": "$6200000",
                    "ok": True,
                },
                {
                    "slot": 1,
                    "price": 6_400_000,
                    "price_raw": "$6400000",
                    "ok": True,
                },
            ),
        )
        snapshot = metrics._compute_snapshot(
            passes=metrics._passes,
            purchases=metrics._purchases,
            elapsed_seconds=30.0,
        )
        self.assertEqual(snapshot["loop_count"], 2)
        self.assertEqual(snapshot["avg_purchases_per_loop"], 1.0)
        # Profits: 100k and 100k → avg 100k; margins 100k/6.2m and 100k/6.4m.
        self.assertEqual(snapshot["avg_profit_coins"], 100_000)
        self.assertAlmostEqual(
            snapshot["avg_margin"],
            ((100_000 / 6_200_000) + (100_000 / 6_400_000)) / 2,
        )

    def test_window_excludes_old_events(self) -> None:
        metrics = ArmorArbSessionMetricsManager(
            window_seconds=60.0,
            started_at=1_000.0,
        )
        metrics.record_pass_report(
            pass_number=1,
            kind="planned",
            summary={
                "items": [_buy_row("/ah a", buy=1_000_000, sell=1_100_000)],
                "purchase_count": 1,
                "sell_count": 1,
            },
            now=1_000.0,
        )
        metrics.record_pass_report(
            pass_number=2,
            kind="planned",
            summary={
                "items": [_buy_row("/ah b", buy=2_000_000, sell=2_200_000)],
                "purchase_count": 1,
                "sell_count": 1,
            },
            now=1_090.0,
        )

        printed: list[str] = []

        def fake_print(*args: object, **_: object) -> None:
            printed.append(" ".join(str(a) for a in args))

        with patch("builtins.print", side_effect=fake_print):
            metrics.print_overview(now=1_100.0)

        text = "\n".join(printed)
        self.assertIn("Session", text)
        self.assertIn("Past 1 min", text)
        # Session has 2 purchases; window (last 60s from t=1100) only pass 2.
        self.assertIn("purchases: 2", text)
        self.assertIn("purchases: 1", text)

    def test_print_overview_handles_empty_session(self) -> None:
        metrics = ArmorArbSessionMetricsManager(
            window_seconds=900.0,
            started_at=0.0,
        )
        printed: list[str] = []
        with patch(
            "builtins.print",
            side_effect=lambda *a, **k: printed.append(" ".join(map(str, a))),
        ):
            metrics.print_overview(now=10.0)
        text = "\n".join(printed)
        self.assertIn("avg purchases/loop: n/a", text)
        self.assertIn("avg profit margin: n/a", text)


if __name__ == "__main__":
    unittest.main()
