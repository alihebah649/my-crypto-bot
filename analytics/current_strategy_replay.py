"""Offline replay harness for the CURRENT dual_mode_strategy.

Diagnostic/research tool only. It does not alter runtime trading logic.

Expected input files (not committed; data_warehouse is gitignored):
    {symbol}_5m.parquet
    {symbol}_15m.parquet
    {symbol}_1h.parquet
    {symbol}_4h.parquet

The replay evaluates the existing dual_mode_strategy at CLOSED 5m decision
points and compares the current entry decision with a research-only candidate:
    below EMA100 AND MTF net < +5 => candidate filtered

For each BUY it also records forward price behavior at 15m/30m/60m/240m.
These are diagnostic outcome measurements, not simulated Trade Manager exits.
The candidate is deliberately NOT a production rule.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dual_mode_strategy import score_symbol, calculate_atr

REQUIRED_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}
TIMEFRAMES = ("5m", "15m", "1h", "4h")
CANDIDATE_MTF_MIN = 5
TIMEFRAME_MINUTES = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
FORWARD_HORIZONS_MIN = (15, 30, 60, 240)


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


def closed_candles_at(df: pd.DataFrame, decision_time: pd.Timestamp, timeframe: str) -> List[dict]:
    duration = pd.Timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
    closed = df[df["timestamp"] + duration <= decision_time]
    candles = [row_to_candle(r) for _, r in closed.iterrows()]
    if candles:
        candles.append(dict(candles[-1]))
    return candles


def research_filter(result: dict) -> bool:
    if result.get("trade_mode") != "SCALP" or result.get("scalp_signal") != "BUY":
        return False
    price = float(result.get("price", 0.0) or 0.0)
    ema = float(result.get("ema100", 0.0) or 0.0)
    mtf_net = int(result.get("mtf_net", 0) or 0)
    if price <= 0 or ema <= 0:
        return False
    return price < ema and mtf_net < CANDIDATE_MTF_MIN


def forward_outcomes(five: pd.DataFrame, decision_time: pd.Timestamp, entry: float) -> dict:
    out: dict = {}
    future = five[five["timestamp"] > decision_time]
    for minutes in FORWARD_HORIZONS_MIN:
        horizon_end = decision_time + pd.Timedelta(minutes=minutes)
        window = future[future["timestamp"] <= horizon_end]
        key = f"{minutes}m"
        if window.empty:
            out[f"future_return_{key}_pct"] = None
            out[f"mfe_{key}_pct"] = None
            out[f"mae_{key}_pct"] = None
            out[f"bars_{key}"] = 0
            continue
        last_close = float(window.iloc[-1]["close"])
        out[f"future_return_{key}_pct"] = (last_close / entry - 1.0) * 100.0
        out[f"mfe_{key}_pct"] = (float(window["high"].max()) / entry - 1.0) * 100.0
        out[f"mae_{key}_pct"] = (float(window["low"].min()) / entry - 1.0) * 100.0
        out[f"bars_{key}"] = int(len(window))
    return out


def replay_symbol(symbol: str, data_dir: Path, min_history_15m: int = 105) -> pd.DataFrame:
    frames: Dict[str, pd.DataFrame] = {tf: load_frame(data_dir / f"{symbol}_{tf}.parquet") for tf in TIMEFRAMES}
    decisions = []
    five = frames["5m"]
    for idx in range(len(five)):
        decision_time = five.iloc[idx]["timestamp"] + pd.Timedelta(minutes=5)
        closed_15m = frames["15m"][frames["15m"]["timestamp"] + pd.Timedelta(minutes=15) <= decision_time]
        if len(closed_15m) < min_history_15m:
            continue
        payload = {
            "5m": closed_candles_at(five, decision_time, "5m"),
            "15m": closed_candles_at(frames["15m"], decision_time, "15m"),
            "1h": closed_candles_at(frames["1h"], decision_time, "1h"),
            "4h": closed_candles_at(frames["4h"], decision_time, "4h"),
        }
        if any(len(payload[tf]) < 2 for tf in TIMEFRAMES):
            continue
        result = score_symbol(symbol, {"lastPrice": str(float(five.iloc[idx]["close"]))}, payload["15m"], payload["5m"], payload["1h"], payload["4h"])
        if result.get("scalp_signal") != "BUY":
            continue
        entry = float(result.get("price", five.iloc[idx]["close"]) or five.iloc[idx]["close"])
        atr15 = float(result.get("atr", 0.0) or 0.0)
        atr5 = float(result.get("atr5", 0.0) or 0.0)
        if atr15 <= 0:
            atr15 = calculate_atr(payload["15m"][:-1])
        stop_price = entry - (2.0 * atr15) if atr15 > 0 else None
        stop_distance_pct = ((entry - stop_price) / entry * 100.0) if stop_price and stop_price > 0 else None
        row = {
            "decision_time": decision_time.isoformat(),
            "symbol": symbol,
            "scalp_score": result.get("scalp_score", 0),
            "trade_mode": result.get("trade_mode", "NONE"),
            "price": entry,
            "ema100": result.get("ema100", 0),
            "price_vs_ema_pct": ((entry - float(result["ema100"])) / float(result["ema100"]) * 100.0 if float(result.get("ema100", 0) or 0) > 0 else 0.0),
            "mtf_net": result.get("mtf_net", 0),
            "trigger": result.get("pattern", "NEUTRAL"),
            "pattern_confirmed": result.get("pattern_confirmed", False),
            "recovery_trigger_count": result.get("scalp_recovery_trigger_count", 0),
            "volume_ratio_5m": result.get("volume_ratio_5m", 0),
            "rsi5m": result.get("rsi5m", 0),
            "atr15m": atr15,
            "atr5m": atr5,
            "initial_stop_price_2x_atr15m": stop_price,
            "initial_stop_distance_pct": stop_distance_pct,
            "candidate_filtered": research_filter(result),
        }
        row.update(forward_outcomes(five, decision_time, entry))
        for minutes in FORWARD_HORIZONS_MIN:
            key = f"{minutes}m"
            mae = row.get(f"mae_{key}_pct")
            if mae is None or stop_distance_pct in (None, 0):
                row[f"mae_{key}_in_stop_R"] = None
                row[f"stop_hit_{key}"] = None
            else:
                row[f"mae_{key}_in_stop_R"] = abs(float(mae)) / float(stop_distance_pct)
                row[f"stop_hit_{key}"] = bool(float(mae) <= -float(stop_distance_pct))
        decisions.append(row)
    return pd.DataFrame(decisions)


def print_group_summary(report: pd.DataFrame, label: str) -> None:
    subset = report[report["candidate_filtered"] == (label == "filtered")]
    if subset.empty:
        print(f"[OUTCOME] {label}: n=0")
        return
    vals = []
    for col in ("future_return_60m_pct", "future_return_240m_pct", "mfe_60m_pct", "mae_60m_pct", "mae_60m_in_stop_R"):
        series = pd.to_numeric(subset[col], errors="coerce").dropna()
        vals.append(f"{col}={series.mean():.3f}" if not series.empty else f"{col}=NA")
    stop_hit = subset["stop_hit_60m"].dropna()
    vals.append(f"stop_hit_60m_rate={stop_hit.mean()*100:.1f}%" if not stop_hit.empty else "stop_hit_60m_rate=NA")
    print(f"[OUTCOME] {label}: n={len(subset)} " + " ".join(vals))


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
        if not result.empty:
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
        print_group_summary(report, "filtered")
        print_group_summary(report, "retained")
    print(f"[OUTPUT] {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
