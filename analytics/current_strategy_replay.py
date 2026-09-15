"""Offline replay harness for the CURRENT dual_mode_strategy.

Diagnostic/research tool only. It does not alter runtime trading logic.

Expected input files (not committed; data_warehouse is gitignored):
    {symbol}_5m.parquet
    {symbol}_15m.parquet
    {symbol}_1h.parquet
    {symbol}_4h.parquet

Each file must contain timestamp, open, high, low, close, volume.
The replay evaluates the existing dual_mode_strategy at closed 5m decision
points and compares the current entry decision with a research-only candidate:
    below EMA100 AND MTF net < +5 => candidate filtered

The candidate is deliberately NOT a production rule.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List

import pandas as pd

from dual_mode_strategy import score_symbol

REQUIRED_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}
TIMEFRAMES = ("5m", "15m", "1h", "4h")
CANDIDATE_MTF_MIN = 5


def load_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(path)
    df = pd.read_parquet(path).copy()
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {sorted(missing)}")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=list(REQUIRED_COLUMNS)).sort_values("timestamp")
    return df.drop_duplicates("timestamp").reset_index(drop=True)


def row_to_candle(row: pd.Series) -> dict:
    return {
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": float(row["volume"]),
    }


def candles_until(df: pd.DataFrame, ts: pd.Timestamp) -> List[dict]:
    # Replay at the close of a 5m candle. For the current strategy contract,
    # append a duplicate "forming" candle so score_symbol removes it and uses
    # the just-closed candle as the latest closed candle.
    closed = df[df["timestamp"] <= ts]
    candles = [row_to_candle(r) for _, r in closed.iterrows()]
    if candles:
        candles.append(dict(candles[-1]))
    return candles


def research_filter(result: dict) -> bool:
    """Return True when the research-only structural filter would reject BUY."""
    if result.get("trade_mode") != "SCALP" or result.get("scalp_signal") != "BUY":
        return False
    price = float(result.get("price", 0.0) or 0.0)
    ema = float(result.get("ema100", 0.0) or 0.0)
    mtf_net = int(result.get("mtf_net", 0) or 0)
    if price <= 0 or ema <= 0:
        return False
    return price < ema and mtf_net < CANDIDATE_MTF_MIN


def replay_symbol(symbol: str, data_dir: Path, min_history_15m: int = 105) -> pd.DataFrame:
    frames: Dict[str, pd.DataFrame] = {
        tf: load_frame(data_dir / f"{symbol}_{tf}.parquet") for tf in TIMEFRAMES
    }

    decisions = []
    five = frames["5m"]
    for idx in range(min_history_15m, len(five)):
        ts = five.iloc[idx]["timestamp"]
        five_closed = five.iloc[: idx + 1]
        # The 5m candle at ts is treated as the just-closed decision candle.
        # Higher timeframes are included only when their candle timestamp is
        # already <= ts; score_symbol itself removes the final supplied item.
        payload = {
            "5m": candles_until(five_closed, ts),
            "15m": candles_until(frames["15m"], ts),
            "1h": candles_until(frames["1h"], ts),
            "4h": candles_until(frames["4h"], ts),
        }
        result = score_symbol(
            symbol,
            {"lastPrice": str(float(five.iloc[idx]["close"]))},
            payload["15m"],
            payload["5m"],
            payload["1h"],
            payload["4h"],
        )
        if result.get("scalp_signal") == "BUY":
            decisions.append(
                {
                    "timestamp": ts.isoformat(),
                    "symbol": symbol,
                    "scalp_score": result.get("scalp_score", 0),
                    "trade_mode": result.get("trade_mode", "NONE"),
                    "price": result.get("price", 0),
                    "ema100": result.get("ema100", 0),
                    "price_vs_ema_pct": (
                        (float(result["price"]) - float(result["ema100"]))
                        / float(result["ema100"])
                        * 100.0
                        if float(result.get("ema100", 0) or 0) > 0
                        else 0.0
                    ),
                    "mtf_net": result.get("mtf_net", 0),
                    "trigger": result.get("pattern", "NEUTRAL"),
                    "pattern_confirmed": result.get("pattern_confirmed", False),
                    "recovery_trigger_count": result.get("scalp_recovery_trigger_count", 0),
                    "volume_ratio_5m": result.get("volume_ratio_5m", 0),
                    "rsi5m": result.get("rsi5m", 0),
                    "candidate_filtered": research_filter(result),
                }
            )

    return pd.DataFrame(decisions)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="+", help="symbols such as BTCUSDT ETHUSDT")
    parser.add_argument("--data-dir", default="data_warehouse")
    parser.add_argument("--output", default="research_database/current_strategy_replay.csv")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    all_rows = []
    for symbol in args.symbols:
        try:
            result = replay_symbol(symbol.upper(), data_dir)
        except (FileNotFoundError, ValueError) as exc:
            print(f"[SKIP] {symbol}: {exc}")
            continue
        print(f"[OK] {symbol}: {len(result)} current-strategy SCALP BUY decisions")
        all_rows.append(result)

    if not all_rows:
        print("[NO DATA] No replayable symbol had all four required timeframe datasets.")
        return 2

    report = pd.concat(all_rows, ignore_index=True)
    report.to_csv(output, index=False)

    scalp_buys = len(report)
    filtered = int(report["candidate_filtered"].sum())
    print(f"[SUMMARY] scalp_buys={scalp_buys} candidate_filtered={filtered}")
    if scalp_buys:
        print(f"[SUMMARY] filter_rate={filtered / scalp_buys * 100:.2f}%")
    print(f"[OUTPUT] {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
