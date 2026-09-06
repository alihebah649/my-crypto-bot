# Paper market-data cache

The Paper-only entrypoint now keeps a short-lived successful 24h ticker snapshot for 120 seconds.

- A fresh snapshot is reused without making another Binance REST request.
- When the snapshot expires, the existing Binance 418/429 guard remains authoritative.
- An expired snapshot is never used as fresh market data.
- If Binance remains blocked after the cache expires, the Paper engine stays fail-safe and produces no new market entries until fresh data is available.
- SCALP=65, SWING=80, Spot-only strategy, Trade Manager, Smart Hold/Recovery, and the Paper risk overlay are unchanged.
