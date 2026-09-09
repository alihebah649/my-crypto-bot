"""Runtime defaults loaded by Python before the application entrypoint."""

import os

# The bot consumes only public Spot market data. Binance documents
# data-api.binance.vision as the dedicated base endpoint for public market-data
# APIs, including klines and ticker endpoints. Keep an explicit Render
# BINANCE_REST_URL override available for controlled testing.
os.environ.setdefault("BINANCE_REST_URL", "https://data-api.binance.vision")
