# Market Data Cadence Decision

Use 22 ticker symbols as two groups of 11, alternating every 30 seconds. Do not introduce a multi-minute delay between groups because SCALP must not wait for a universe refresh.

Cache 5m, 15m, 1h, and 4h independently according to timeframe freshness. Persist the cache under the Paper state directory. Allow bounded-stale data for diagnostics only; new Paper entries require fresh entry-critical data.
