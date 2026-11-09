"""
Unit tests for gated armor-arb purchase JSON logging.

Casual: buffer snags until the session clears the >10 bar, then write for real.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ah_price.armor_arb.purchase_log_manager import ArmorArbPurchaseLogManager
from ah_price.armor_arb.session_metrics_manager import ArmorArbPurchaseMetric


def _metric(
    index: int,
    *,
    buy: int = 1_000_000,
    sell: int = 1_100_000,
    timestamp: float = 1_700_000_000.0,
    checked_prices: tuple[dict, ...] | None = None,
) -> ArmorArbPurchaseMetric:
    profit = sell - buy
    prices = checked_prices
    if prices is None:
        prices = (
            {"slot": 0, "price": buy, "price_raw": f"${buy}", "ok": True},
            {
                "slot": 1,
                "price": sell + 100_000,
                "price_raw": f"${sell + 100_000}",
                "ok": True,
            },
        )
    return ArmorArbPurchaseMetric(
        timestamp=timestamp + index,
        pass_number=1,
        kind="planned",
        query=f"/ah item-{index}",
        buy_coins=buy,
        sell_coins=sell,
        profit_coins=profit,
        margin=profit / buy,
        checked_prices=prices,
    )


class ArmorArbPurchaseLogManagerTests(unittest.TestCase):
    """JSON logging stays buffered until session purchases exceed the floor."""

    def test_stays_buffered_at_or_below_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            manager = ArmorArbPurchaseLogManager(
                log_dir=log_dir,
                min_session_purchases=10,
                session_id="test_session",
                started_at=1_700_000_000.0,
            )
            # Exactly 10 buys → still buffered (need >10).
            status = manager.record_purchases([_metric(i) for i in range(10)])
            self.assertFalse(status["logging_enabled"])
            self.assertFalse(status.get("just_unlocked", False))
            self.assertEqual(manager.buffered_count, 10)
            self.assertEqual(list(log_dir.iterdir()), [])
            self.assertIsNone(manager.read_log())

    def test_unlocks_and_flushes_after_eleventh_purchase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            manager = ArmorArbPurchaseLogManager(
                log_dir=log_dir,
                min_session_purchases=10,
                session_id="test_session",
                started_at=1_700_000_000.0,
            )
            manager.record_purchases([_metric(i) for i in range(10)])
            status = manager.record_purchases([_metric(10)])
            self.assertTrue(status["just_unlocked"])
            self.assertTrue(status["logging_enabled"])
            self.assertEqual(status["newly_written"], 11)
            self.assertEqual(manager.buffered_count, 0)

            payload = manager.read_log()
            self.assertIsNotNone(payload)
            assert payload is not None
            self.assertEqual(payload["session_id"], "test_session")
            self.assertEqual(payload["min_session_purchases"], 10)
            self.assertEqual(len(payload["purchases"]), 11)
            first = payload["purchases"][0]
            self.assertEqual(first["query"], "/ah item-0")
            self.assertEqual(first["buy_coins"], 1_000_000)
            self.assertEqual(first["sell_coins"], 1_100_000)
            self.assertEqual(first["profit_coins"], 100_000)
            self.assertIn("timestamp", first)
            self.assertEqual(
                first["checked_prices"],
                [
                    {
                        "slot": 0,
                        "price": 1_000_000,
                        "price_raw": "$1000000",
                        "ok": True,
                    },
                    {
                        "slot": 1,
                        "price": 1_200_000,
                        "price_raw": "$1200000",
                        "ok": True,
                    },
                ],
            )

    def test_appends_after_unlock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            manager = ArmorArbPurchaseLogManager(
                log_dir=log_dir,
                min_session_purchases=2,
                session_id="append_session",
                started_at=1_700_000_000.0,
            )
            manager.record_purchases([_metric(0), _metric(1), _metric(2)])
            self.assertTrue(manager.logging_enabled)
            status = manager.record_purchases([_metric(3, buy=5_000_000, sell=5_200_000)])
            self.assertEqual(status["newly_written"], 1)
            self.assertFalse(status.get("just_unlocked", False))

            payload = manager.read_log()
            assert payload is not None
            self.assertEqual(len(payload["purchases"]), 4)
            self.assertEqual(payload["purchases"][-1]["buy_coins"], 5_000_000)
            self.assertEqual(payload["purchases"][-1]["profit_coins"], 200_000)

    def test_empty_record_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = ArmorArbPurchaseLogManager(
                log_dir=Path(tmp),
                min_session_purchases=10,
                session_id="empty",
            )
            status = manager.record_purchases([])
            self.assertFalse(status["logging_enabled"])
            self.assertEqual(status["newly_written"], 0)


if __name__ == "__main__":
    unittest.main()
