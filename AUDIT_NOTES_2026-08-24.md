# Stability audit checkpoint — 2026-08-24

## Findings addressed

- Swing scoring now supports healthy bullish continuation without requiring an oversold/lower-Bollinger pullback.
- Swing threshold remains 80/100.
- Scalp threshold remains 65/100 and its reversal gate remains unchanged.
- A realized loss below the configured daily loss limit no longer freezes the Paper Trading engine by default.
- `/` diagnostics expose the unified BUY threshold plus lane-specific thresholds.
- Explicit bullish-continuation Swing regression coverage was added.

## Remaining blockers

- GitHub Actions must pass on the audit branch.
- Risk period boundary/reset still needs explicit validation: the loss ledger uses UTC while the report uses Asia/Aden, and risk locks need period-boundary behavior.
- Exchange-specific filters/reconciliation remain live-trading blockers and are intentionally not being changed during this stabilization pass.
