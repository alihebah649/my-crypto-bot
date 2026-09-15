"""Research-only A/B replay for the current SCALP lane.

Variant A: current strategy unchanged.
Variant B: suppress BULLISH_BREAKOUT at the pattern layer, so its +30 scalp
points and reversal confirmation disappear exactly as they would in a genuine
strategy variant. No runtime trading code is changed.
"""
from __future__ import annotations

from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dual_mode_strategy as dms
import analytics.regime_entry_replay as rr

SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT", "FETUSDT")


def replay_variant(symbol: str, data_dir: Path, suppress_breakout: bool) -> pd.DataFrame:
    original = dms.bullish_pattern

    if suppress_breakout:
        def suppressed(candles):
            found, name, confirmed = original(candles)
            if name == "BULLISH_BREAKOUT":
                return False, "NEUTRAL", False
            return found, name, confirmed
        dms.bullish_pattern = suppressed
        rr.score_symbol = dms.score_symbol
    try:
        frame = rr.replay(symbol, data_dir, max_decisions=1200)
    finally:
        dms.bullish_pattern = original
        rr.score_symbol = dms.score_symbol
    if frame.empty:
        return frame.assign(variant="NO_BREAKOUT" if suppress_breakout else "CURRENT")
    frame = frame.copy()
    frame["variant"] = "NO_BREAKOUT" if suppress_breakout else "CURRENT"
    return frame


def summary(df: pd.DataFrame, variant: str) -> str:
    x = df[(df["variant"] == variant) & pd.to_numeric(df["future_return_60m_pct"], errors="coerce").notna()].copy()
    if x.empty:
        return f"[SUMMARY] {variant}: n=0"
    ret = pd.to_numeric(x["future_return_60m_pct"], errors="coerce")
    mfe = pd.to_numeric(x["mfe_60m_pct"], errors="coerce")
    mae = pd.to_numeric(x["mae_60m_pct"], errors="coerce")
    return (
        f"[SUMMARY] {variant}: n={len(x)} "
        f"win_rate_60m={(ret > 0).mean()*100:.2f}% "
        f"return_mean_60m={ret.mean():.4f}% "
        f"mfe_mean_60m={mfe.mean():.4f}% "
        f"mae_mean_60m={mae.mean():.4f}%"
    )


def main() -> int:
    data_dir = Path("data_warehouse")
    out_dir = Path("research_database")
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for symbol in SYMBOLS:
        current = replay_variant(symbol, data_dir, False)
        no_breakout = replay_variant(symbol, data_dir, True)
        print(f"[OK] {symbol}: current={len(current)} no_breakout={len(no_breakout)}")
        if not current.empty:
            frames.append(current)
        if not no_breakout.empty:
            frames.append(no_breakout)
    if not frames:
        print("[NO DATA] no replayable entries")
        return 2
    report = pd.concat(frames, ignore_index=True)
    report.to_csv(out_dir / "breakout_ab_replay.csv", index=False)
    print(summary(report, "CURRENT"))
    print(summary(report, "NO_BREAKOUT"))
    print("[OUTPUT] research_database/breakout_ab_replay.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
