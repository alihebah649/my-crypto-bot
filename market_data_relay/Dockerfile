FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BINANCE_API_BASE=https://data-api.binance.vision \
    PORT=8080 \
    RELAY_SNAPSHOT_PATH=/data/latest-market-data.json

WORKDIR /app
COPY market_data_relay/requirements.txt /tmp/relay-requirements.txt
RUN pip install --no-cache-dir -r /tmp/relay-requirements.txt
COPY tools /app/tools
COPY market_data_relay /app/market_data_relay
RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8080
CMD ["python", "-m", "market_data_relay.app"]
