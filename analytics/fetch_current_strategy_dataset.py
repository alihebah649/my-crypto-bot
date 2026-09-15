"""Build research data for the CURRENT dual_mode_strategy replay.

Research-only utility. It does not import or alter trading runtime code.

The current strategy needs closed 5m/15m/1h/4h candles. To avoid four
independent Binance histories drifting apart, this utility downloads one
5m history and deterministically resamples it into the higher timeframes.

Output is gitignored under data_warehouse by design.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd
import requests

# Binance can geo-restrict one REST hostname (for example api.binance.com
# returning HTTP 451) while alternate production API hostnames remain usable.
# Keep the fallback here research-only; runtime trading code is untouched.
BASE_URLS = (
    "https://api.binance.com/api/v3/klines",
    "https://api1.binance.com/api/v3/klines",
    "https://api2.binance.com/api/v3/klines",
    "https://api3.binance.com/api/v3/klines",
)
INTERVAL_MS = 5 * 60 * 1000
API_LIMIT = 1000


def fetch_batch(symbol: str, params: dict) -> list:
    failures = []
    for base_url in BASE_URLS:
        try:
            response = requests.get(base_url, params=params, timeout=20)
            if response.ok:
                batch = response.json()
                if isinstance(batch, list):
                    return batch
            failures.append(f"{base_url}: HTTP {response.status_code}")
        except requests.RequestException as exc:
            failures.append(f"{base_url}: {type(exc).__name__}: {exc}")
    raise RuntimeError(f"All Binance research endpoints failed for {symbol}: {' | '.join(failures)}")


def fetch_5m(symbol: str, candles: int, pause: float = 0.25) -> pd.DataFrame:
    rows = []
    end_time = int(time.time() * 1000)
    batches = (candles + API_LIMIT - 1) // API_LIMIT
    for _ in range(batches):
        params = {
            "symbol": symbol,
            "interval": "5m",
            "limit": min(API_LIMIT, candles - len(rows)),
            "endTime": end_time,
        }
        batch = fetch_batch(symbol, params)
        if not batch:
            break
        rows = batch + rows
        end_time = int(batch[0][0]) - 1
        if len(rows) >= candles:
            break
        time.sleep(pause)

    if not rows:
        raise RuntimeError(f"No Binance data returned for {symbol}")

    columns = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore",
    ]
    df = pd.DataFrame(rows, columns=columns)
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return (
        df[["timestamp", "open", "high", "low", "close", "volume"]]
        .dropna()
        .drop_duplicates("timestamp")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    work = df.set_index("timestamp")
    out = work.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    return out.dropna().reset_index()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbols", nargs="+", help="e.g. BTCUSDT ETHUSDT")
    parser.add_argument("--candles-5m", type=int, default=20000)
    parser.add_argument("--data-dir", default="data_warehouse")
    args = parser.parse_args()

    out = Path(args.data_dir)
    out.mkdir(parents=True, exist_ok=True)

    for symbol in args.symbols:
        symbol = symbol.upper()
        five = fetch_5m(symbol, args.candles_5m)
        datasets = {
            "5m": five,
            "15m": resample_ohlcv(five, "15min"),
            "1h": resample_ohlcv(five, "1h"),
            "4h": resample_ohlcv(five, "4h"),
        }
        for tf, frame in datasets.items():
            frame.to_parquet(out / f"{symbol}_{tf}.parquet", index=False, engine="pyarrow", compression="snappy")
            print(f"[OK] {symbol} {tf}: {len(frame)} candles")
        print(f"[OK] {symbol}: {five['timestamp'].min()} -> {five['timestamp'].max()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
