import json
import time
import os
import requests
import math
from datetime import datetime
from flask import Flask, jsonify

app = Flask(__name__)

def fetch_past_8_days_data():
    print("⏳ جاري جلب سجل حركة السوق للـ 8 أيام الماضية من Binance...")
    symbol = "BTCUSDT"
    interval = "1h"
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=200"
    
    try:
        response = requests.get(url, timeout=10)
        raw_candles = response.json()
        formatted_ticks = []
        for c in raw_candles:
            formatted_ticks.append({
                "timestamp": float(c[0]) / 1000.0, # تحويل إلى ثوانٍ
                "open_price": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close_price": float(c[4]),
                "volume": float(c[5])
            })
        return formatted_ticks
    except Exception as e:
        print(f"❌ فشل جلب البيانات: {e}")
        return []

def calculate_indicators(ticks, period=14):
    """حساب مؤشرات ATR و ADX برمجياً بدون مكتبات خارجية لضمان بيئة تشغيل خفيفة"""
    n = len(ticks)
    if n <= period:
        return ticks

    # 1. حساب True Range (TR) و Directional Movement (DM)
    tr = [0] * n
    plus_dm = [0] * n
    minus_dm = [0] * n

    for i in range(1, n):
        up_move = ticks[i]["high"] - ticks[i-1]["high"]
        down_move = ticks[i-1]["low"] - ticks[i]["low"]
        
        # TR
        c1 = ticks[i]["high"] - ticks[i]["low"]
        c2 = abs(ticks[i]["high"] - ticks[i-1]["close_price"])
        c3 = abs(ticks[i]["low"] - ticks[i-1]["close_price"])
        tr[i] = max(c1, c2, c3)

        # +DM & -DM
        if up_move > down_move and up_move > 0:
            plus_dm[i] = up_move
        if down_move > up_move and down_move > 0:
            minus_dm[i] = down_move

    # 2. التمهيد (Smoothing) لحساب ATR و DI
    str_val = [0] * n
    splus_dm = [0] * n
    sminus_dm = [0] * n

    str_val[period] = sum(tr[1:period+1])
    splus_dm[period] = sum(plus_dm[1:period+1])
    sminus_dm[period] = sum(minus_dm[1:period+1])

    for i in range(period + 1, n):
        str_val[i] = str_val[i-1] - (str_val[i-1] / period) + tr[i]
        splus_dm[i] = splus_dm[i-1] - (splus_dm[i-1] / period) + plus_dm[i]
        sminus_dm[i] = sminus_dm[i-1] - (sminus_dm[i-1] / period) + minus_dm[i]

    # 3. حساب ADX
    adx = [0] * n
    dx = [0] * n
    for i in range(period, n):
        if str_val[i] == 0:
            continue
        plus_di = 100 * (splus_dm[i] / str_val[i])
        minus_di = 100 * (sminus_dm[i] / str_val[i])
        
        denom = plus_di + minus_di
        dx[i] = (100 * abs(plus_di - minus_di) / denom) if denom != 0 else 0

    # تمهيد الـ DX للحصول على ADX
    if n > period * 2:
        adx[period * 2] = sum(dx[period:period * 2]) / period
        for i in range(period * 2 + 1, n):
            adx[i] = ((adx[i-1] * (period - 1)) + dx[i]) / period

    # دمج المؤشرات في الحقول
    for i in range(n):
        ticks[i]["atr"] = str_val[i] / period if str_val[i] else 0
        ticks[i]["adx"] = adx[i]
    
    return ticks

def calculate_correlation(x, y):
    """حساب معامل ارتباط بيرسون لقياس أهمية الخصائص إحصائياً"""
    n = len(x)
    if n < 2: return 0
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    num = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
    den_x = sum((x[i] - mean_x) ** 2 for i in range(n))
    den_y = sum((x[i] - mean_y) ** 2 for i in range(n))
    if den_x == 0 or den_y == 0: return 0
    return num / math.sqrt(den_x * den_y)

def analyze_performance():
    raw_ticks = fetch_past_8_days_data()
    if not raw_ticks:
        return {"error": "لم يتم العثور على بيانات جارية للتحليل"}

    ticks = calculate_indicators(raw_ticks)
    
    total_signals = 0
    passed_filters = 0
    trades_matrix = []
    
    # محاكاة الاستراتيجية (نبدأ من شمعة 30 لضمان استقرار المؤشرات الحسابية)
    for i in range(30, len(ticks) - 4):  
        current = ticks[i]
        prev = ticks[i-1]
        
        price_change = (current["close_price"] - prev["close_price"]) / prev["close_price"]
        
        if abs(price_change) > 0.002: # رصد الإشارة
            total_signals += 1
            
            if current["volume"] > prev["volume"] * 1.1: # الفلتر الصارم
                passed_filters += 1
                
                # تفاصيل الدخول والاتجاه
                entry_price = current["close_price"]
                direction = "LONG" if price_change > 0 else "SHORT"
                
                # تتبع الصفقة عبر الـ 4 شموع القادمة لحساب MAE, MFE, PnL الحقيقي
                future_candles = ticks[i+1 : i+5]
                highs = [c["high"] for c in future_candles]
                lows = [c["low"] for c in future_candles]
                exit_price = future_candles[-1]["close_price"]
                
                if direction == "LONG":
                    actual_pnl = (exit_price - entry_price) / entry_price
                    mfe = (max(highs) - entry_price) / entry_price
                    mae = (min(lows) - entry_price) / entry_price
                else:
                    actual_pnl = (entry_price - exit_price) / entry_price
                    mfe = (entry_price - min(lows)) / entry_price
                    mae = (entry_price - max(highs)) / entry_price
                
                # توليد صبغة وقت التداول والـ Confidence غير المعاير لمحاكاتك السابقة
                dt = datetime.utcfromtimestamp(current["timestamp"])
                
                # بناء مصفوفة الخصائص الجينية للصفقة
                trade_features = {
                    "symbol": "BTCUSDT",
                    "hour": dt.hour,
                    "day_of_week": dt.weekday(), # 0=Monday, 6=Sunday
                    "adx": current["adx"],
                    "atr": current["atr"],
                    "volume": current["volume"],
                    "confidence": min(0.95, 0.75 + abs(price_change) * 12), # محاكاة التوزيع شبه المسطح
                    "mae_percent": mae * 100,
                    "mfe_percent": mfe * 100,
                    "final_pnl_percent": actual_pnl * 100,
                    "is_win": actual_pnl > 0
                }
                trades_matrix.append(trade_features)

    # عزل الرابحة والخاسرة لبناء التقارير الإحصائية
    winners = [t for t in trades_matrix if t["is_win"]]
    losers = [t for t in trades_matrix if not t["is_win"]]
    
    total_trades = len(trades_matrix)
    wins_count = len(winners)
    losses_count = len(losers)
    
    # حساب قيم Profit Factor الحقيقية بناء على حجم الأرباح والخسائر الفعلية
    gross_profits = sum(t["final_pnl_percent"] for t in winners)
    gross_losses = abs(sum(t["final_pnl_percent"] for t in losers))
    true_profit_factor = gross_profits / gross_losses if gross_losses > 0 else gross_profits
    
    # --- 1. REPORT: Winner Profile ---
    winner_profile = {}
    if winners:
        winner_profile = {
            "avg_adx_in_wins": sum(t["adx"] for t in winners) / wins_count,
            "avg_atr_in_wins": sum(t["atr"] for t in winners) / wins_count,
            "avg_confidence_in_wins": sum(t["confidence"] for t in winners) / wins_count,
            "avg_mfe_achieved": sum(t["mfe_percent"] for t in winners) / wins_count,
            "most_active_hour_wins": max(set([t["hour"] for t in winners]), default=0)
        }

    # --- 2. REPORT: Winner vs Loser Differential ---
    differential_analysis = {
        "adx_diff (Win vs Loss)": (sum(t["adx"] for t in winners)/wins_count if wins_count else 0) - (sum(t["adx"] for t in losers)/losses_count if losses_count else 0),
        "mae_diff_percent": (sum(t["mae_percent"] for t in winners)/wins_count if wins_count else 0) - (sum(t["mae_percent"] for t in losers)/losses_count if losses_count else 0),
        "confidence_gap": (sum(t["confidence"] for t in winners)/wins_count if wins_count else 0) - (sum(t["confidence"] for t in losers)/losses_count if losses_count else 0)
    }

    # --- 3. REPORT: Edge Concentration Report ---
    hours_pnl = {}
    days_pnl = {}
    for t in trades_matrix:
        hours_pnl[t["hour"]] = hours_pnl.get(t["hour"], 0) + t["final_pnl_percent"]
        days_pnl[t["day_of_week"]] = days_pnl.get(t["day_of_week"], 0) + t["final_pnl_percent"]
        
    edge_concentration = {
        "best_performing_hour_utc": max(hours_pnl, key=hours_pnl.get) if hours_pnl else None,
        "worst_performing_hour_utc": min(hours_pnl, key=hours_pnl.get) if hours_pnl else None,
        "best_performing_day": max(days_pnl, key=days_pnl.get) if days_pnl else None,
        "concentration_by_asset": {"BTCUSDT_net_pnl_percent": sum(t["final_pnl_percent"] for t in trades_matrix)}
    }

    # --- 4. REPORT: Regime Validation Report ---
    trend_regime_trades = [t for t in trades_matrix if t["adx"] > 25]
    range_regime_trades = [t for t in trades_matrix if t["adx"] < 20]
    
    def calc_segment_metrics(segment):
        if not segment: return {"trades": 0, "win_rate": "0%"}
        seg_wins = sum(1 for t in segment if t["is_win"])
        return {
            "trades_count": len(segment),
            "win_rate": f"{(seg_wins / len(segment) * 100):.2f}%",
            "net_pnl_percent": f"{sum(t['final_pnl_percent'] for t in segment):.2f}%"
        }

    regime_validation = {
        "trend_regime (ADX > 25)": calc_segment_metrics(trend_regime_trades),
        "range_regime (ADX < 20)": calc_segment_metrics(range_regime_trades)
    }

    # --- 5. REPORT: Feature Importance Report ---
    # قياس مدى قوة ارتباط الخصائص بالـ PnL النهائي رياضياً
    pnls = [t["final_pnl_percent"] for t in trades_matrix]
    feature_importance = {
        "market_regime_adx_correlation": calculate_correlation([t["adx"] for t in trades_matrix], pnls),
        "market_volatility_atr_correlation": calculate_correlation([t["atr"] for t in trades_matrix], pnls),
        "signal_confidence_correlation": calculate_correlation([t["confidence"] for t in trades_matrix], pnls),
        "volume_momentum_correlation": calculate_correlation([t["volume"] for t in trades_matrix], pnls),
        "execution_hour_correlation": calculate_correlation([t["hour"] for t in trades_matrix], pnls)
    }

    return {
        "status": "QUANT_LAB_ANALYSIS_COMPLETE",
        "period": "Past 8 Days (Deterministic Replay Evaluation)",
        "baseline_metrics": {
            "total_market_signals_spotted": total_signals,
            "total_executed_trades": total_trades,
            "successful_trades": wins_count,
            "failed_trades": losses_count,
            "win_rate": f"{((wins_count / total_trades * 100) if total_trades > 0 else 0):.2f}%",
            "true_profit_factor": f"{true_profit_factor:.2f}"
        },
        "quant_research_reports": {
            "1_winner_profile": winner_profile,
            "2_winner_vs_loser_differential": differential_analysis,
            "3_edge_concentration": edge_concentration,
            "4_regime_validation": regime_validation,
            "5_feature_importance_report": feature_importance
        }
    }

@app.route('/')
def dashboard():
    report = analyze_performance()
    return jsonify(report)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
