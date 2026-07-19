import json
import time
import os
import requests
from datetime import datetime
from flask import Flask, jsonify

app = Flask(__name__)

# ==========================================
# إعدادات الذاكرة السحابية (JSONBIN) للمسار الحي
# ==========================================
# سحب المفاتيح بالتسميات الدقيقة التي حددتها في بيئة منصة Render
JSONBIN_API_KEY = os.environ.get("JSONBIN_API_KEY")
JSONBIN_BIN_ID = os.environ.get("BIN_ID")  

HEADERS = {
    "X-Master-Key": JSONBIN_API_KEY,
    "Content-Type": "application/json",
    "X-Bin-Meta": "false"
}

# ==========================================
# دوال المسار الحي (Live Trading Journal)
# ==========================================
def load_immutable_journal():
    """تحميل سجل الصفقات غير القابل للتعديل من السحابة"""
    url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        data = response.json() if response.status_code == 200 else {}
        if "journal_registry" not in data: data = {"journal_registry": []}
        return data
    except Exception:
        return {"journal_registry": []}

def save_immutable_journal(journal_data):
    """حفظ وتحديث سجل الصفقات السحابي بأمان"""
    url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
    try:
        requests.put(url, json=journal_data, headers=HEADERS, timeout=10)
        return True
    except Exception:
        return False

def check_market_signal_pure(candles_snapshot):
    """الطبقة الأولى: فحص الإشارة المجردة (Naked Signal Generator)"""
    if len(candles_snapshot) < 2: return "NONE"
    current = candles_snapshot[-2]
    prev = candles_snapshot[-3]
    
    price_change = (current["close"] - prev["close"]) / prev["close"]
    volume_ratio = current["volume"] / prev["volume"] if prev["volume"] > 0 else 1.0
    
    # منطق الدخول الأساسي المستهدف بالاختبار
    if abs(price_change) > 0.002 and volume_ratio > 1.1:
        return "LONG" if price_change > 0 else "SHORT"
    return "NONE"

def reconcile_and_track_trades(journal_registry):
    """الطبقة الثانية: إدارة الصفقات والمصالحة التاريخية (Trade Manager)"""
    assets = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT"]
    fixed_brackets = {"BTCUSDT": 0.45, "LINKUSDT": 0.40, "ETHUSDT": 0.35, "SOLUSDT": 0.50}
    
    # 1. تحديث ومصالحة الصفقات المفتوحة بناءً على حركة السعر الحالية
    for trade in journal_registry:
        if trade["status"] != "OPEN": continue
        symbol = trade["asset"]
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=100"
        try:
            raw_candles = requests.get(url, timeout=10).json()
            historical_candles = [{"timestamp": float(c[0]) / 1000.0, "high": float(c[2]), "low": float(c[3]), "close": float(c[4])} for c in raw_candles]
        except Exception:
            continue
            
        entry_time = trade["entry_timestamp"]
        entry_price = trade["entry_price"]
        tp_price = trade["take_profit_price"]
        sl_price = trade["stop_loss_price"]
        
        active_period = [c for c in historical_candles if c["timestamp"] >= entry_time]
        
        for candle in active_period:
            if trade["status"] != "OPEN": break
            if trade["direction"] == "LONG":
                if candle["low"] <= sl_price:
                    trade["status"], trade["exit_price"], trade["exit_reason"] = "CLOSED", sl_price, "STOP_LOSS"
                elif candle["high"] >= tp_price:
                    trade["status"], trade["exit_price"], trade["exit_reason"] = "CLOSED", tp_price, "TAKE_PROFIT"
            else:
                if candle["high"] >= sl_price:
                    trade["status"], trade["exit_price"], trade["exit_reason"] = "CLOSED", sl_price, "STOP_LOSS"
                elif candle["low"] <= tp_price:
                    trade["status"], trade["exit_price"], trade["exit_reason"] = "CLOSED", tp_price, "TAKE_PROFIT"

    # 2. البحث عن إشارات دخول جديدة للعملات غير المستثمرة حالياً
    for symbol in assets:
        if any(t["asset"] == symbol and t["status"] == "OPEN" for t in journal_registry): continue
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=5"
        try:
            raw_c = requests.get(url, timeout=10).json()
            snapshot = [{"close": float(c[4]), "volume": float(c[5])} for c in raw_c]
        except Exception: continue
            
        signal = check_market_signal_pure(snapshot)
        if signal in ["LONG", "SHORT"]:
            entry_p = float(raw_c[-2][4])
            timestamp_entry = float(raw_c[-2][0]) / 1000.0
            bracket = fixed_brackets.get(symbol, 0.40)
            tp_p = entry_p * (1 + bracket/100) if signal == "LONG" else entry_p * (1 - bracket/100)
            sl_p = entry_p * (1 - bracket/100) if signal == "LONG" else entry_p * (1 + bracket/100)
            
            journal_registry.append({
                "id": int(timestamp_entry * 1000), "asset": symbol, "direction": signal,
                "status": "OPEN", "entry_time": datetime.fromtimestamp(timestamp_entry).strftime("%Y-%m-%d %H:%M:%S"),
                "entry_timestamp": timestamp_entry, "entry_price": entry_p,
                "take_profit_price": tp_p, "stop_loss_price": sl_p,
                "exit_price": None, "exit_reason": None
            })
    return journal_registry

def calculate_analytics(journal_registry):
    """الطبقة الرابعة: محرك التحليلات الإحصائية للمسار الحي (Analytics Engine)"""
    closed = [t for t in journal_registry if t["status"] == "CLOSED"]
    if not closed: return {"message": "No executed data yet. Collecting cold data silently..."}
    wins, gross_profits, gross_losses = 0, 0.0, 0.0
    for t in closed:
        pnl = ((t["exit_price"] - t["entry_price"]) / t["entry_price"] * 100) if t["direction"] == "LONG" else ((t["entry_price"] - t["exit_price"]) / t["entry_price"] * 100)
        if pnl > 0:
            wins += 1; gross_profits += pnl
        else:
            gross_losses += abs(pnl)
    total = len(closed)
    return {
        "total_trades": total,
        "win_rate": f"{(wins / total * 100):.2f}%" if total > 0 else "0.00%",
        "profit_factor": f"{(gross_profits / gross_losses if gross_losses > 0 else gross_profits):.2f}"
    }

# ==========================================
# مسار الاختبار العكسي العميق (The Deep Backtest Engine)
# ==========================================
def fetch_1_year_data(symbol):
    """جلب بيانات سنة كاملة (حوالي 9 طلبات متتالية * 1000 شمعة) لتجاوز قيود البث لـ Binance"""
    all_candles = []
    end_time = int(time.time() * 1000)
    for _ in range(9): 
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=1000&endTime={end_time}"
        try:
            response = requests.get(url, timeout=10)
            data = response.json()
            if not data: break
            all_candles = data + all_candles
            end_time = data[0][0] - 1 
        except Exception: break
        
    return [{"timestamp": c[0], "high": float(c[2]), "low": float(c[3]), "close": float(c[4]), "volume": float(c[5])} for c in all_candles]

@app.route('/deep-test')
def run_deep_edge_test():
    """واجهة الاختبار الصارم للبحث عن الحافة الإحصائية المجردة لآخر عام"""
    assets = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT"]
    fixed_brackets = {"BTCUSDT": 0.45, "LINKUSDT": 0.40, "ETHUSDT": 0.35, "SOLUSDT": 0.50}
    results = {}
    
    for symbol in assets:
        candles = fetch_1_year_data(symbol)
        if len(candles) < 100: continue
        
        bracket = fixed_brackets.get(symbol, 0.40)
        wins, losses = 0, 0
        gross_profit, gross_loss = 0.0, 0.0
        
        # محاكاة حركة السوق التاريخية كرونولوجياً لرصد واستخراج الإشارات
        for i in range(2, len(candles) - 1):
            prev = candles[i-1]
            current = candles[i]
            
            price_change = (current["close"] - prev["close"]) / prev["close"]
            volume_ratio = current["volume"] / prev["volume"] if prev["volume"] > 0 else 1.0
            
            if abs(price_change) > 0.002 and volume_ratio > 1.1:
                direction = "LONG" if price_change > 0 else "SHORT"
                entry_price = current["close"]
                
                # فحص الشموع التالية مباشرة لتحديد نقطة الخروج الدقيقة (Stop-Loss First Principle)
                for j in range(i + 1, len(candles)):
                    future_candle = candles[j]
                    is_closed = False
                    pnl = 0.0
                    
                    if direction == "LONG":
                        if future_candle["low"] <= entry_price * (1 - bracket/100):
                            is_closed, pnl = True, -bracket
                        elif future_candle["high"] >= entry_price * (1 + bracket/100):
                            is_closed, pnl = True, bracket
                    else:
                        if future_candle["high"] >= entry_price * (1 + bracket/100):
                            is_closed, pnl = True, -bracket
                        elif future_candle["low"] <= entry_price * (1 - bracket/100):
                            is_closed, pnl = True, bracket
                            
                    if is_closed:
                        if pnl > 0:
                            wins += 1
                            gross_profit += pnl
                        else:
                            losses += 1
                            gross_loss += abs(pnl)
                        break 
                        
        total_trades = wins + losses
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else gross_profit
        
        avg_win = (gross_profit / wins) if wins > 0 else 0
        avg_loss = (gross_loss / losses) if losses > 0 else 0
        expectancy = ((win_rate / 100) * avg_win) - (((100 - win_rate) / 100) * avg_loss)
        
        results[symbol] = {
            "total_candles_analyzed": len(candles),
            "total_trades_triggered": total_trades,
            "win_rate": f"{win_rate:.2f}%",
            "profit_factor": f"{profit_factor:.2f}",
            "mathematical_expectancy_per_trade": f"{expectancy:.3f}%",
            "edge_evaluation": "POSITIVE EDGE (Viable for filtering)" if expectancy > 0 else "NEGATIVE EDGE (Core logic is flawed)"
        }
        
    return jsonify({
        "status": "DEEP_NAKED_EDGE_TEST_COMPLETED",
        "timeframe": "Approximately 1 Year (1h interval)",
        "methodology": "No indicators, no trailing, raw signal generation vs fixed TP/SL",
        "results_by_asset": results
    })

# ==========================================
# الواجهة الرئيسية (المسار الحي للتداول الصامت)
# ==========================================
@app.route('/')
def main_execution_endpoint():
    """الرابط الرئيسي المستهدف بنبضات UptimeRobot لجمع البيانات الحية الموثوقة بصمت"""
    journal_data = load_immutable_journal()
    journal_data["journal_registry"] = reconcile_and_track_trades(journal_data["journal_registry"])
    save_immutable_journal(journal_data)
    
    return jsonify({
        "status": "LIVE_JOURNAL_ACTIVE",
        "live_analytics": calculate_analytics(journal_data["journal_registry"]),
        "active_positions": [t for t in journal_data["journal_registry"] if t["status"] == "OPEN"]
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
