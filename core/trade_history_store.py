from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


@dataclass(slots=True)
class TradeHistoryRecord:
    """Normalized trade record shared by PAPER/LIVE/BACKTEST history."""

    trade_id: str
    symbol: str
    source: str
    side: str
    order_id: str = ""
    price: float = 0.0
    quantity: float = 0.0
    quote_quantity: float = 0.0
    commission: float = 0.0
    commission_asset: str = ""
    is_buyer: bool = False
    is_maker: bool = False
    trade_time: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class TradeHistoryStore:
    """
    Single-file persistent trade history.

    The code lives in the repository, while the runtime JSON file should live
    under data/ (which is intentionally git-ignored) so private account/trade
    history is not committed to a public repository.
    """

    def __init__(self, path: str | Path = "data/trade_history.json") -> None:
        self.path = Path(path)

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(payload, dict) and isinstance(payload.get("trades"), list):
            return payload["trades"]
        if isinstance(payload, list):
            return payload
        return []

    def _save(self, records: Iterable[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        payload = {
            "schema_version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "trades": list(records),
        }
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def upsert(self, record: TradeHistoryRecord | dict[str, Any]) -> None:
        item = asdict(record) if isinstance(record, TradeHistoryRecord) else dict(record)
        trade_id = str(item.get("trade_id", ""))
        if not trade_id:
            raise ValueError("trade_id is required")

        records = self._load()
        for index, existing in enumerate(records):
            if str(existing.get("trade_id", "")) == trade_id:
                records[index] = item
                self._save(records)
                return
        records.append(item)
        self._save(records)

    def all(self) -> list[dict[str, Any]]:
        return self._load()

    def count(self) -> int:
        return len(self._load())

    def sync_binance_trades(
        self,
        client: Any,
        symbols: Iterable[str],
        *,
        source: str = "LIVE",
        limit: int = 1000,
    ) -> int:
        """Pull account trades from Binance and merge them into the same file."""
        added_or_updated = 0
        for symbol in symbols:
            rows = client.get_my_trades(symbol=symbol, limit=limit)
            for row in rows:
                record = TradeHistoryRecord(
                    trade_id=str(row.get("id", "")),
                    symbol=str(row.get("symbol", symbol)),
                    source=source,
                    side="BUY" if bool(row.get("isBuyer")) else "SELL",
                    order_id=str(row.get("orderId", "")),
                    price=float(row.get("price", 0.0) or 0.0),
                    quantity=float(row.get("qty", 0.0) or 0.0),
                    quote_quantity=float(row.get("quoteQty", 0.0) or 0.0),
                    commission=float(row.get("commission", 0.0) or 0.0),
                    commission_asset=str(row.get("commissionAsset", "")),
                    is_buyer=bool(row.get("isBuyer", False)),
                    is_maker=bool(row.get("isMaker", False)),
                    trade_time=(
                        datetime.fromtimestamp(
                            int(row.get("time", 0)) / 1000,
                            tz=timezone.utc,
                        ).isoformat()
                        if row.get("time")
                        else ""
                    ),
                    raw=row,
                )
                self.upsert(record)
                added_or_updated += 1
        return added_or_updated
