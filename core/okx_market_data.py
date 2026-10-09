"""Unauthenticated OKX Spot public market-data client for Paper-only venue labs.

This adapter only reads public ticker and candle endpoints. It has no account,
order, signing, or execution responsibilities.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import requests

_DEFAULT_BASE_URL = "https://openapi.okx.com"
_INTERVAL_TO_OKX = {
    "1m": "1m",
    "3m": "3m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1H",
    "2h": "2H",
    "4h": "4H",
}
_INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
}


class OKXMarketDataError(RuntimeError):
    """Raised when an OKX public market-data request fails."""


def to_okx_inst_id(symbol: str) -> str:
    """Convert the bot's BTCUSDT form to OKX's BTC-USDT Spot instrument ID."""
    normalized = str(symbol or "").strip().upper()
    if normalized.endswith("USDT") and "-" not in normalized:
        return f"{normalized[:-4]}-USDT"
    if "-" in normalized:
        return normalized
    raise ValueError(f"Unsupported OKX Spot symbol format: {symbol}")


def from_okx_inst_id(inst_id: str) -> str:
    return str(inst_id or "").replace("-", "").upper()


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class OKXMarketDataClient:
    """Small unauthenticated OKX V5 Spot REST client."""

    base_url: str = _DEFAULT_BASE_URL
    timeout_seconds: float = 12.0
    user_agent: str = "ShadowTradingBot/Paper-OKXMarketData"

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = requests.get(
                f"{self.base_url.rstrip('/')}{path}",
                params=params,
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise OKXMarketDataError(str(exc)) from exc

        if response.status_code in {403, 429}:
            raise OKXMarketDataError(
                f"OKX HTTP {response.status_code} for {path}: {response.text[:300]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise OKXMarketDataError(
                f"OKX returned non-JSON HTTP {response.status_code} for {path}"
            ) from exc
        if response.status_code >= 400:
            raise OKXMarketDataError(
                f"OKX HTTP {response.status_code} for {path}: {payload}"
            )
        if not isinstance(payload, dict) or str(payload.get("code", "")) != "0":
            raise OKXMarketDataError(f"OKX API error for {path}: {payload}")
        return payload

    @staticmethod
    def _normalize_ticker(item: dict[str, Any]) -> dict[str, Any]:
        last = _float(item.get("last"))
        bid = _float(item.get("bidPx"), last) or last
        ask = _float(item.get("askPx"), last) or last
        open_24h = _float(item.get("open24h"))
        change = ((last - open_24h) / open_24h * 100.0) if open_24h > 0 else 0.0
        return {
            "symbol": from_okx_inst_id(item.get("instId", "")),
            "lastPrice": last,
            "bidPrice": bid,
            "askPrice": ask,
            "volume": _float(item.get("vol24h")),
            "quoteVolume": _float(item.get("volCcy24h")),
            "priceChangePercent": change,
            "highPrice": _float(item.get("high24h")),
            "lowPrice": _float(item.get("low24h")),
            "market_data_source": "OKX",
        }

    def fetch_tickers(self, symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
        wanted = {str(symbol).upper() for symbol in symbols}
        if not wanted:
            return {}
        payload = self._get("/api/v5/market/tickers", {"instType": "SPOT"})
        rows = payload.get("data") or []
        result: dict[str, dict[str, Any]] = {}
        for item in rows:
            if not isinstance(item, dict):
                continue
            symbol = from_okx_inst_id(item.get("instId", ""))
            if symbol in wanted:
                result[symbol] = self._normalize_ticker(item)
        return result

    def fetch_klines(
        self,
        symbol: str,
        interval: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        interval_key = str(interval)
        bar = _INTERVAL_TO_OKX.get(interval_key)
        if bar is None:
            raise ValueError(f"Unsupported OKX interval: {interval}")
        bounded_limit = max(1, min(int(limit), 300))
        inst_id = to_okx_inst_id(symbol)
        payload = self._get(
            "/api/v5/market/candles",
            {"instId": inst_id, "bar": bar, "limit": str(bounded_limit)},
        )
        rows = payload.get("data") or []
        normalized: list[dict[str, Any]] = []
        interval_ms = _INTERVAL_MS[interval_key]
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            try:
                open_time = int(row[0])
                open_price = float(row[1])
                high_price = float(row[2])
                low_price = float(row[3])
                close_price = float(row[4])
                volume = float(row[5])
            except (TypeError, ValueError):
                continue
            confirm = str(row[8]) == "1" if len(row) > 8 else False
            normalized.append({
                "open_time": open_time,
                "close_time": open_time + interval_ms - 1,
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
                "quote_volume": _float(row[7] if len(row) > 7 else 0.0),
                "is_closed": confirm,
                "market_data_source": "OKX",
                "market_data_transport": "REST_COLD_START",
            })
        normalized.sort(key=lambda item: int(item["open_time"]))
        return normalized


__all__ = [
    "OKXMarketDataClient",
    "OKXMarketDataError",
    "from_okx_inst_id",
    "to_okx_inst_id",
]
