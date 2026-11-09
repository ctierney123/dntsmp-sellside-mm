"""
Timestamped JSONL order-book log for every armor-arb price check.

Casual: remember every first-row book we skimmed, buys and skips alike.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ah_price.config import (
    ARMOR_ARB_ORDER_BOOK_LOG_DIR,
    ARMOR_ARB_ORDER_BOOK_LOG_ENABLED,
)


class ArmorArbOrderBookLogManager:
    """
    Append one JSONL record per AH first-row price check.

    Casual: every time we OCR a book, drop a line in the session log file.
    Unlike the purchase log (gated until >N buys), this writes from the
    first check when enabled. Uses newline-delimited JSON so overnight
    sessions can append thousands of scans without rewriting a giant
    pretty-printed array each time. Unit tests inject a temp directory.
    """

    def __init__(
        self,
        *,
        log_dir: Path | None = None,
        enabled: bool = ARMOR_ARB_ORDER_BOOK_LOG_ENABLED,
        session_id: str | None = None,
        started_at: float | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._log_dir = Path(log_dir or ARMOR_ARB_ORDER_BOOK_LOG_DIR)
        self._started_at = float(time.time() if started_at is None else started_at)
        self._session_id = session_id or self._default_session_id(self._started_at)
        self._log_path: Path | None = None
        self._record_count = 0
        if self._enabled:
            self._ensure_log_path()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def log_path(self) -> Path | None:
        return self._log_path

    @property
    def record_count(self) -> int:
        return self._record_count

    def record_pass_report(
        self,
        *,
        pass_number: int,
        kind: str,
        summary: dict[str, Any],
        timestamp: float | None = None,
    ) -> dict[str, Any]:
        """
        Log every item row from one planned pass or recheck summary.

        Casual: walk the pass report and stash each book's prices.
        Returns a small status dict (enabled / path / newly_written) so the
        loop coordinator can print a one-liner when useful.
        """
        if not self._enabled:
            return {
                "enabled": False,
                "log_path": None,
                "newly_written": 0,
                "record_count": self._record_count,
            }

        now = float(time.time() if timestamp is None else timestamp)
        items = list(summary.get("items") or [])
        newly_written = 0
        for row in items:
            record = self._item_row_to_record(
                row,
                pass_number=pass_number,
                kind=kind,
                timestamp=now,
            )
            self._append_record(record)
            newly_written += 1

        return {
            "enabled": True,
            "log_path": str(self._log_path) if self._log_path else None,
            "newly_written": newly_written,
            "record_count": self._record_count,
        }

    def read_records(self) -> list[dict[str, Any]]:
        """
        Load every JSONL record from the session file (tests / tooling).

        Casual: read the whole order-book log back as a list of dicts.
        """
        if self._log_path is None or not self._log_path.is_file():
            return []
        records: list[dict[str, Any]] = []
        with self._log_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                records.append(json.loads(text))
        return records

    def _ensure_log_path(self) -> None:
        """
        Create the session JSONL path (and parent dir) once logging is on.

        Casual: pick the filename and make sure the folder exists.
        """
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._log_dir / f"order_books_{self._session_id}.jsonl"

    def _append_record(self, record: dict[str, Any]) -> None:
        """
        Append one JSON object as a single line.

        Casual: tack this book snapshot onto the end of the file.
        """
        if self._log_path is None:
            self._ensure_log_path()
        assert self._log_path is not None
        with self._log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")))
            handle.write("\n")
        self._record_count += 1

    @staticmethod
    def _item_row_to_record(
        row: dict[str, Any],
        *,
        pass_number: int,
        kind: str,
        timestamp: float,
    ) -> dict[str, Any]:
        """
        Turn one armor-arb item report into a JSON-friendly order-book row.

        Casual: flatten compare + buy/skip outcome into one log line.
        Keeps the OCR'd slot prices (partial on early-buy), plus whether we
        bought / skipped and any undercut opportunity we considered.
        """
        compare = row.get("compare") or {}
        listings = compare.get("listings") or []
        opportunity = row.get("opportunity")
        sell = row.get("sell") or {}
        sell_decision = sell.get("decision") or {}

        return {
            "timestamp": ArmorArbOrderBookLogManager._iso_utc(timestamp),
            "pass": pass_number,
            "kind": kind,
            "query": str(row.get("query") or ""),
            "purchased": bool(row.get("purchased")),
            "skip_reason": row.get("skip_reason"),
            "early_stopped": bool(compare.get("early_stopped")),
            "elapsed_ms": compare.get("elapsed_ms"),
            "ok_count": compare.get("ok_count"),
            "slot_count": compare.get("slot_count"),
            "planned_slot_count": compare.get("planned_slot_count"),
            "first_price": compare.get("first_price"),
            "cheapest_price": compare.get("cheapest_price"),
            "opportunity": (
                dict(opportunity) if isinstance(opportunity, dict) else None
            ),
            "sell_coins": sell_decision.get("sell_coins"),
            "prices": [
                ArmorArbOrderBookLogManager._listing_to_price_entry(listing)
                for listing in listings
            ],
        }

    @staticmethod
    def _listing_to_price_entry(listing: dict[str, Any]) -> dict[str, Any]:
        """Keep the useful OCR fields from one slot listing."""
        return {
            "slot": listing.get("slot"),
            "price": listing.get("price"),
            "price_raw": listing.get("price_raw"),
            "ok": bool(listing.get("ok")),
        }

    @staticmethod
    def _default_session_id(started_at: float) -> str:
        """UTC timestamp slug used in the log filename."""
        return datetime.fromtimestamp(started_at, tz=timezone.utc).strftime(
            "%Y%m%dT%H%M%SZ"
        )

    @staticmethod
    def _iso_utc(epoch_seconds: float) -> str:
        """Format an epoch float as an ISO-8601 UTC timestamp."""
        return (
            datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
