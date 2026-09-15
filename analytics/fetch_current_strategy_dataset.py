"""Build research data for the CURRENT dual_mode_strategy replay.

Research-only utility. It does not import or alter trading runtime code.

The current strategy needs closed 5m/15m/1h/4h candles. To avoid four
independent Binance histories drifting apart, this utility downloads one
5m history and deterministically resamples it into the higher timeframes.
"""
from __future__ import annotations

import argparse
import io
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

PUBLIC_BASE_URL = "https://data.binance.vision/data/spot/daily/klines"
KLINE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_asset_volume", "number_of_trades",
    "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore",
]


def read_daily_zip(symbol: str, day: datetime) -> pd.DataFrame | None:
    date_text = day.strftime("%Y-%m-%d")
    filename = f"{symbol}-5m-{date_text}.zip"
    url = f"{PUBLIC_BASE_URL}/{symbol}/5m/{filename}"
    try:
        response = requests.get(url, timeout=30)
    except requests.RequestException as exc:
        raise RuntimeError(f"Binance public archive request failed for {url}: {exc}") from exc
    if response.status_code == 404:
        return None
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if not csv_names:
            raise RuntimeError(f"No CSV found in {url}")
        with archive.open(csv_names[0]) as handle:
            df = pd.read_csv(handle, header=None, names=KLINE_COLUMNS)
    return df


def fetch_5m(symbol: str, candles: int) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    days_needed = candles // 288 + 3
    for offset in range(days_needed):
        frame = read_daily_zip(symbol, day - timedelta(days=offset))
        if frame is not None and not frame.empty:
            rows.append(frame)
        combined_count = sum(len(item) for item in rows)
        if combined_count >= candles:
            break
    if not rows:
        raise RuntimeError(f"No Binance public kline archive data returned for {symbol}")

    df = pd.concat(rows, ignore_index=True)
    raw_time = pd.to_numeric(df["open_time"], errors="coerce")
    # Spot archive timestamps are microseconds from 2025-01-01 onward.
    unit = "us" if raw_time.dropna().median() > 10_000_000_000_000 else "ms"
    df["timestamp"] = pd.to_datetime(raw_time, unit=unit, utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return (
        df[["timestamp", "open", "high", "low", "close", "volume"]]
        .dropna()
        .drop_duplicates("timestamp")
        .sort_values("timestamp")
        .tail(candles)
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
