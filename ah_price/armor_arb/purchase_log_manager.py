"""
Timestamped JSON purchase log for overnight armor-arb sessions.

Casual: remember every snag once the night gets interesting enough.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ah_price.armor_arb.session_metrics_manager import ArmorArbPurchaseMetric
from ah_price.config import (
    ARMOR_ARB_PURCHASE_LOG_DIR,
    ARMOR_ARB_PURCHASE_LOG_MIN_SESSION_PURCHASES,
)


class ArmorArbPurchaseLogManager:
    """
    Buffer purchases in memory, then persist once the session clears a floor.

    Casual: don't bother writing a log file until we've snagged >10 times.
    Until the session purchase count exceeds ``min_session_purchases``,
    events stay in a memory buffer and nothing is written. Crossing the
    threshold creates a session JSON file, flushes the buffer, and every
    later purchase appends immediately. Designed so unit tests can inject
    a temp directory and a low threshold without touching production paths.
    """

    def __init__(
        self,
        *,
        log_dir: Path | None = None,
        min_session_purchases: int = ARMOR_ARB_PURCHASE_LOG_MIN_SESSION_PURCHASES,
        session_id: str | None = None,
        started_at: float | None = None,
    ) -> None:
        if min_session_purchases < 0:
            raise ValueError("min_session_purchases must be non-negative")
        self._log_dir = Path(log_dir or ARMOR_ARB_PURCHASE_LOG_DIR)
        self._min_session_purchases = int(min_session_purchases)
        self._started_at = float(time.time() if started_at is None else started_at)
        self._session_id = session_id or self._default_session_id(self._started_at)
        self._buffer: list[dict[str, Any]] = []
        self._persisted_count = 0
        self._logging_enabled = False
        self._log_path: Path | None = None

    @property
    def min_session_purchases(self) -> int:
        return self._min_session_purchases

    @property
    def logging_enabled(self) -> bool:
        return self._logging_enabled

    @property
    def log_path(self) -> Path | None:
        return self._log_path

    @property
    def buffered_count(self) -> int:
        return len(self._buffer)

    @property
    def session_purchase_count(self) -> int:
        return self._persisted_count + len(self._buffer)

    def record_purchases(
        self,
        purchases: list[ArmorArbPurchaseMetric] | tuple[ArmorArbPurchaseMetric, ...],
    ) -> dict[str, Any]:
        """
        Accept new purchase metrics; maybe unlock + flush the JSON log.

        Casual: stash buys; once we clear the bar, start writing for real.
        Returns a small status dict (enabled / path / newly_written) so the
        loop coordinator can print a one-liner when logging unlocks.
        """
        if not purchases:
            return {
                "logging_enabled": self._logging_enabled,
                "log_path": str(self._log_path) if self._log_path else None,
                "newly_written": 0,
                "session_purchase_count": self.session_purchase_count,
            }

        for purchase in purchases:
            self._buffer.append(self._purchase_to_record(purchase))

        newly_written = 0
        just_unlocked = False
        if not self._logging_enabled:
            if self.session_purchase_count > self._min_session_purchases:
                just_unlocked = True
                newly_written = self._enable_and_flush()
        else:
            newly_written = self._append_buffer()

        return {
            "logging_enabled": self._logging_enabled,
            "log_path": str(self._log_path) if self._log_path else None,
            "newly_written": newly_written,
            "just_unlocked": just_unlocked,
            "session_purchase_count": self.session_purchase_count,
        }

    def read_log(self) -> dict[str, Any] | None:
        """
        Load the on-disk session log if logging has been unlocked.

        Casual: peek at the JSON file we wrote (tests use this a lot).
        """
        if self._log_path is None or not self._log_path.is_file():
            return None
        with self._log_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _enable_and_flush(self) -> int:
        """
        Create the session file and dump everything buffered so far.

        Casual: unlock real logging and dump the backlog in one shot.
        """
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._log_dir / f"purchases_{self._session_id}.json"
        payload = {
            "session_id": self._session_id,
            "started_at": self._iso_utc(self._started_at),
            "min_session_purchases": self._min_session_purchases,
            "purchases": list(self._buffer),
        }
        self._write_payload(payload)
        written = len(self._buffer)
        self._persisted_count += written
        self._buffer.clear()
        self._logging_enabled = True
        return written

    def _append_buffer(self) -> int:
        """
        Append newly buffered purchases onto an already-open session file.

        Casual: logging is on — just tack the new snags onto the JSON.
        """
        if not self._buffer:
            return 0
        if self._log_path is None:
            raise RuntimeError("logging enabled but log_path is missing")

        payload = self.read_log()
        if payload is None:
            # File vanished mid-session — recreate from the current buffer.
            return self._enable_and_flush()

        purchases = list(payload.get("purchases") or [])
        purchases.extend(self._buffer)
        payload["purchases"] = purchases
        self._write_payload(payload)
        written = len(self._buffer)
        self._persisted_count += written
        self._buffer.clear()
        return written

    def _write_payload(self, payload: dict[str, Any]) -> None:
        """Atomically-ish write JSON (temp then replace) for crash safety."""
        assert self._log_path is not None
        tmp_path = self._log_path.with_suffix(self._log_path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        tmp_path.replace(self._log_path)

    @staticmethod
    def _purchase_to_record(purchase: ArmorArbPurchaseMetric) -> dict[str, Any]:
        """Turn a metric dataclass into a JSON-friendly dict."""
        return {
            "timestamp": ArmorArbPurchaseLogManager._iso_utc(purchase.timestamp),
            "pass": purchase.pass_number,
            "kind": purchase.kind,
            "query": purchase.query,
            "buy_coins": purchase.buy_coins,
            "sell_coins": purchase.sell_coins,
            "profit_coins": purchase.profit_coins,
            "margin": purchase.margin,
            # First-row OCR snapshot at buy time (partial on early-buy).
            "checked_prices": [
                dict(entry) for entry in purchase.checked_prices
            ],
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
