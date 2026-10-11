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

- A small always-on Docker host outside Render, with persistent storage at
  `/data` and outbound TLS/WebSocket connectivity to Binance.
- For Railway, use the native Python buildpack with Root Directory `market_data_relay`,
  build command `pip install -r requirements.txt`, and start command `python app.py`.
  The non-default `Dockerfile.container` is only for manual Docker deployments.
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

## Required Render environment variables (MAIN only)

After the relay's public TLS endpoint has passed the checks below, set these on
`my-crypto-bot` only:

- `BINANCE_MARKET_DATA_RELAY_WS_URL=wss://YOUR-RELAY-HOST/stream`
- `BINANCE_MARKET_DATA_RELAY_TOKEN=<same secret as RELAY_SHARED_TOKEN>`

Do not set these on Bybit Lab or OKX Lab. Those services must continue using
their own venue feeds. Once MAIN is confirmed using the relay, remove
`BINANCE_MARKET_DATA_SNAPSHOT_URL` from MAIN: the relay supplies its own
historical bootstrap, so GitHub is no longer in the startup market-data path.

When the relay URL is configured, the Bot's Binance adapter fails closed for
missing relay tickers/klines; it does not fall back to direct Binance REST or a
direct Binance WebSocket. A relay outage should result in stale/incomplete data
and no unsafe new entries, not a burst of requests from Render.

## Acceptance checks before switching MAIN

1. `GET /healthz` reports `snapshot_ready=true`, `upstream_connected=true`,
   and `upstream_healthy=true`.
2. An unauthenticated `/snapshot` request is rejected with HTTP 401.
3. An authenticated `/snapshot` request returns all 22 symbols and all four
   intervals with closed historical candles.
4. An authenticated WebSocket connection to `/stream` first receives a
   `type=snapshot` bootstrap frame, then continuous Binance ticker/kline event
   frames; no secrets appear in URLs or logs.
5. Set the relay URL/token on MAIN only, restart once, and confirm Render health
   shows `transport=EXTERNAL_RELAY`, 22/22 data completeness, 88/88 kline
   coverage, a healthy feed, and no Binance REST endpoint requests or direct
   `stream.binance.com` connection from the Render runtime.
6. Confirm Paper-only invariants and strategy thresholds remain unchanged.

The relay code is deployable, but it is not active until it is deployed on an
external host and the two Render environment variables are configured.
