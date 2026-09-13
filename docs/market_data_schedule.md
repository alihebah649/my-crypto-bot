# Market data freshness schedule

The Paper Trading market-data layer is designed to minimize Binance REST pressure without making SCALP wait on an entire universe refresh.

## Ticker

The 22-symbol universe is split into two deterministic groups of 11 symbols.
The groups alternate every 30 seconds:

- t=00s: Group A (11 symbols)
- t=30s: Group B (11 symbols)
- t=60s: Group A
- t=90s: Group B

The cache merges both groups, so strategy reads see the newest available snapshot for every symbol instead of waiting for the second group.

Ticker data has a short freshness window and a bounded stale window for diagnostics. Stale ticker data is never entry-safe.

## Candles

Candles are refreshed by timeframe freshness rather than by every strategy cycle:

- 5m: refresh only when its freshness window expires / a new closed candle is due.
- 15m: refresh on its own cadence.
- 1h: refresh when a new 1h candle is due.
- 4h: refresh when a new 4h candle is due.

The cache is persistent under the Paper state directory so a process restart does not automatically discard valid market snapshots.

## Safety

A cache hit never creates an exchange request. A Binance 429/418 response activates the upstream guard. Existing bounded-stale snapshots may remain available for diagnostics, but new Paper entries require fresh entry-critical market data.

No strategy score, SCALP threshold, SWING threshold, indicator, risk sizing, Smart Hold, Recovery, or exit rule is changed by this layer.
