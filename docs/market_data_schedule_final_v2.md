# Market Data Schedule

Ticker data is refreshed in two 11-symbol groups with a 30-second gap between groups. This is intentionally short to preserve timely SCALP opportunities.

5m and 15m candles are refreshed only when their cache expires / a new closed candle is due. 1h and 4h candles are refreshed only when their respective new candles are due.

Persistent snapshots are reused after restart. Bounded stale data may support diagnostics, but it cannot authorize a new Paper entry.
