import json
import time
import os
import requests
import math
from datetime import datetime
from flask import Flask, jsonify

app = Flask(__name__)

def fetch_past_8_days_data():
    symbol = "BTCUSDT"
    interval = "1h"
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=200"
    try:
        response = requests.get(url, timeout=10)
        raw_candles = response.json()
        formatted_ticks = []
        for c in raw_candles:
            formatted_ticks.append({
                "timestamp": float(c[0]) / 1000.0,
                "open_price": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close_price": float(c[4]),
                "volume": float(c[5])
            })
        return formatted_ticks
    except Exception as e:
        return []

def calculate_indicators(ticks, period=14):
    n = len(ticks)
    if n <= period: return ticks
    tr, plus_dm, minus_dm = [0]*n, [0]*n, [0]*n

    for i in range(1, n):
        up_move = ticks[i]["high"] - ticks[i-1]["high"]
        down_move = ticks[i-1]["low"] - ticks[i]["low"]
        c1 = ticks[i]["high"] - ticks[i]["low"]
        c2 = abs(ticks[i]["high"] - ticks[i-1]["close_price"])
        c3 = abs(ticks[i]["low"] - ticks[i-1]["close_price"])
        tr[i] = max(c1, c2, c3)
        if up_move > down_move and up_move > 0: plus_dm[i] = up_move
        if down_move > up_move and down_move > 0: minus_dm[i] = down_move

    str_val, splus_dm, sminus_dm = [0]*n, [0]*n, [0]*n
    str_val[period] = sum(tr[1:period+1])
    splus_dm[period] = sum(plus_dm[1:period+1])
    sminus_dm[period] = sum(minus_dm[1:period+1])

    for i in range(period + 1, n):
        str_val[i] = str_val[i-1] - (str_val[i-1] / period) + tr[i]
        splus_dm[i] = splus_dm[i-1] - (splus_dm[i-1] / period) + plus_dm[i]
        sminus_dm[i] = sminus_dm[i-1] - (sminus_dm[i-1] / period) + minus_dm[i]

    adx, dx = [0]*n, [0]*n
    for i in range(period, n):
        if str_val[i] == 0: continue
        plus_di = 100 * (splus_dm[i] / str_val[i])
        minus_di = 100 * (sminus_dm[i] / str_val[i])
        denom = plus_di + minus_di
        dx[i] = (100 * abs(plus_di - minus_di) / denom) if denom != 0 else 0

    if n > period * 2:
        adx[period * 2] = sum(dx[period:period * 2]) / period
        for i in range(period * 2 + 1, n):
            adx[i] = ((adx[i-1] * (period - 1)) + dx[i]) / period

    for i in range(n):
        ticks[i]["atr"] = str_val[i] / period if str_val[i] else 0
        ticks[i]["adx"] = adx[i]
    return ticks

def simulate_trade_path(direction, entry_price, future_candles, be_trigger_percent=None):
    """تحاكي مسار الصفقة ساعة بساعة لحل مشكلة ارتهان المسار الإحصائي"""
    be_activated = False
    
    for candle in future_candles:
        if direction == "LONG":
            max_potential_profit = (candle["high"] - entry_price) / entry_price * 100
            
            # التحقق من تفعيل شرط الـ Break-Even أولاً في هذه الشمعة
            if be_trigger_percent and not be_activated and max_potential_profit >= be_trigger_percent:
                be_activated = True
            
            # إذا كان الـ BE مفعلاً، هل ضرب السعر نقطة الدخول أو هبط تحتها في هذه الشمعة أو الشموع التالية؟
            if be_activated and candle["low"] <= entry_price:
                return 0.0, "BREAK_EVEN"
                
        else: # SHORT
            max_potential_profit = (entry_price - candle["low"]) / entry_price * 100
            
            if be_trigger_percent and not be_activated and max_potential_profit >= be_trigger_percent:
                be_activated = True
                
            if be_activated and candle["high"] >= entry_price:
                return 0.0, "BREAK_EVEN"
    
    # إذا لم يضرب الـ BE طوال الـ 4 ساعات، نخرج بسعر إغلاق الشمعة الأخيرة
    final_close = future_candles[-1]["close_price"]
    if direction == "LONG":
        pnl = (final_close - entry_price) / entry_price * 100
    else:
        pnl = (entry_price - final_close) / entry_price * 100
        
    return pnl, "WIN" if pnl > 0 else "LOSS"

def run_backtest_matrix():
    raw_ticks = fetch_past_8_days_data()
    if not raw_ticks: return {"error": "بيانات باينانس غير متوفرة حالياً"}
    ticks = calculate_indicators(raw_ticks)
    
    # رصد الإشارات الثابتة الموحدة أولاً لضمان تماثل العينة
    detected_signals = []
    for i in range(30, len(ticks) - 4):
        current = ticks[i]
        prev = ticks[i-1]
        price_change = (current["close_price"] - prev["close_price"]) / prev["close_price"]
        
        if abs(price_change) > 0.002 and current["volume"] > prev["volume"] * 1.1:
            detected_signals.append({
                "entry_price": current["close_price"],
                "direction": "LONG" if price_change > 0 else "SHORT",
                "future_candles": ticks[i+1 : i+5]
            })
            
    scenarios = {
        "1_Baseline (No BE)": None,
        "2_BE_Activated_At_Plus_0.25%": 0.25,
        "3_BE_Activated_At_Plus_0.35%": 0.35,
        "4_BE_Activated_At_Plus_0.50%": 0.50
    }
    
    matrix_results = {}
    
    for name, trigger in scenarios.items():
        wins, losses, bes = 0, 0, 0
        gross_profits, gross_losses = 0.0, 0.0
        
        for sig in detected_signals:
            pnl, outcome = simulate_trade_path(sig["direction"], sig["entry_price"], sig["future_candles"], trigger)
            
            if outcome == "WIN":
                wins += 1
                gross_profits += pnl
            elif outcome == "LOSS":
                losses += 1
                gross_losses += abs(pnl)
            elif outcome == "BREAK_EVEN":
                bes += 1
                
        total_trades = wins + losses + bes
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        profit_factor = gross_profits / gross_losses if gross_losses > 0 else gross_profits
        net_pnl = gross_profits - gross_losses
        
        matrix_results[name] = {
            "total_executed_trades": total_trades,
            "wins_count": wins,
            "losses_count": losses,
            "break_even_count": bes,
            "win_rate": f"{win_rate:.2f}%",
            "true_profit_factor": f"{profit_factor:.2f}",
            "net_pnl_percent": f"{net_pnl:.2f}%",
            "avg_profit_per_win": f"{(gross_profits/wins if wins > 0 else 0):.3f}%",
            "avg_loss_per_loss": f"{(gross_losses/losses if losses > 0 else 0):.3f}%"
        }
        
    return {
        "status": "QUANT_LAB_MATRIX_ANALYSIS_COMPLETE",
        "total_signals_analyzed": len(detected_signals),
        "comparative_scenarios_matrix": matrix_results
    }

@app.route('/')
def dashboard():
    return jsonify(run_backtest_matrix())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
