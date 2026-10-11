FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BINANCE_API_BASE=https://data-api.binance.vision \
    PORT=8080 \
    RELAY_SNAPSHOT_PATH=/data/latest-market-data.json

WORKDIR /app
COPY requirements.txt /tmp/relay-requirements.txt
RUN pip install --no-cache-dir -r /tmp/relay-requirements.txt
COPY tools /app/tools
COPY app.py /app/market_data_relay/app.py
COPY __init__.py /app/market_data_relay/__init__.py
RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8080
CMD ["python", "-m", "market_data_relay.app"]
