"""
Unit tests for armor-arb order-book JSONL logging.

Casual: every price check should land as one line in the session file.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ah_price.armor_arb.order_book_log_manager import ArmorArbOrderBookLogManager


def _item_row(
    *,
    query: str = "/ah netherite boots",
    purchased: bool = False,
    skip_reason: str | None = None,
    early_stopped: bool = False,
    prices: list[dict] | None = None,
    opportunity: dict | None = None,
    sell_coins: int | None = None,
) -> dict:
    if prices is None:
        prices = [
            {
                "slot": 0,
                "price": 6_000_000,
                "price_raw": "$6M",
                "ok": True,
            },
            {
                "slot": 1,
                "price": 6_500_000,
                "price_raw": "$6.5M",
                "ok": True,
            },
        ]
    sell = None
    if sell_coins is not None:
        sell = {"sold": True, "decision": {"sell_coins": sell_coins}}
    return {
        "query": query,
        "purchased": purchased,
        "skip_reason": skip_reason,
        "opportunity": opportunity,
        "sell": sell,
        "compare": {
            "listings": prices,
            "early_stopped": early_stopped,
            "elapsed_ms": 123.4,
            "ok_count": len([p for p in prices if p.get("ok")]),
            "slot_count": len(prices),
            "planned_slot_count": 9,
            "first_price": prices[0]["price"] if prices else None,
            "cheapest_price": min(
                (int(p["price"]) for p in prices if p.get("ok") and p.get("price")),
                default=None,
            ),
        },
    }


class ArmorArbOrderBookLogManagerTests(unittest.TestCase):
    """Order-book JSONL writes one record per item price check."""

    def test_disabled_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = ArmorArbOrderBookLogManager(
                log_dir=Path(tmp),
                enabled=False,
                session_id="disabled",
                started_at=1_700_000_000.0,
            )
            status = manager.record_pass_report(
                pass_number=1,
                kind="planned",
                summary={"items": [_item_row()]},
            )
            self.assertFalse(status["enabled"])
            self.assertEqual(status["newly_written"], 0)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_records_each_item_in_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            manager = ArmorArbOrderBookLogManager(
                log_dir=log_dir,
                enabled=True,
                session_id="books_session",
                started_at=1_700_000_000.0,
            )
            status = manager.record_pass_report(
                pass_number=2,
                kind="planned",
                summary={
                    "items": [
                        _item_row(query="/ah netherite boots", skip_reason=None),
                        _item_row(
                            query="/ah netherite helm",
                            purchased=True,
                            opportunity={
                                "slot": 0,
                                "price": 5_500_000,
                                "market_price": 5_900_000,
                                "discount_coins": 400_000,
                            },
                            sell_coins=5_800_000,
                        ),
                    ]
                },
                timestamp=1_700_000_100.0,
            )
            self.assertTrue(status["enabled"])
            self.assertEqual(status["newly_written"], 2)
            self.assertEqual(manager.record_count, 2)
            self.assertTrue(manager.log_path is not None)
            assert manager.log_path is not None
            self.assertEqual(manager.log_path.name, "order_books_books_session.jsonl")

            records = manager.read_records()
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["query"], "/ah netherite boots")
            self.assertFalse(records[0]["purchased"])
            self.assertEqual(records[0]["pass"], 2)
            self.assertEqual(records[0]["kind"], "planned")
            self.assertEqual(
                records[0]["prices"],
                [
                    {
                        "slot": 0,
                        "price": 6_000_000,
                        "price_raw": "$6M",
                        "ok": True,
                    },
                    {
                        "slot": 1,
                        "price": 6_500_000,
                        "price_raw": "$6.5M",
                        "ok": True,
                    },
                ],
            )
            self.assertTrue(records[1]["purchased"])
            self.assertEqual(records[1]["sell_coins"], 5_800_000)
            self.assertEqual(records[1]["opportunity"]["discount_coins"], 400_000)

    def test_appends_across_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = ArmorArbOrderBookLogManager(
                log_dir=Path(tmp),
                enabled=True,
                session_id="append",
                started_at=1_700_000_000.0,
            )
            manager.record_pass_report(
                pass_number=1,
                kind="planned",
                summary={"items": [_item_row(query="/ah a")]},
            )
            manager.record_pass_report(
                pass_number=1,
                kind="recheck_bought",
                summary={"items": [_item_row(query="/ah a", early_stopped=True)]},
            )
            records = manager.read_records()
            self.assertEqual(len(records), 2)
            self.assertEqual(records[1]["kind"], "recheck_bought")
            self.assertTrue(records[1]["early_stopped"])

    def test_empty_items_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = ArmorArbOrderBookLogManager(
                log_dir=Path(tmp),
                enabled=True,
                session_id="empty",
            )
            status = manager.record_pass_report(
                pass_number=1,
                kind="planned",
                summary={"items": []},
            )
            self.assertEqual(status["newly_written"], 0)
            self.assertEqual(manager.read_records(), [])


if __name__ == "__main__":
    unittest.main()
