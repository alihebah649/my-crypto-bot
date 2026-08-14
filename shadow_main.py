"""Shadow Trading Bot application entry point.

Architecture boundary:
    market data -> indicators/strategy -> Trade Manager -> core execution adapter

``shadow_main.py`` is intentionally an orchestrator.  It no longer owns a
second portfolio, risk engine, position store, stop-loss engine, or execution
implementation.  Those responsibilities belong to Trade Manager/Core.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from typing import Dict

import pandas as pd
import requests
import websockets
from flask import Flask, jsonify

from trade_manager.shadow_integration import ShadowTradeManagerRuntime

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("ShadowMain")

INITIAL_CASH = float(os.getenv("PAPER_INITIAL_CASH", "1000.0"))
FEE_RATE = float(os.getenv("PAPER_FEE_RATE", "0.001"))
TIMEFRAME_SECONDS = 60
TRADE_MANAGER_STATE_DIR = os.getenv("TRADE_MANAGER_STATE_DIR", "data/trade_manager")

ISLAMIC_ASSETS = [
    "BTC-USD",
    "ETH-USD",
    "BNB-USD",
    "SOL-USD",
    "AVAX-USD",
    "LINK-USD",
    "MATIC-USD",
]

app = Flask(__name__)
runtime = ShadowTradeManagerRuntime(
    initial_cash=INITIAL_CASH,
    fee_rate=FEE_RATE,
    state_dir=TRADE_MANAGER_STATE_DIR,
)

current_prices: Dict[str, float] = {}
market_state: Dict[str, Dict[str, float]] = {}
resampler_history: Dict[str, list[dict]] = {}
resampler_current: Dict[str, dict] = {}


def process_tick(symbol: str, price: float, volume: float, timestamp: float) -> None:
    bucket = int(timestamp // TIMEFRAME_SECONDS) * TIMEFRAME_SECONDS
    candle = resampler_current.get(symbol)

    if candle is None or candle["ts"] != bucket:
        if candle is not None:
            history = resampler_history.setdefault(symbol, [])
            history.append(candle)
            del history[:-200]
        resampler_current[symbol] = {
            "ts": bucket,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": volume,
        }
        return

    candle["high"] = max(candle["high"], price)
    candle["low"] = min(candle["low"], price)
    candle["close"] = price
    candle["volume"] += volume


def calculate_indicators(symbol: str):
    history = resampler_history.get(symbol, [])
    if len(history) < 101:
        return None, None, None

    df = pd.DataFrame(history)
    ema100 = float(df["close"].ewm(span=100, adjust=False).mean().iloc[-1])

    delta = df["close"].diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    ema_up = up.ewm(alpha=1 / 14, adjust=False).mean()
    ema_down = down.ewm(alpha=1 / 14, adjust=False).mean()
    rs = ema_up / ema_down.replace(0, pd.NA)
    rsi = float((100 - (100 / (1 + rs))).iloc[-1])

    previous_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - previous_close).abs(),
            (df["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = float(tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
    return ema100, rsi, atr


def evaluate_signal(price: float, ema100, rsi) -> str:
    if ema100 is None or rsi is None or pd.isna(ema100) or pd.isna(rsi):
        return "HOLD"
    score = 0
    if price > ema100:
        score += 50
    if rsi < 40:
        score += 30
    if rsi > 70:
        score -= 50
    if score >= 80:
        return "BUY"
    if score <= -50:
        return "SELL"
    return "HOLD"


TELEGRAM_TOKEN = os.getenv("TOKEN") or os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "199325566")


def send_telegram_message(message: str) -> None:
    if not TELEGRAM_TOKEN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=5,
        )
    except Exception:
        logger.exception("Telegram notification failed")


@app.get("/")
def home():
    positions = runtime.facade.get_open_positions()
    metrics = runtime.facade.get_metrics()
    return jsonify(
        {
            "status": "healthy",
            "mode": "PAPER",
            "entrypoint": "shadow_main.py",
            "trade_manager": "modular_parts_1_8",
            "state_dir": TRADE_MANAGER_STATE_DIR,
            "open_positions": len(positions),
            "symbols": [p.symbol for p in positions],
            "metrics": getattr(metrics, "__dict__", str(metrics)),
            "last_update": time.time(),
        }
    ), 200


@app.get("/trade-manager/positions")
def positions():
    return jsonify(
        [
            {
                "position_id": p.position_id,
                "symbol": p.symbol,
                "status": p.status.name,
                "quantity": p.quantity,
                "entry_price": p.entry_price,
                "current_price": p.current_price,
                "stop_loss": p.stop_loss,
                "take_profit": p.take_profit,
                "realized_pnl": p.realized_pnl,
                "fees": p.total_fees,
            }
            for p in runtime.repository.get_all()
        ]
    ), 200


async def start_shadow_engine() -> None:
    send_telegram_message("Shadow Trading Bot started: Trade Manager is now the lifecycle boundary.")

    while True:
        try:
            async with websockets.connect(
                "wss://ws-feed.exchange.coinbase.com",
                ping_interval=20,
            ) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "type": "subscribe",
                            "product_ids": ISLAMIC_ASSETS,
                            "channels": ["ticker"],
                        }
                    )
                )

                async for raw in ws:
                    data = json.loads(raw)
                    if data.get("type") != "ticker":
                        continue

                    symbol = data.get("product_id")
                    if symbol not in ISLAMIC_ASSETS:
                        continue

                    price = float(data.get("price", 0.0))
                    if price <= 0:
                        continue

                    current_prices[symbol] = price
                    timestamp = time.time()
                    last_size = float(data.get("last_size", 0.0) or 0.0)
                    volume_24h = float(data.get("volume_24h", 0.0) or 0.0)
                    volume_usdt = volume_24h * price
                    bid = float(data.get("best_bid", price) or price)
                    ask = float(data.get("best_ask", price) or price)
                    spread_percent = ((ask - bid) / price * 100.0) if price > 0 else 0.0

                    process_tick(symbol, price, last_size, timestamp)
                    ema100, rsi, atr = calculate_indicators(symbol)

                    runtime.update_market(
                        symbol,
                        price=price,
                        bid=bid,
                        ask=ask,
                        spread_percent=spread_percent,
                        atr=float(atr or 0.0),
                        volume_usdt=volume_usdt,
                        volatility=0.0,
                        ema100=float(ema100 or 0.0),
                    )
                    market_state[symbol] = {
                        "price": price,
                        "ema100": float(ema100 or 0.0),
                        "rsi": float(rsi or 0.0),
                        "atr": float(atr or 0.0),
                    }

                    runtime.evaluate_position(symbol)

                    if ema100 is None or rsi is None or atr is None or atr <= 0:
                        continue

                    signal = evaluate_signal(price, ema100, rsi)
                    has_position = runtime.controller.has_position(symbol)

                    if signal == "BUY" and not has_position:
                        stop_loss = price - (atr * 2.0)
                        if stop_loss <= 0:
                            continue
                        position = runtime.open_position(symbol, price, stop_loss)
                        if position:
                            send_telegram_message(
                                "=== PAPER BUY ===\n"
                                f"Symbol: {symbol}\n"
                                f"Quantity: {position.quantity:.12f}\n"
                                f"Entry: {position.entry_price:.8f}\n"
                                f"Stop: {position.stop_loss:.8f}\n"
                                f"RSI: {rsi:.2f}"
                            )

                    elif signal == "SELL" and has_position:
                        logger.info("SELL signal observed for %s; Trade Manager decides exit/hold.", symbol)

        except Exception as exc:
            logger.exception("Market websocket error: %s", exc)
            await asyncio.sleep(5)


def run_flask() -> None:
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))


if __name__ == "__main__":
    threading.Thread(
        target=lambda: asyncio.run(start_shadow_engine()),
        daemon=True,
        name="shadow-market-engine",
    ).start()
    run_flask()
