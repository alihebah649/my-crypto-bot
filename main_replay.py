import json
import time
import os
import requests
import math
from datetime import datetime
from flask import Flask, jsonify

app = Flask(__name__)

def fetch_asset_data(symbol):
    """جلب بيانات الحركة السعرية لـ 8 أيام مضت لأي زوج مالي"""
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

    str_val = [0]*n
    str_val[period] = sum(tr[1:period+1])
    for i in range(period + 1, n):
        str_val[i] = str_val[i-1] - (str_val[i-1] / period) + tr[i]

    for i in range(n):
        ticks[i]["atr"] = str_val[i] / period if str_val[i] else 0
    return ticks

def simulate_event_driven_path(direction, entry_price, future_candles, tp_percent, sl_percent):
    """
    محاكاة حركة السعر ساعة بساعة (Event-Driven) لحل مشكلة ارتهان المسار.
    تتبنى القاعدة الأكثر تحفظاً: في حال تداخل الهدف والستوب في نفس الشمعة، تُعتبر خسارة فوراً.
    """
    for candle in future_candles:
        if direction == "LONG":
            max_profit = (candle["high"] - entry_price) / entry_price * 100
            max_loss = (entry_price - candle["low"]) / entry_price * 100
            
            # في حال ضرب الاثنين في نفس الساعة -> افتراض السيناريو الأسوأ (خسارة)
            if max_profit >= tp_percent and max_loss >= sl_percent:
                return -sl_percent, "LOSS"
            if max_loss >= sl_percent:
                return -sl_percent, "LOSS"
            if max_profit >= tp_percent:
                return tp_percent, "WIN"
        else: # SHORT
            max_profit = (entry_price - candle["low"]) / entry_price * 100
            max_loss = (candle["high"] - entry_price) / entry_price * 100
            
            if max_profit >= tp_percent and max_loss >= sl_percent:
                return -sl_percent, "LOSS"
            if max_loss >= sl_percent:
                return -sl_percent, "LOSS"
            if max_profit >= tp_percent:
                return tp_percent, "WIN"
                
    # إذا انتهت الـ 4 ساعات دون ملامسة الأهداف، نغلق بـ سعر إغلاق الشمعة الأخيرة (Timeout)
    final_close = future_candles[-1]["close_price"]
    if direction == "LONG":
        pnl = (final_close - entry_price) / entry_price * 100
    else:
        pnl = (entry_price - final_close) / entry_price * 100
    return pnl, "WIN" if pnl > 0 else "LOSS"

@app.route('/')
def run_optimization_sweep():
    assets = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT"]
    tp_sweep_values = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 1.00]
    
    optimization_matrix = {}
    
    for symbol in assets:
        raw_ticks = fetch_asset_data(symbol)
        if not raw_ticks:
            optimization_matrix[symbol] = "خطأ في الاتصال ببيانات باينانس"
            continue
            
        ticks = calculate_indicators(raw_ticks)
        
        # رصد إشارات الدخول الثابتة الموحدة لهذا الأصل
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
                
        sweep_reports = []
        
        # تشغيل المسح الشامل لجميع قيم الأهداف مع تثبيت نظام مخاطرة متماثل 1:1
        for tp in tp_sweep_values:
            sl = tp  # تثبيت نظام 1:1 Risk-to-Reward لحساب كفاءة الإشارة بدقة وعادلية
            wins, losses = 0, 0
            gross_profits, gross_losses = 0.0, 0.0
            
            for sig in detected_signals:
                pnl, outcome = simulate_event_driven_path(sig["direction"], sig["entry_price"], sig["future_candles"], tp, sl)
                if outcome == "WIN":
                    wins += 1
                    gross_profits += pnl
                else:
                    losses += 1
                    gross_losses += abs(pnl)
                    
            total_trades = wins + losses
            win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
            profit_factor = gross_profits / gross_losses if gross_losses > 0 else (gross_profits if gross_profits > 0 else 0)
            net_pnl = gross_profits - gross_losses
            
            avg_win = (gross_profits / wins) if wins > 0 else 0
            avg_loss = (gross_losses / losses) if losses > 0 else 0
            
            # حساب التوقع الرياضي الحقيقي للنظام: Expectancy = (WR * AvgWin) - (LR * AvgLoss)
            loss_rate = 100 - win_rate
            expectancy = ((win_rate / 100) * avg_win) - ((loss_rate / 100) * avg_loss)
            
            sweep_reports.append({
                "TP_Target": f"{tp:.2f}%",
                "Win_Rate": f"{win_rate:.2f}%",
                "Profit_Factor": f"{profit_factor:.2f}",
                "Avg_Win": f"{avg_win:.3f}%",
                "Avg_Loss": f"{avg_loss:.3f}%",
                "Expectancy": f"{expectancy:.4f}%",
                "Net_PnL": f"{net_pnl:.2f}%",
                "Sample_Trades": total_trades
            })
            
        optimization_matrix[symbol] = sweep_reports
        
    return jsonify({
        "status": "INSTITUTIONAL_EVENT_DRIVEN_OPTIMIZATION_COMPLETE",
        "methodology_note": "Symmetrical 1:1 Bracket System (SL=TP). Intra-candle conflict rules set to Absolute Worst Case (Stop-Loss First).",
        "data_provenance": "Binance Live Spot API (1h Klines Matrix)",
        "results": optimization_matrix
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
