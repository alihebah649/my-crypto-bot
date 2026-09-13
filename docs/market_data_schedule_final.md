# Market Data Scheduling

- Ticker universe: two groups of 11 symbols.
- Refresh cadence: Group A, then 30 seconds later Group B, then repeat.
- Short candle data (5m/15m): refresh only when due for a new closed-candle snapshot.
- Long candle data (1h/4h): refresh only when a new candle is due.
- Persist snapshots under the Paper state directory.
- Use bounded-stale data for diagnostics only; new Paper entries require fresh entry-critical data.
- No changes to strategy thresholds, indicators, risk, Smart Hold, Recovery, or exit policy.
