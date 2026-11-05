# External Binance live market-data relay

## Purpose

Run this service on a host **outside Render**. It maintains one upstream
Binance Spot combined WebSocket and relays live ticker/kline messages to the
Paper Trading services. GitHub remains the code repository and CI runner; it is
not in the live market-data path. The relay never submits orders.

The service supports the existing 22-symbol universe and 5m/15m/1h/4h candles.
REST is used to seed or repair historical continuity; normal live data comes
from WebSocket. If Binance REST replies HTTP 418, the relay does not rapidly
retry that response.

## Requirements

- An always-on service outside Render, with persistent storage at `/data` and
  outbound TLS/WebSocket connectivity to Binance.
- For Railway, use the native Python buildpack with Root Directory
  `market_data_relay`, automatic dependency installation from `requirements.txt`,
  and start command `python app.py`. The non-default `Dockerfile.container` is
  only for manual Docker deployments.
- A DNS name and TLS termination (for example, Caddy or the host's managed HTTPS
  ingress) so the downstream endpoint is `wss://.../stream`.
- One randomly generated shared bearer token of at least 32 characters.

Do not expose the service over plain public `ws://`. Do not put the bearer
secret in the URL, source code, GitHub, or a public log. Stream and snapshot
endpoints require `Authorization: Bearer <token>`.

## Docker build/run

From the repository root:

```sh
docker build -f Dockerfile.container -t binance-market-data-relay market_data_relay
mkdir -p ./relay-data
docker run -d --name binance-market-data-relay --restart unless-stopped \
  -p 127.0.0.1:8080:8080 -v "$PWD/relay-data:/data" \
  -e RELAY_SHARED_TOKEN='REPLACE_WITH_A_RANDOM_64_HEX_CHARACTER_SECRET' \
  -e BINANCE_API_BASE='https://data-api.binance.vision' \
  -e BINANCE_WS_BASE='wss://data-stream.binance.vision/stream' \
  -e RELAY_SNAPSHOT_PATH='/data/latest-market-data.json' \
  binance-market-data-relay
```

Example Caddy site (replace the hostname and ensure DNS points to the VPS):

```caddy
relay.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

Caddy supports WebSocket upgrades through `reverse_proxy`. Persistent `/data`
storage allows the service to warm from a local snapshot after restart instead
of depending on GitHub releases.

## Active production configuration (MAIN only)

The relay is now deployed on Railway and configured on the MAIN Render service:

- `BINANCE_MARKET_DATA_RELAY_WS_URL=wss://binance-live-relay-production-production.up.railway.app/stream`
- `BINANCE_MARKET_DATA_RELAY_TOKEN=<stored securely in Render; same secret as RELAY_SHARED_TOKEN>`
- `BINANCE_MARKET_DATA_SNAPSHOT_URL` is cleared on MAIN, so GitHub is no longer in the startup market-data path.

Keep the bearer value in service secrets only; never commit or echo it in logs.
Do not set the relay variables on Bybit Lab or OKX Lab. Those services continue
to use their own venue feeds.

When the relay URL is configured, the Bot's Binance adapter fails closed for
missing relay tickers/klines; it does not fall back to direct Binance REST or a
direct Binance WebSocket. A relay outage should result in stale/incomplete data
and no unsafe new entries, not a burst of requests from Render.

## Production validation record

The deployment was switched on MAIN only after the external service started
successfully. The following behavior has been observed in production:

1. Railway's health check receives HTTP 200, and its upstream WebSocket connects
   with 110 streams (22 ticker streams plus 88 kline streams).
2. MAIN reports `transport=EXTERNAL_RELAY`, `connected=True`, `healthy=True`,
   `kline_coverage=88/88`, and `ticker_coverage=22/22` after the initial live
   stream warms. The first health sample can briefly show zero live coverage;
   bootstrap candles are intentionally not mislabelled as live data.
3. MAIN's market-cycle audit reports `tickers=22/22`, `15m=22/22`,
   `5m=22/22`, `scored=22/22`, `missing=NONE`.
4. The Render Binance request instrumentation reports `total=0` in the sampled
   metrics window, consistent with Binance live data being routed through the
   external relay. No HTTP 418 appeared in the sampled MAIN logs after the
   switch; continue monitoring rather than treating this as a guarantee against
   future upstream restrictions.
5. The relay's scheduled REST history refresh completed successfully after
   approximately 15 minutes, keeping repairs off Render. Earlier, the default
   Binance WebSocket host returned HTTP 451 from the Railway region. Setting
   `BINANCE_WS_BASE=wss://data-stream.binance.vision/stream` restored the upstream
   connection; retain this variable in Railway's service configuration.
6. The bearer authorization helper is covered by relay tests. The WebSocket
   endpoint's successful HTTP 101 upgrade was recorded in Railway logs.
7. Paper-only mode remains enabled, strategy thresholds remain `SCALP=65` and
   `SWING=80`, and Legacy remains the execution authority. No live orders were
   enabled by this deployment.
