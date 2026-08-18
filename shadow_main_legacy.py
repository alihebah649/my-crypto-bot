"""Shadow Trading Bot application entry point.

Architecture boundary:
    Binance public market data -> strategy/score -> Trade Manager -> core paper execution

``shadow_main.py`` is intentionally an orchestrator. It does not own a second
portfolio, risk engine, position store, stop-loss engine, or execution
implementation. Those responsibilities belong to Trade Manager/Core.

The active paper strategy is the existing spot strategy contract:
15m macro support + EMA100/RSI/volume context -> 5m bullish confirmation ->
Part-6 risk approval -> Part-8 lifecycle.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Optional
from urllib.parse import quote
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
LOOP_SECONDS = float(os.getenv("PAPER_LOOP_SECONDS", "30"))
REPORT_TIMEZONE = ZoneInfo(os.getenv("PAPER_REPORT_TIMEZONE", "Asia/Aden"))
BINANCE_REST = os.getenv("BINANCE_REST_URL", "https://api.binance.com")

TRADING_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT",
    "ADAUSDT", "DOTUSDT", "NEARUSDT", "ARBUSDT",
    "OPUSDT", "RENDERUSDT", "BNBUSDT", "AVAXUSDT",
    "ALGOUSDT", "ATOMUSDT", "FETUSDT", "LTCUSDT",
]

BUY_SCORE_THRESHOLD = 80
EMA_POINTS = 20
RSI_POINTS = 20
BB_POINTS = 25
VOLUME_POINTS = 15
CANDLE_POINTS = 20

app = Flask(__name__)
runtime = ShadowTradeManagerRuntime(
    initial_cash=INITIAL_CASH,
    fee_rate=FEE_RATE,
    persistence_dir=PAPER_STATE_DIR,
)

current_prices: Dict[str, float] = {}
market_state: Dict[str, Dict[str, float]] = {}
latest_scores: Dict[str, dict] = {}
_report_lock = threading.RLock()
_last_report_date: str | None = None
_last_score_report_at = 0.0


# -----------------------------------------------------------------------------
# Telegram
# -----------------------------------------------------------------------------

TELEGRAM_TOKEN = os.getenv("TOKEN") or os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAMID") or os.getenv("TELEGRAM_CHAT_ID")


def send_telegram_message(message: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram is not configured: TOKEN/TELEGRAMID are required")
        return False
    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=10,
        )
        if response.status_code != 200:
            logger.error(
                "Telegram returned HTTP %s: %s",
                response.status_code,
                response.text[:500],
            )
            return False
        return bool(response.json().get("ok", True))
    except Exception:
        logger.exception("Telegram notification failed")
        return False


# -----------------------------------------------------------------------------
# Binance public market data
# -----------------------------------------------------------------------------


def _binance_get(path: str, params: Optional[dict] = None, timeout: float = 12.0):
    response = requests.get(
        f"{BINANCE_REST}{path}",
        params=params,
        headers={"User-Agent": "ShadowTradingBot/Paper"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def fetch_24h_tickers() -> dict[str, dict]:
    symbols_json = json.dumps(TRADING_SYMBOLS, separators=(",", ":"))
    data = _binance_get("/api/v3/ticker/24hr", {"symbols": symbols_json})
    return {item["symbol"]: item for item in data if item.get("symbol") in TRADING_SYMBOLS}


def fetch_klines(symbol: str, interval: str, limit: int) -> list[dict]:
    raw = _binance_get(
        "/api/v3/klines",
        {"symbol": symbol, "interval": interval, "limit": limit},
    )
    candles = []
    for row in raw:
        candles.append(
            {
                "open_time": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "close_time": int(row[6]),
            }
        )
    return candles


def fetch_strategy_data() -> tuple[dict[str, dict], dict[str, list[dict]], dict[str, list[dict]]]:
    tickers = fetch_24h_tickers()
    entry_15m: dict[str, list[dict]] = {}
    entry_5m: dict[str, list[dict]] = {}

    jobs: dict[concurrent.futures.Future, tuple[str, str]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        for symbol in TRADING_SYMBOLS:
            jobs[executor.submit(fetch_klines, symbol, "15m", 150)] = (symbol, "15m")
            jobs[executor.submit(fetch_klines, symbol, "5m", 60)] = (symbol, "5m")
        for future in concurrent.futures.as_completed(jobs):
            symbol, timeframe = jobs[future]
            try:
                data = future.result()
            except Exception as exc:
                logger.warning("Kline fetch failed for %s %s: %s", symbol, timeframe, exc)
                continue
            if timeframe == "15m":
                entry_15m[symbol] = data
            else:
                entry_5m[symbol] = data

    return tickers, entry_15m, entry_5m


# -----------------------------------------------------------------------------
# Indicators and strategy
# -----------------------------------------------------------------------------


def calculate_ema(prices: list[float], period: int = 100) -> float:
    if len(prices) < period:
        return 0.0
    series = pd.Series(prices, dtype="float64")
    return float(series.ewm(span=period, adjust=False).mean().iloc[-1])


def calculate_rsi(prices: list[float], period: int = 14) -> float:
    if len(prices) < period + 1:
        return 0.0
    series = pd.Series(prices, dtype="float64")
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    if float(avg_loss.iloc[-1]) == 0.0:
        return 100.0 if float(avg_gain.iloc[-1]) > 0 else 50.0
    rs = avg_gain / avg_loss
    return float((100 - (100 / (1 + rs))).iloc[-1])


def calculate_atr(candles: list[dict], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    highs = pd.Series([c["high"] for c in candles], dtype="float64")
    lows = pd.Series([c["low"] for c in candles], dtype="float64")
    closes = pd.Series([c["close"] for c in candles], dtype="float64")
    previous = closes.shift(1)
    tr = pd.concat(
        [highs - lows, (highs - previous).abs(), (lows - previous).abs()],
        axis=1,
    ).max(axis=1)
    return float(tr.ewm(alpha=1 / period, adjust=False).mean().iloc[-1])


def calculate_bollinger(candles: list[dict], period: int = 20, deviations: float = 2.0):
    if len(candles) < period:
        return 0.0, 0.0, 0.0
    closes = pd.Series([c["close"] for c in candles], dtype="float64")
    middle = float(closes.rolling(period).mean().iloc[-1])
    std = float(closes.rolling(period).std(ddof=0).iloc[-1])
    return middle - deviations * std, middle, middle + deviations * std


def bullish_pattern(candles: list[dict]) -> tuple[bool, str, bool]:
    if len(candles) < 4:
        return False, "INSUFFICIENT_CANDLES", False
    c1, c2, c3 = candles[-1], candles[-2], candles[-3]
    body1 = abs(c1["close"] - c1["open"])
    body2 = abs(c2["close"] - c2["open"])
    body3 = abs(c3["close"] - c3["open"])
    bullish1 = c1["close"] > c1["open"]
    bullish2 = c2["close"] > c2["open"]
    bearish2 = c2["close"] < c2["open"]
    bearish3 = c3["close"] < c3["open"]
    lower_shadow = min(c1["open"], c1["close"]) - c1["low"]
    upper_shadow = c1["high"] - max(c1["open"], c1["close"])

    name = ""
    if bearish3 and bullish2 and c2["close"] >= c3["open"] and c2["open"] <= c3["close"] and body2 > body3:
        name = "BULLISH_OUTSIDE"
    elif bearish3 and body2 <= body3 * 0.30 and bullish1 and c2["low"] < c3["low"] and c2["low"] < c1["low"]:
        name = "MORNING_STAR"
    elif bearish2 and bullish1 and c1["close"] >= c2["open"] and c1["open"] <= c2["close"] and body1 > body2:
        name = "BULLISH_ENGULFING"
    elif lower_shadow >= 2 * body1 and upper_shadow < 0.4 * max(body1, 1e-12) and body1 > 0:
        name = "HAMMER"
    elif bullish1 and bullish2 and c1["close"] > c2["high"]:
        name = "BULLISH_BREAKOUT"

    if not name:
        return False, "NEUTRAL", False
    confirmation = bullish1 and c1["close"] > c2["high"]
    return True, name, confirmation


def score_symbol(symbol: str, ticker: dict, candles_15m: list[dict], candles_5m: list[dict]) -> dict:
    closed_15m = candles_15m[:-1] if len(candles_15m) > 1 else []
    closed_5m = candles_5m[:-1] if len(candles_5m) > 1 else []
    price = float(ticker.get("lastPrice", 0.0))
    if len(closed_15m) < 100 or len(closed_5m) < 4 or price <= 0:
        return {
            "symbol": symbol, "score": 0, "signal": "HOLD", "reasons": ["INSUFFICIENT_DATA"],
            "price": price, "ema100": 0.0, "rsi": 0.0, "atr": 0.0,
        }
    closes = [c["close"] for c in closed_15m]
    ema100 = calculate_ema(closes, 100)
    rsi = calculate_rsi(closes, 14)
    atr = calculate_atr(closed_15m, 14)
    lower_band, middle_band, upper_band = calculate_bollinger(closed_15m, 20, 2.0)
    current_volume = closed_15m[-1]["volume"]
    average_volume = sum(c["volume"] for c in closed_15m[-21:-1]) / 20.0
    score = 0
    reasons: list[str] = []
    if price > ema100:
        score += EMA_POINTS; reasons.append("EMA100_TREND")
    if rsi <= 30:
        score += RSI_POINTS; reasons.append("RSI_DEEP_OVERSOLD")
    elif rsi < 40:
        score += 15; reasons.append("RSI_OVERSOLD")
    elif rsi < 50:
        score += 8; reasons.append("RSI_RECOVERY_ZONE")
    if lower_band > 0:
        distance_from_lower = (price - lower_band) / price
        if price <= lower_band:
            score += BB_POINTS; reasons.append("BOLLINGER_LOWER_SUPPORT")
        elif distance_from_lower <= 0.005:
            score += 18; reasons.append("BOLLINGER_NEAR_SUPPORT")
        elif price <= middle_band:
            score += 8; reasons.append("BOLLINGER_LOWER_HALF")
    if average_volume > 0:
        volume_ratio = current_volume / average_volume
        if volume_ratio >= 1.20:
            score += VOLUME_POINTS; reasons.append("VOLUME_CONFIRMATION")
        elif volume_ratio >= 1.05:
            score += 8; reasons.append("VOLUME_RISING")
    pattern_found, pattern_name, confirmation = bullish_pattern(closed_5m)
    if pattern_found and confirmation:
        score += CANDLE_POINTS; reasons.append(f"5M_{pattern_name}_CONFIRMED")
    elif pattern_found:
        score += 8; reasons.append(f"5M_{pattern_name}")
    score = min(score, 100)
    signal = "BUY" if score >= BUY_SCORE_THRESHOLD else "HOLD"
    return {
        "symbol": symbol, "score": score, "signal": signal, "reasons": reasons,
        "price": price, "ema100": ema100, "rsi": rsi, "atr": atr,
        "lower_band": lower_band, "middle_band": middle_band, "upper_band": upper_band,
        "volume_ratio": current_volume / average_volume if average_volume else 0.0,
        "pattern": pattern_name, "pattern_confirmed": confirmation,
    }


def btc_crash_guard(candles: list[dict]) -> tuple[bool, float]:
    closed = candles[:-1] if len(candles) > 1 else candles
    if len(closed) < 3:
        return False, 0.0
    current = closed[-1]["close"]
    recent_high = max(c["close"] for c in closed[-3:])
    if recent_high <= 0:
        return False, 0.0
    drop = (current - recent_high) / recent_high
    return drop <= -0.03, drop * 100.0


# -----------------------------------------------------------------------------
# Reports and HTTP diagnostics
# -----------------------------------------------------------------------------


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
        coin = position.symbol.upper().replace("USDT", "")
        row = by_coin.setdefault(coin, {"wins": 0, "losses": 0, "net": 0.0})
        pnl = float(position.realized_pnl)
        row["wins" if pnl > 0 else "losses"] += 1
        row["net"] += pnl
    lines = [
        "📊 حصاد اليوم الشامل (PAPER TRADING)", f"📅 التاريخ المنتهي: {date_key}", "", "```",
        f"{'COIN':<8} | {'WIN':<3} | {'LOSS':<4} | {'NET (FEES)':<10}",
        "---------------------------------",
    ]
    total_wins = total_losses = 0; total_net = 0.0
    for coin in sorted(by_coin):
        row = by_coin[coin]; total_wins += row["wins"]; total_losses += row["losses"]; total_net += row["net"]
        lines.append(f"{coin:<8} | {row['wins']:<3} | {row['losses']:<4} | {row['net']:+.2f}$")
    lines.extend([
        "---------------------------------", f"{'TOTAL':<8} | {total_wins:<3} | {total_losses:<4} | {total_net:+.2f}$",
        "```", "📄 Paper Trading — لا توجد أوامر حقيقية" if not closed else "📄 Paper Trading — أوامر محاكاة فقط",
        f"💵 Paper cash: ${runtime.execution_adapter.balance.cash:.2f}",
        f"📦 Open positions: {len(runtime.repository.get_open_positions())}",
    ])
    return "\n".join(lines)


def build_score_diagnostic() -> str:
    rows = sorted(latest_scores.values(), key=lambda item: item.get("score", 0), reverse=True)
    top = rows[:8]
    lines = [
        "🔎 تشخيص Score — Paper Trading",
        f"📡 العملات ذات البيانات: {len(latest_scores)}/{len(TRADING_SYMBOLS)}",
        f"🎯 BUY >= {BUY_SCORE_THRESHOLD}: {sum(1 for r in rows if r.get('signal') == 'BUY')}", "", "أعلى الدرجات:",
    ]
    for row in top:
        lines.append(f"• {row['symbol']}: {row['score']}/100 | RSI={row['rsi']:.1f} | EMA100={row['ema100']:.6f} | {', '.join(row['reasons']) or '—'}")
    return "\n".join(lines)


def _daily_report_loop() -> None:
    global _last_report_date
    while True:
        try:
            now = datetime.now(REPORT_TIMEZONE); date_key = now.strftime("%Y-%m-%d")
            with _report_lock:
                if _last_report_date is None:
                    _last_report_date = date_key
                elif date_key != _last_report_date:
                    previous = _last_report_date
                    if send_telegram_message(build_daily_report(previous)):
                        _last_report_date = date_key
            time.sleep(30)
        except Exception:
            logger.exception("Daily report loop failed"); time.sleep(30)


@app.get("/")
def home():
    positions = runtime.facade.get_open_positions(); metrics = runtime.facade.get_metrics()
    return jsonify({
        "status": "healthy", "mode": "PAPER", "entrypoint": "shadow_main.py",
        "trade_manager": "modular_parts_1_8", "symbols": TRADING_SYMBOLS,
        "open_positions": len(positions), "metrics": getattr(metrics, "__dict__", str(metrics)),
        "last_update": time.time(), "persistence": bool(PAPER_STATE_DIR),
        "telegram_configured": bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID),
        "score_threshold": BUY_SCORE_THRESHOLD,
        "strategy": "15m Bollinger/EMA/RSI/Volume + 5m bullish confirmation",
        "daily_report_timezone": str(REPORT_TIMEZONE),
    }), 200


@app.get("/trade-manager/positions")
def positions():
    return jsonify([
        {"position_id": p.position_id, "symbol": p.symbol, "status": p.status.name, "quantity": p.quantity,
         "entry_price": p.entry_price, "current_price": p.current_price, "stop_loss": p.stop_loss,
         "take_profit": p.take_profit, "realized_pnl": p.realized_pnl, "fees": p.total_fees}
        for p in runtime.repository.get_all()
    ]), 200


@app.get("/paper/daily-report")
def daily_report():
    return jsonify({"mode": "PAPER", "date": datetime.now(REPORT_TIMEZONE).strftime("%Y-%m-%d"), "report": build_daily_report()}), 200


@app.get("/paper/diagnostics")
def diagnostics():
    return jsonify({
        "mode": "PAPER",
        "symbol_count": len(TRADING_SYMBOLS),
        "data_count": len(latest_scores),
        "buy_count": sum(1 for row in latest_scores.values() if row.get("signal") == "BUY"),
        "score_threshold": BUY_SCORE_THRESHOLD,
        "scores": sorted(latest_scores.values(), key=lambda item: item.get("score", 0), reverse=True),
        "entry_diagnostics": runtime.last_entry_diagnostics,
    }), 200


# -----------------------------------------------------------------------------
# Main market loop
# -----------------------------------------------------------------------------


def process_market_cycle() -> None:
    global latest_scores
    tickers, candles_15m, candles_5m = fetch_strategy_data()
    new_scores: dict[str, dict] = {}
    btc_1h = fetch_klines("BTCUSDT", "1h", 6)
    btc_crashing, btc_drop = btc_crash_guard(btc_1h)
    if btc_crashing:
        logger.warning("BTC crash guard active: %.2f%%", btc_drop)

    for symbol in TRADING_SYMBOLS:
        ticker = tickers.get(symbol); c15 = candles_15m.get(symbol, []); c5 = candles_5m.get(symbol, [])
        if not ticker:
            continue
        price = float(ticker.get("lastPrice", 0.0)); bid = float(ticker.get("bidPrice", price) or price)
        ask = float(ticker.get("askPrice", price) or price)
        spread = ((ask - bid) / price * 100.0) if price > 0 else 0.0
        quote_volume = float(ticker.get("quoteVolume", 0.0) or 0.0)
        score = score_symbol(symbol, ticker, c15, c5); new_scores[symbol] = score
        runtime.update_market(symbol, price=price, bid=bid, ask=ask, spread_percent=spread,
                              atr=float(score.get("atr", 0.0)), volume_usdt=quote_volume,
                              volatility=0.0, ema100=float(score.get("ema100", 0.0)))
        current_prices[symbol] = price; market_state[symbol] = score
        runtime.evaluate_position(symbol)

    latest_scores = new_scores

    for symbol, score in sorted(new_scores.items(), key=lambda item: item[1]["score"], reverse=True):
        if score.get("signal") != "BUY":
            continue

        # Non-invasive trace: these are pre-Trade-Manager blockers. They do not
        # change the existing decision path; they only make the exact choke
        # point observable from /paper/diagnostics.
        trace = runtime.last_entry_diagnostics.setdefault(symbol, {"symbol": symbol})
        trace.update({
            "score": score.get("score"), "signal": score.get("signal"),
            "scalp_score": score.get("scalp_score"), "scalp_gate": score.get("scalp_gate"),
            "pre_trade": {"btc_crash_guard": "PASS", "existing_position": "PASS",
                          "atr_price": "PASS", "stop_loss": "PASS"},
        })
        if btc_crashing:
            trace["pre_trade"]["btc_crash_guard"] = "REJECT"
            trace["result"] = "REJECTED_AT_BTC_CRASH_GUARD"
            trace["finished_at"] = time.time()
            logger.info("ENTRY TRACE %s: %s", symbol, trace)
            continue
        if runtime.controller.has_position(symbol):
            trace["pre_trade"]["existing_position"] = "REJECT"
            trace["result"] = "REJECTED_EXISTING_POSITION"
            trace["finished_at"] = time.time()
            logger.info("ENTRY TRACE %s: %s", symbol, trace)
            continue
        atr = float(score.get("atr", 0.0)); price = float(score.get("price", 0.0))
        if atr <= 0 or price <= 0:
            trace["pre_trade"]["atr_price"] = "REJECT"
            trace["result"] = "REJECTED_INVALID_ATR_OR_PRICE"
            trace["finished_at"] = time.time()
            logger.info("ENTRY TRACE %s: %s", symbol, trace)
            continue
        stop_loss = price - (2.0 * atr)
        if stop_loss <= 0:
            trace["pre_trade"]["stop_loss"] = "REJECT"
            trace["result"] = "REJECTED_INVALID_STOP"
            trace["finished_at"] = time.time()
            logger.info("ENTRY TRACE %s: %s", symbol, trace)
            continue

        position = runtime.open_position(symbol, price, stop_loss)
        trace = runtime.last_entry_diagnostics.get(symbol, trace)
        if position is not None:
            reasons = " | ".join(score.get("reasons", []))
            send_telegram_message(
                "=== PAPER BUY ===\n" f"Symbol: {symbol}\n" f"Score: {score['score']}/100\n"
                f"Reasons: {reasons}\n" f"Quantity: {position.quantity:.12f}\n"
                f"Entry: {position.entry_price:.8f}\n" f"Stop: {position.stop_loss:.8f}\n"
                f"RSI: {score['rsi']:.2f}\n" f"EMA100: {score['ema100']:.8f}\nPAPER ONLY"
            )
        else:
            logger.warning("ENTRY BLOCKED %s: score=%s trace=%s", symbol, score.get("score"), trace)

    logger.info("Paper cycle complete: data=%d/%d, BUY=%d, top=%s",
                len(new_scores), len(TRADING_SYMBOLS),
                sum(1 for row in new_scores.values() if row.get("signal") == "BUY"),
                ", ".join(f"{r['symbol']}:{r['score']}" for r in sorted(new_scores.values(), key=lambda x: x['score'], reverse=True)[:5]))


async def start_shadow_engine() -> None:
    if not send_telegram_message("🟢 Paper Trading strategy engine started on Render\n"
                                 f"Universe: {len(TRADING_SYMBOLS)} Binance Spot USDT pairs\n"
                                 "Strategy: 15m macro support + 5m bullish confirmation + EMA100/RSI/volume\n"
                                 "Trade Manager: Parts 1-8\nNo real exchange orders are submitted."):
        logger.warning("Paper engine started but Telegram activation message was not delivered")
    while True:
        started = time.monotonic()
        try:
            await asyncio.to_thread(process_market_cycle)
        except Exception:
            logger.exception("Paper market cycle failed")
        elapsed = time.monotonic() - started
        await asyncio.sleep(max(1.0, LOOP_SECONDS - elapsed))


def run_flask() -> None:
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")), debug=False, use_reloader=False)


if __name__ == "__main__":
    threading.Thread(target=_daily_report_loop, daemon=True, name="paper-daily-report").start()
    threading.Thread(target=lambda: asyncio.run(start_shadow_engine()), daemon=True, name="shadow-market-engine").start()
    run_flask()
