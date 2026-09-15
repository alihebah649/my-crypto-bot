"""Research-only threshold analysis over saved 5m regime replay outputs.

No trading logic is changed. This script compares RSI-floor candidates against
forward outcomes to identify a candidate entry-regime filter for later validation.
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd

RSI_FLOORS = (40.0, 42.0, 44.0, 45.0, 46.0, 48.0, 50.0)


def main() -> int:
    files = sorted(Path("research_database").glob("regime_*.csv"))
    files = [p for p in files if p.name != "regime_threshold_analysis.csv"]
    if not files:
        print("[NO DATA] no regime replay files")
        return 2
    frames = []
    for path in files:
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            print(f"[SKIP] {path}: {exc}")
            continue
        if not df.empty:
            frames.append(df)
    if not frames:
        print("[NO DATA] regime files are empty")
        return 2
    report = pd.concat(frames, ignore_index=True)
    report = report[pd.to_numeric(report.get("future_return_60m_pct"), errors="coerce").notna()].copy()
    report["rsi5m"] = pd.to_numeric(report["rsi5m"], errors="coerce")
    report["future_return_60m_pct"] = pd.to_numeric(report["future_return_60m_pct"], errors="coerce")
    report["mfe_60m_pct"] = pd.to_numeric(report["mfe_60m_pct"], errors="coerce")
    report["mae_60m_pct"] = pd.to_numeric(report["mae_60m_pct"], errors="coerce")
    report["scalp_score"] = pd.to_numeric(report["scalp_score"], errors="coerce")
    print(f"[SUMMARY] symbols={report['symbol'].nunique()} completed_entries={len(report)}")
    base_win = (report["future_return_60m_pct"] > 0).mean() * 100.0
    print(f"[BASELINE] win_rate_60m={base_win:.1f}% return_mean={report['future_return_60m_pct'].mean():.3f}%")
    rows = []
    for floor in RSI_FLOORS:
        subset = report[report["rsi5m"] >= floor]
        rejected = report[report["rsi5m"] < floor]
        if subset.empty:
            continue
        rows.append({
            "rsi_floor": floor,
            "retained": len(subset),
            "rejected": len(rejected),
            "retain_pct": len(subset) / len(report) * 100.0,
            "win_rate_60m_pct": (subset["future_return_60m_pct"] > 0).mean() * 100.0,
            "return_60m_mean_pct": subset["future_return_60m_pct"].mean(),
            "mfe_60m_mean_pct": subset["mfe_60m_pct"].mean(),
            "mae_60m_mean_pct": subset["mae_60m_pct"].mean(),
            "rejected_win_rate_60m_pct": (rejected["future_return_60m_pct"] > 0).mean() * 100.0 if not rejected.empty else None,
            "rejected_return_60m_mean_pct": rejected["future_return_60m_pct"].mean() if not rejected.empty else None,
        })
    out = pd.DataFrame(rows)
    print(out.to_string(index=False, float_format=lambda x: f"{x:.3f}"))
    Path("research_database").mkdir(parents=True, exist_ok=True)
    out.to_csv("research_database/regime_threshold_analysis.csv", index=False)
    print("[OUTPUT] research_database/regime_threshold_analysis.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
