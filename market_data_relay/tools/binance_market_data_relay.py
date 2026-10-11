#!/usr/bin/env python3
"""Fetch a bounded Binance Spot market snapshot for the 22-symbol paper universe."""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_URL = os.getenv("BINANCE_API_BASE", "https://api.binance.com")
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT", "ADAUSDT", "DOTUSDT",
    "NEARUSDT", "ARBUSDT", "OPUSDT", "RENDERUSDT", "BNBUSDT", "AVAXUSDT",
    "ALGOUSDT", "ATOMUSDT", "FETUSDT", "LTCUSDT", "XRPUSDT", "XLMUSDT",
    "HBARUSDT", "SUIUSDT", "BCHUSDT", "TRXUSDT",
]
INTERVALS = ("5m", "15m", "1h", "4h")
DEFAULT_LIMITS = {"5m": 300, "15m": 300, "1h": 200, "4h": 200}


class RelayError(RuntimeError):
    pass


def _request_json(path: str, params: dict[str, Any], *, attempts: int = 3) -> Any:
    query = urllib.parse.urlencode(
        {
            key: json.dumps(value, separators=(",", ":"))
            if isinstance(value, list)
            else value
            for key, value in params.items()
        }
    )
    url = f"{BASE_URL}{path}?{query}"
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "shadow-trading-bot-binance-relay/1.0"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 418:
                raise RelayError(
                    f"Binance returned 418 for {path}; refusing to retry a ban response"
                ) from exc
            if exc.code not in (429, 500, 502, 503, 504) or attempt >= attempts:
                body = exc.read().decode("utf-8", errors="replace")[:500]
                raise RelayError(
                    f"Binance HTTP {exc.code} for {path}: {body}"
                ) from exc
            retry_after = exc.headers.get("Retry-After")
            delay = min(float(retry_after or (5 * attempt)), 30.0)
            time.sleep(delay + random.uniform(0.0, 1.0))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt >= attempts:
                raise RelayError(f"Binance request failed for {path}: {exc}") from exc
            time.sleep(min(5.0 * attempt, 15.0))

    raise RelayError(f"Binance request failed for {path}: {last_error}")


def _candle(raw: list[Any]) -> dict[str, Any]:
    return {
        "open_time": int(raw[0]),
        "open": str(raw[1]),
        "high": str(raw[2]),
        "low": str(raw[3]),
        "close": str(raw[4]),
        "volume": str(raw[5]),
        "close_time": int(raw[6]),
        "quote_volume": str(raw[7]),
        "trade_count": int(raw[8]),
        "taker_buy_base_volume": str(raw[9]),
        "taker_buy_quote_volume": str(raw[10]),
    }


def _closed_klines(raw_rows: list[list[Any]], now_ms: int) -> list[dict[str, Any]]:
    return [_candle(row) for row in raw_rows if len(row) >= 11 and int(row[6]) < now_ms]


def build_snapshot(
    *,
    now_ms: int,
    ticker_rows: list[dict[str, Any]],
    candles: dict[str, dict[str, list[list[Any]]]],
    limits: dict[str, int] | None = None,
) -> dict[str, Any]:
    limits = limits or DEFAULT_LIMITS
    tickers = {str(row["symbol"]).upper(): row for row in ticker_rows}

    missing_tickers = [symbol for symbol in SYMBOLS if symbol not in tickers]
    if missing_tickers:
        raise RelayError(f"Ticker coverage incomplete: missing {','.join(missing_tickers)}")

    symbols: dict[str, Any] = {}
    for symbol in SYMBOLS:
        intervals: dict[str, Any] = {}
        for interval in INTERVALS:
            closed = _closed_klines(candles[symbol][interval], now_ms)
            minimum = min(100, limits[interval])
            if len(closed) < minimum:
                raise RelayError(
                    f"Insufficient closed klines {symbol} {interval}: {len(closed)} < {minimum}"
                )
            intervals[interval] = closed[-limits[interval]:]
        symbols[symbol] = {"ticker": tickers[symbol], "klines": intervals}

    return {
        "schema_version": 1,
        "generated_at": datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).isoformat(),
        "generated_at_ms": now_ms,
        "source": "binance_spot_public_rest",
        "symbol_count": len(SYMBOLS),
        "symbols": symbols,
    }


def fetch_snapshot() -> dict[str, Any]:
    now_ms = int(time.time() * 1000)
    ticker_rows = _request_json("/api/v3/ticker/24hr", {"symbols": SYMBOLS})
    if not isinstance(ticker_rows, list):
        raise RelayError("Unexpected ticker payload")

    candles: dict[str, dict[str, list[list[Any]]]] = {}
    for symbol in SYMBOLS:
        candles[symbol] = {}
        for interval in INTERVALS:
            candles[symbol][interval] = _request_json(
                "/api/v3/klines",
                {"symbol": symbol, "interval": interval, "limit": DEFAULT_LIMITS[interval]},
            )

    return build_snapshot(now_ms=now_ms, ticker_rows=ticker_rows, candles=candles)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/latest-market-data.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    snapshot = fetch_snapshot()
    output = Path(args.output)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "schema_version": snapshot["schema_version"],
                    "generated_at": snapshot["generated_at"],
                    "symbol_count": snapshot["symbol_count"],
                    "symbols": list(snapshot["symbols"]),
                },
                indent=2,
            )
        )
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    tmp.write_text(json.dumps(snapshot, separators=(",", ":")), encoding="utf-8")
    tmp.replace(output)

    print(
        f"BINANCE_RELAY_OK generated_at={snapshot['generated_at']} "
        f"symbols={snapshot['symbol_count']} output={output}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RelayError as exc:
        print(f"BINANCE_RELAY_ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
