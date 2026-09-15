"""Research-only replay for 5m entry regime diagnostics.

This does not change the trading strategy. It replays the current strategy at
closed 5m decision points and records additional pre-entry 5m structure:
recent returns, candle range/body, distance to recent extremes, RSI slope,
volume ratio, and ATR-normalized movement. Forward MFE/MAE/returns are also
recorded so entry-regime features can be compared with outcomes.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dual_mode_strategy import calculate_atr, calculate_rsi, score_symbol

TIMEFRAME_MINUTES = {"5m": 5, "15m": 15, "1h": 60, "4h": 240}
FORWARD_HORIZONS_MIN = (15, 30, 60, 240)
REQUIRED_COLUMNS = {"timestamp", "open", "high", "low", "close", "volume"}


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
    return df.dropna(subset=list(REQUIRED_COLUMNS)).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def candle(row: pd.Series) -> dict:
    return {k: float(row[k]) for k in ("open", "high", "low", "close", "volume")}


def closed(df: pd.DataFrame, decision_time: pd.Timestamp, timeframe: str) -> list[dict]:
    duration = pd.Timedelta(minutes=TIMEFRAME_MINUTES[timeframe])
    part = df[df["timestamp"] + duration <= decision_time]
    rows = [candle(r) for _, r in part.iterrows()]
    if rows:
        rows.append(dict(rows[-1]))
    return rows


def forward(five: pd.DataFrame, decision_time: pd.Timestamp, entry: float) -> dict:
    out: dict = {}
    future = five[five["timestamp"] > decision_time]
    for minutes in FORWARD_HORIZONS_MIN:
        window = future[future["timestamp"] <= decision_time + pd.Timedelta(minutes=minutes)]
        key = f"{minutes}m"
        if window.empty:
            out[f"future_return_{key}_pct"] = None
            out[f"mfe_{key}_pct"] = None
            out[f"mae_{key}_pct"] = None
            continue
        out[f"future_return_{key}_pct"] = (float(window.iloc[-1]["close"]) / entry - 1.0) * 100.0
        out[f"mfe_{key}_pct"] = (float(window["high"].max()) / entry - 1.0) * 100.0
        out[f"mae_{key}_pct"] = (float(window["low"].min()) / entry - 1.0) * 100.0
    return out


def replay(symbol: str, data_dir: Path, max_decisions: int | None = None) -> pd.DataFrame:
    five = load_frame(data_dir / f"{symbol}_5m.parquet")
    fifteen = load_frame(data_dir / f"{symbol}_15m.parquet")
    one_h = load_frame(data_dir / f"{symbol}_1h.parquet")
    four_h = load_frame(data_dir / f"{symbol}_4h.parquet")

    rows = []
    start = 0
    if max_decisions is not None and max_decisions > 0:
        start = max(0, len(five) - max_decisions)

    for idx in range(start, len(five)):
        decision_time = five.iloc[idx]["timestamp"] + pd.Timedelta(minutes=5)
        c5 = closed(five, decision_time, "5m")
        c15 = closed(fifteen, decision_time, "15m")
        c1h = closed(one_h, decision_time, "1h")
        c4h = closed(four_h, decision_time, "4h")
        if len(c15) < 106 or len(c5) < 16 or len(c1h) < 2 or len(c4h) < 2:
            continue

        result = score_symbol(
            symbol,
            {"lastPrice": str(float(five.iloc[idx]["close"]))},
            c15, c5, c1h, c4h,
        )
        if result.get("scalp_signal") != "BUY":
            continue

        p = [x["close"] for x in c5[:-1]]
        v = [x["volume"] for x in c5[:-1]]
        rsi_now = calculate_rsi(p)
        rsi_prev = calculate_rsi(p[:-1]) if len(p) >= 16 else rsi_now
        atr5 = calculate_atr(c5[:-1], 14)
        atr15 = float(result.get("atr", 0.0) or 0.0)
        last = c5[-2]
        recent = p[-1]
        def pct(a: float, b: float) -> float:
            return (a / b - 1.0) * 100.0 if b else 0.0

        recent_high_6 = max(x["high"] for x in c5[-7:-1])
        recent_low_6 = min(x["low"] for x in c5[-7:-1])
        recent_high_12 = max(x["high"] for x in c5[-13:-1])
        recent_low_12 = min(x["low"] for x in c5[-13:-1])
        avg_vol = sum(v[-21:-1]) / 20.0 if len(v) >= 21 else 0.0
        body = abs(last["close"] - last["open"])
        full_range = max(last["high"] - last["low"], 1e-12)

        row = {
            "decision_time": decision_time.isoformat(),
            "symbol": symbol,
            "scalp_score": result.get("scalp_score", 0),
            "trade_mode": result.get("trade_mode", "NONE"),
            "price": float(result.get("price", recent) or recent),
            "mtf_net": result.get("mtf_net", 0),
            "trigger": result.get("pattern", "NEUTRAL"),
            "pattern_confirmed": bool(result.get("pattern_confirmed", False)),
            "volume_ratio_5m": result.get("volume_ratio_5m", 0),
            "rsi5m": result.get("rsi5m", 0),
            "rsi_slope_1bar": rsi_now - rsi_prev,
            "ret_5m_1bar_pct": pct(p[-1], p[-2]) if len(p) >= 2 else 0.0,
            "ret_5m_3bar_pct": pct(p[-1], p[-4]) if len(p) >= 4 else 0.0,
            "ret_5m_6bar_pct": pct(p[-1], p[-7]) if len(p) >= 7 else 0.0,
            "ret_5m_12bar_pct": pct(p[-1], p[-13]) if len(p) >= 13 else 0.0,
            "last_candle_body_pct": pct(last["close"], last["open"]),
            "last_candle_range_pct": pct(last["high"], last["low"]),
            "body_to_range": body / full_range,
            "range_to_atr5": (full_range / atr5) if atr5 > 0 else None,
            "atr5_pct": (atr5 / recent * 100.0) if recent > 0 else None,
            "atr15_pct": (atr15 / recent * 100.0) if recent > 0 else None,
            "dist_recent_high_6_pct": pct(recent, recent_high_6),
            "dist_recent_low_6_pct": pct(recent, recent_low_6),
            "dist_recent_high_12_pct": pct(recent, recent_high_12),
            "dist_recent_low_12_pct": pct(recent, recent_low_12),
            "volume_ratio_recalc": (last["volume"] / avg_vol) if avg_vol > 0 else None,
            "initial_stop_distance_pct": (2.0 * atr15 / recent * 100.0) if recent > 0 else None,
        }
        row.update(forward(five, decision_time, row["price"]))
        rows.append(row)

    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("symbol")
    parser.add_argument("--data-dir", default="data_warehouse")
    parser.add_argument("--max-decisions", type=int, default=1200)
    parser.add_argument("--output", default="research_database/regime_entry_replay.csv")
    args = parser.parse_args()

    report = replay(args.symbol.upper(), Path(args.data_dir), args.max_decisions)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(args.output, index=False)
    print(f"[OK] {args.symbol.upper()}: scalp_buys={len(report)}")
    if not report.empty:
        for horizon in ("15m", "30m", "60m", "240m"):
            r = pd.to_numeric(report[f"future_return_{horizon}_pct"], errors="coerce").dropna()
            mfe = pd.to_numeric(report[f"mfe_{horizon}_pct"], errors="coerce").dropna()
            mae = pd.to_numeric(report[f"mae_{horizon}_pct"], errors="coerce").dropna()
            print(f"[OUTCOME] {horizon}: return_mean={r.mean():.3f}% mfe_mean={mfe.mean():.3f}% mae_mean={mae.mean():.3f}%")
        print(f"[OUTPUT] {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
