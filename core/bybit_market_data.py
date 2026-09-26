"""Bybit public Spot market-data client used only for Paper market data.

The client intentionally has no order, account, fee, or execution responsibilities.
It normalizes Bybit's V5 Spot payloads into the field shape expected by the
existing Binance-oriented Paper strategy code.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import requests


_INTERVAL_TO_BYBIT = {
    "1m": "1",
    "3m": "3",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "2h": "120",
    "4h": "240",
}


class BybitMarketDataError(RuntimeError):
    """Raised when a Bybit public market-data request is unsuccessful."""


@dataclass(frozen=True)
class BybitMarketDataClient:
    """Minimal unauthenticated Bybit V5 Spot market-data client."""

    base_url: str = "https://api.bybit.com"
    timeout_seconds: float = 12.0
    user_agent: str = "ShadowTradingBot/Paper-BybitMarketData"

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        try:
            response = requests.get(
                f"{self.base_url.rstrip('/')}{path}",
                params=params,
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as exc:
            raise BybitMarketDataError(str(exc)) from exc

        if response.status_code in {403, 429}:
            raise BybitMarketDataError(
                f"Bybit HTTP {response.status_code} for {path}: {response.text[:300]}"
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise BybitMarketDataError(
                f"Bybit returned non-JSON HTTP {response.status_code} for {path}"
            ) from exc

        if response.status_code >= 400:
            raise BybitMarketDataError(
                f"Bybit HTTP {response.status_code} for {path}: {payload}"
            )
        if not isinstance(payload, dict) or payload.get("retCode") != 0:
            raise BybitMarketDataError(
                f"Bybit API error for {path}: {payload}"
            )
        return payload

    @staticmethod
    def _as_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize_ticker(item: dict[str, Any]) -> dict[str, Any]:
        last = BybitMarketDataClient._as_float(item.get("lastPrice"))
        bid = BybitMarketDataClient._as_float(item.get("bid1Price"), last)
        ask = BybitMarketDataClient._as_float(item.get("ask1Price"), last)
        volume = BybitMarketDataClient._as_float(item.get("volume24h"))
        turnover = BybitMarketDataClient._as_float(item.get("turnover24h"))
        price_change_fraction = BybitMarketDataClient._as_float(item.get("price24hPcnt"))
        return {
            "symbol": str(item.get("symbol", "")).upper(),
            "lastPrice": last,
            "bidPrice": bid or last,
            "askPrice": ask or last,
            "volume": volume,
            "quoteVolume": turnover,
            "priceChangePercent": price_change_fraction * 100.0,
            "highPrice": BybitMarketDataClient._as_float(item.get("highPrice24h")),
            "lowPrice": BybitMarketDataClient._as_float(item.get("lowPrice24h")),
            "market_data_source": "BYBIT",
        }

    def fetch_tickers(self, symbols: Iterable[str]) -> dict[str, dict[str, Any]]:
        wanted = {str(symbol).upper() for symbol in symbols}
        if not wanted:
            return {}
        payload = self._get("/v5/market/tickers", {"category": "spot"})
        rows = ((payload.get("result") or {}).get("list") or [])
        result: dict[str, dict[str, Any]] = {}
        for item in rows:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol", "")).upper()
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
        bybit_interval = _INTERVAL_TO_BYBIT.get(interval_key)
        if bybit_interval is None:
            raise ValueError(f"Unsupported Bybit interval: {interval}")
        bounded_limit = max(1, min(int(limit), 1000))
        payload = self._get(
            "/v5/market/kline",
            {
                "category": "spot",
                "symbol": str(symbol).upper(),
                "interval": bybit_interval,
                "limit": bounded_limit,
            },
        )
        rows = ((payload.get("result") or {}).get("list") or [])
        interval_seconds = {
            "1m": 60,
            "3m": 180,
            "5m": 300,
            "15m": 900,
            "30m": 1800,
            "1h": 3600,
            "2h": 7200,
            "4h": 14400,
        }[interval_key]
        candles: list[dict[str, Any]] = []
        for row in reversed(rows):
            if not isinstance(row, list) or len(row) < 6:
                continue
            open_time = int(float(row[0]))
            candles.append(
                {
                    "open_time": open_time,
                    "open": self._as_float(row[1]),
                    "high": self._as_float(row[2]),
                    "low": self._as_float(row[3]),
                    "close": self._as_float(row[4]),
                    "volume": self._as_float(row[5]),
                    "close_time": open_time + interval_seconds * 1000 - 1,
                }
            )
        return candles
