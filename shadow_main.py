"""Shadow Trading Bot application entry point.

Architecture boundary:
    market data -> indicators/strategy -> Trade Manager -> core execution adapter

``shadow_main.py`` is intentionally an orchestrator. It does not own a
second portfolio, risk engine, position store, stop-loss engine, or execution
implementation. Those responsibilities belong to Trade Manager/Core.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Dict
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import websockets
from flask import Flask, jsonify

from trade_manager.shadow_integration import ShadowTradeManagerRuntime

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("ShadowMain")

INITIAL_CASH = float(os.getenv("PAPER_INITIAL_CASH", "1000.0"))
FEE_RATE = float(os.getenv("PAPER_FEE_RATE", "0.001"))
PAPER_STATE_DIR = os.getenv("PAPER_STATE_DIR", "data/paper")
TIMEFRAME_SECONDS = 60
REPORT_TIMEZONE = ZoneInfo(os.getenv("PAPER_REPORT_TIMEZONE", "Asia/Aden"))

ISLAMIC_ASSETS = [
    "BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "AVAX-USD", "LINK-USD", "MATIC-USD",
]

app = Flask(__name__)
runtime = ShadowTradeManagerRuntime(
    initial_cash=INITIAL_CASH,
    fee_rate=FEE_RATE,
    persistence_dir=PAPER_STATE_DIR,
)

current_prices: Dict[str, float] = {}
market_state: Dict[str, Dict[str, float]] = {}
resampler_history: Dict[str, list[dict]] = {}
resampler_current: Dict[str, dict] = {}
_report_lock = threading.RLock()
_last_report_date: str | None = None


def process_tick(symbol: str, price: float, volume: float, timestamp: float) -> None:
    bucket = int(timestamp // TIMEFRAME_SECONDS) * TIMEFRAME_SECONDS
    candle = resampler_current.get(symbol)
    if candle is None or candle["ts"] != bucket:
        if candle is not None:
            history = resampler_history.setdefault(symbol, [])
            history.append(candle)
            del history[:-200]
        resampler_current[symbol] = {
            "ts": bucket, "open": price, "high": price, "low": price,
            "close": price, "volume": volume,
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
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - previous_close).abs(),
        (df["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
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


# Render environment contract: TOKEN = Telegram bot token, TELEGRAMID = chat id.
# Legacy names remain supported only as fallbacks.
TELEGRAM_TOKEN = os.getenv("TOKEN") or os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAMID") or os.getenv("TELEGRAM_CHAT_ID")


def send_telegram_message(message: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram is not configured: TOKEN/TELEGRAMID are required")
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=10,
        )
        if response.status_code != 200:
            logger.error("Telegram returned HTTP %s: %s", response.status_code, response.text[:500])
            return False
        return bool(response.json().get("ok", True))
    except Exception:
        logger.exception("Telegram notification failed")
        return False


def _closed_positions_for_local_date(date_key: str):
    positions = []
    for position in runtime.repository.get_closed_positions():
        closed_at = position.closed_at or position.opened_at
        local_date = datetime.fromtimestamp(closed_at, REPORT_TIMEZONE).strftime("%Y-%m-%d")
        if local_date == date_key:
            positions.append(position)
    return positions


def build_daily_report(date_key: str | None = None) -> str:
    date_key = date_key or datetime.now(REPORT_TIMEZONE).strftime("%Y-%m-%d")
    closed = _closed_positions_for_local_date(date_key)
    by_coin: Dict[str, dict] = {}
    for position in closed:
        coin = position.symbol.upper().replace("-USD", "").replace("USDT", "")
        row = by_coin.setdefault(coin, {"wins": 0, "losses": 0, "net": 0.0})
        pnl = float(position.realized_pnl)
        row["wins" if pnl > 0 else "losses"] += 1
        row["net"] += pnl

    lines = [
        "📊 حصاد اليوم الشامل (PAPER TRADING)",
        f"📅 التاريخ: {date_key}",
        "",
        "```",
        f"{'COIN':<8} | {'WIN':<3} | {'LOSS':<4} | {'NET (FEES)':<10}",
        "---------------------------------",
    ]
    total_wins = total_losses = 0
    total_net = 0.0
    for coin in sorted(by_coin):
        row = by_coin[coin]
        total_wins += row["wins"]
        total_losses += row["losses"]
        total_net += row["net"]
        lines.append(f"{coin:<8} | {row['wins']:<3} | {row['losses']:<4} | {row['net']:+.2f}$")
    lines.extend([
        "---------------------------------",
        f"{'TOTAL':<8} | {total_wins:<3} | {total_losses:<4} | {total_net:+.2f}$",
        "```",
        f"💵 Paper cash: ${runtime.execution_adapter.balance.cash:.2f}",
        f"📦 Open positions: {len(runtime.repository.get_open_positions())}",
    ])
    if not closed:
        lines.insert(5, "لا توجد صفقات مغلقة في هذا اليوم بعد.")
    return "\n".join(lines)


def _daily_report_loop() -> None:
    global _last_report_date
    while True:
        try:
            now = datetime.now(REPORT_TIMEZONE)
            date_key = now.strftime("%Y-%m-%d")
            with _report_lock:
                if _last_report_date is None:
                    _last_report_date = date_key
                elif date_key != _last_report_date:
                    previous = _last_report_date
                    message = build_daily_report(previous)
                    if send_telegram_message(message):
                        _last_report_date = date_key
            time.sleep(30)
        except Exception:
            logger.exception("Daily paper report loop failed")
            time.sleep(30)


@app.get("/")
def home():
    positions = runtime.facade.get_open_positions()
    metrics = runtime.facade.get_metrics()
    return jsonify({
        "status": "healthy", "mode": "PAPER", "entrypoint": "shadow_main.py",
        "trade_manager": "modular_parts_1_8", "open_positions": len(positions),
        "symbols": [p.symbol for p in positions],
        "metrics": getattr(metrics, "__dict__", str(metrics)),
        "last_update": time.time(),
        "persistence": bool(PAPER_STATE_DIR),
        "telegram_configured": bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID),
        "daily_report_timezone": str(REPORT_TIMEZONE),
    }), 200


@app.get("/trade-manager/positions")
def positions():
    return jsonify([
        {
            "position_id": p.position_id, "symbol": p.symbol, "status": p.status.name,
            "quantity": p.quantity, "entry_price": p.entry_price,
            "current_price": p.current_price, "stop_loss": p.stop_loss,
            "take_profit": p.take_profit, "realized_pnl": p.realized_pnl,
            "fees": p.total_fees,
        }
        for p in runtime.repository.get_all()
    ]), 200


@app.get("/paper/daily-report")
def daily_report():
    return jsonify({
        "mode": "PAPER",
        "date": datetime.now(REPORT_TIMEZONE).strftime("%Y-%m-%d"),
        "report": build_daily_report(),
    }), 200


async def start_shadow_engine() -> None:
    send_telegram_message(
        "🟢 Paper Trading started on Render\n"
        "Trade Manager is the lifecycle boundary.\n"
        "No real exchange orders are submitted.\n"
        "Telegram: TOKEN + TELEGRAMID"
    )
    while True:
        try:
            async with websockets.connect("wss://ws-feed.exchange.coinbase.com", ping_interval=20) as ws:
                await ws.send(json.dumps({
                    "type": "subscribe", "product_ids": ISLAMIC_ASSETS, "channels": ["ticker"],
                }))
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
                        symbol, price=price, bid=bid, ask=ask,
                        spread_percent=spread_percent, atr=float(atr or 0.0),
                        volume_usdt=volume_usdt, volatility=0.0, ema100=float(ema100 or 0.0),
                    )
                    market_state[symbol] = {
                        "price": price, "ema100": float(ema100 or 0.0),
                        "rsi": float(rsi or 0.0), "atr": float(atr or 0.0),
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
                                f"Symbol: {symbol}\nQuantity: {position.quantity:.12f}\n"
                                f"Entry: {position.entry_price:.8f}\nStop: {position.stop_loss:.8f}\nRSI: {rsi:.2f}"
                            )
                    elif signal == "SELL" and has_position:
                        logger.info("SELL signal observed for %s; Trade Manager decides exit/hold.", symbol)
        except Exception as exc:
            logger.exception("Market websocket error: %s", exc)
            await asyncio.sleep(5)


def run_flask() -> None:
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))


if __name__ == "__main__":
    threading.Thread(target=_daily_report_loop, daemon=True, name="paper-daily-report").start()
    threading.Thread(
        target=lambda: asyncio.run(start_shadow_engine()),
        daemon=True,
        name="shadow-market-engine",
    ).start()
    run_flask()
