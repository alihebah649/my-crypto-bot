"""Research-only walk-forward validation for SCALP breakout quality gates.

Does not alter runtime strategy code. Reads the replay CSV produced by the
exact breakout A/B research and evaluates candidate range/ATR thresholds using
rolling chronological train/test splits.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def evaluate(df: pd.DataFrame, threshold: float) -> dict[str, float | int]:
    x = df[df["range_to_atr5"] <= threshold]
    if x.empty:
        return {"n": 0, "win_rate_60m": float("nan"), "mean_return_60m": float("nan")}
    return {
        "n": int(len(x)),
        "win_rate_60m": float((x["future_return_60m_pct"] > 0).mean() * 100),
        "mean_return_60m": float(x["future_return_60m_pct"].mean()),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", type=Path)
    ap.add_argument("--folds", type=int, default=4)
    ap.add_argument("--test-fraction", type=float, default=0.25)
    args = ap.parse_args()

    df = pd.read_csv(args.csv, parse_dates=["decision_time"])
    df = df[
        (df["variant"] == "CURRENT")
        & (df["trigger"] == "BULLISH_BREAKOUT")
        & df["future_return_60m_pct"].notna()
        & df["range_to_atr5"].notna()
    ].sort_values("decision_time").reset_index(drop=True)

    if len(df) < args.folds * 8:
        raise SystemExit(f"Not enough breakout rows for {args.folds} folds: {len(df)}")

    thresholds = [0.90, 1.00, 1.10, 1.15, 1.20, 1.30, 1.50]
    rows: list[dict[str, object]] = []
    n = len(df)
    min_train = max(12, int(n * 0.30))
    test_size = max(6, int(n * args.test_fraction))

    for fold in range(args.folds):
        test_start = min_train + fold * test_size
        test_end = min(n, test_start + test_size)
        if test_end - test_start < 4:
            break
        train = df.iloc[:test_start]
        test = df.iloc[test_start:test_end]

        train_scores = []
        for t in thresholds:
            s = evaluate(train, t)
            train_scores.append((t, s["mean_return_60m"], s["win_rate_60m"], s["n"]))
        # Primary selection criterion is mean return, with win-rate as tie break.
        best_t = max(train_scores, key=lambda z: (z[1], z[2]))[0]
        out = evaluate(test, best_t)
        rows.append(
            {
                "fold": fold + 1,
                "train_end": str(train["decision_time"].iloc[-1]),
                "test_start": str(test["decision_time"].iloc[0]),
                "test_end": str(test["decision_time"].iloc[-1]),
                "selected_threshold": best_t,
                "test_n": out["n"],
                "test_win_rate_60m": out["win_rate_60m"],
                "test_mean_return_60m": out["mean_return_60m"],
            }
        )

    out_df = pd.DataFrame(rows)
    out_df.to_csv("research_database/breakout_gate_walk_forward.csv", index=False)
    print(out_df.to_string(index=False))
    if not out_df.empty:
        print("\nWALK_FORWARD_SUMMARY")
        print("folds:", len(out_df))
        print("median_test_win_rate_60m:", round(out_df.test_win_rate_60m.median(), 3))
        print("mean_test_return_60m:", round(out_df.test_mean_return_60m.mean(), 4))
        print("selected_thresholds:", sorted(out_df.selected_threshold.unique().tolist()))


if __name__ == "__main__":
    main()
