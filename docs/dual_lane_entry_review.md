# Dual-lane entry review

PR #29 correctly identifies the symbol-only entry gate as a problem and adds independent SCALP/SWING orchestration.

Before merge, one edge case must be fixed:

- Existing SCALP + new SCALP/SWING simultaneous BUY must open **SWING only**.
- Existing SWING + simultaneous BUY must open **SCALP only**.
- Existing SCALP + existing SWING + simultaneous BUY must open **neither**.
- No existing positions + simultaneous BUY must open **both**.

The current wrapper builds both requested modes directly from `scalp_signal` / `swing_signal` and does not filter already-active lanes inside the opening loop. Therefore the current implementation can duplicate an already-open lane when both signals are BUY.

This review intentionally blocks merge until that edge case is covered and the production orchestration is corrected. Strategy thresholds remain SCALP 65 / SWING 80; Trade Manager is unchanged.
