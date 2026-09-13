# Market Data Scheduling Decision

The 22-symbol ticker universe is split into two groups of 11 and refreshed in alternating 30-second slots. A multi-minute gap is intentionally avoided so SCALP symbols do not wait for the other half of the universe.

Timeframe caches are independent: 5m and 15m refresh on their short-candle cadence, while 1h and 4h refresh only when a new candle is due. The persistent cache survives process restarts.

Stale snapshots may be used for diagnostics, but stale entry-critical data is never safe for a new Paper entry.
