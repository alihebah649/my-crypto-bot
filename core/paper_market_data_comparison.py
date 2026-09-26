"""Diagnostic comparison of Paper outcomes by market-data source."""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def compare_paper_outcomes_by_market_data_source(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    unknown: list[Mapping[str, Any]] = []

    for record in records:
        source = str(
            record.get("market_data_source")
            or (record.get("strategy") or {}).get("market_data_source")
            or "UNKNOWN"
        ).upper()
        if source in {"BINANCE", "BYBIT"}:
            grouped[source].append(record)
        else:
            unknown.append(record)

    sources: dict[str, dict[str, Any]] = {}
    for source in ("BINANCE", "BYBIT"):
        rows = grouped.get(source, [])
        wins = [row for row in rows if _number(row.get("realized_pnl")) > 0]
        losses = [row for row in rows if _number(row.get("realized_pnl")) < 0]
        net = sum(_number(row.get("realized_pnl")) for row in rows)
        avg = net / len(rows) if rows else 0.0
        sources[source] = {
            "records": len(rows),
            "wins": len(wins),
            "losses": len(losses),
            "flat": len(rows) - len(wins) - len(losses),
            "win_rate_percent": round(len(wins) / len(rows) * 100.0, 2) if rows else None,
            "net_pnl": round(net, 6),
            "avg_pnl_per_trade": round(avg, 6) if rows else None,
            "avg_fee": round(
                sum(_number(row.get("fees")) for row in rows) / len(rows), 6
            ) if rows else None,
            "avg_stop_distance_percent": round(
                sum(
                    _number((row.get("entry_forensics") or {}).get("stop_distance_percent"))
                    for row in rows
                    if (row.get("entry_forensics") or {}).get("stop_distance_valid") is True
                )
                / max(
                    1,
                    sum(
                        1
                        for row in rows
                        if (row.get("entry_forensics") or {}).get("stop_distance_valid") is True
                    ),
                ),
                6,
            ) if rows else None,
        }

    return {
        "schema_version": 1,
        "comparison_type": "PAPER_OUTCOME_BY_MARKET_DATA_SOURCE",
        "total_records": sum(len(rows) for rows in grouped.values()) + len(unknown),
        "unknown_source_records": len(unknown),
        "sources": sources,
    }


__all__ = ["compare_paper_outcomes_by_market_data_source"]
