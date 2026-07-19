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
JSONBIN_API_KEY = os.environ.get("JSONBIN_API_KEY")
JSONBIN_BIN_ID = os.environ.get("BIN_ID")  

HEADERS = {
    "X-Master-Key": JSONBIN_API_KEY,
    "Content-Type": "application/json",
    "X-Bin-Meta": "false"
}

# ==========================================
# محرك الفلسفات والاستراتيجيات (The Strategy Matrix)
# ==========================================

def strategy_naked_noise(candles, idx):
    """1. الاستراتيجية القديمة المستندة للنسب المئوية الصغيرة"""
    if idx < 2: return "NONE"
    current = candles[idx]
    prev = candles[idx-1]
    price_change = (current["close"] - prev["close"]) / prev["close"]
    volume_ratio = current["volume"] / prev["volume"] if prev["volume"] > 0 else 1.0
    if abs(price_change) > 0.002 and volume_ratio > 1.1:
        return "LONG" if price_change > 0 else "SHORT"
    return "NONE"

def strategy_donchian_breakout(candles, idx, window=20):
    """2. استراتيجية اختراق النطاق السعري التاريخي (Breakout Strategy)"""
    if idx < window: return "NONE"
    slice_candles = candles[idx-window:idx]
    highest_high = max(c["high"] for c in slice_candles)
    lowest_low = min(c["low"] for c in slice_candles)
    current_close = candles[idx]["close"]
    
    if current_close > highest_high: return "LONG"
    if current_close < lowest_low: return "SHORT"
    return "NONE"

def strategy_mean_reversion_zscore(candles, idx, window=20):
    """3. استراتيجية الارتداد من التطرفات الإحصائية (Mean Reversion)"""
    if idx < window: return "NONE"
    slice_candles = candles[idx-window:idx]
    closes = [c["close"] for c in slice_candles]
    
    mean = sum(closes) / window
    variance = sum((x - mean) ** 2 for x in closes) / window
    std_dev = variance ** 0.5
    if std_dev == 0: return "NONE"
    
    current_close = candles[idx]["close"]
    z_score = (current_close - mean) / std_dev
    
    if z_score < -2.0: return "LONG"   # السعر منخفض جداً إحصائياً - توقع ارتداد لأعلى
    if z_score > 2.0: return "SHORT"   # السعر مرتفع جداً إحصائياً - توقع ارتداد لأسفل
    return "NONE"

# ==========================================
# البنية التحتية للمسار الحي والمصالحات
# ==========================================
def load_immutable_journal():
    url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        data = response.json() if response.status_code == 200 else {}
        if "journal_registry" not in data: data = {"journal_registry": []}
        return data
    except Exception: return {"journal_registry": []}

def save_immutable_journal(journal_data):
    url = f"https://api.jsonbin.io/v3/b/{JSONBIN_BIN_ID}"
    try:
        requests.put(url, json=journal_data, headers=HEADERS, timeout=10)
        return True
    except Exception: return False

def reconcile_and_track_trades(journal_registry):
    assets = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT"]
    fixed_brackets = {"BTCUSDT": 0.45, "LINKUSDT": 0.40, "ETHUSDT": 0.35, "SOLUSDT": 0.50}
    
    for trade in journal_registry:
        if trade["status"] != "OPEN": continue
        symbol = trade["asset"]
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=50"
        try:
            raw_candles = requests.get(url, timeout=10).json()
            historical_candles = [{"timestamp": float(c[0]) / 1000.0, "high": float(c[2]), "low": float(c[3]), "close": float(c[4])} for c in raw_candles]
        except Exception: continue
            
        entry_time = trade["entry_timestamp"]
        tp_price = trade["take_profit_price"]
        sl_price = trade["stop_loss_price"]
        
        active_period = [c for c in historical_candles if c["timestamp"] >= entry_time]
        for candle in active_period:
            if trade["status"] != "OPEN": break
            if trade["direction"] == "LONG":
                if candle["low"] <= sl_price: trade["status"], trade["exit_price"], trade["exit_reason"] = "CLOSED", sl_price, "STOP_LOSS"
                elif candle["high"] >= tp_price: trade["status"], trade["exit_price"], trade["exit_reason"] = "CLOSED", tp_price, "TAKE_PROFIT"
            else:
                if candle["high"] >= sl_price: trade["status"], trade["exit_price"], trade["exit_reason"] = "CLOSED", sl_price, "STOP_LOSS"
                elif candle["low"] <= tp_price: trade["status"], trade["exit_price"], trade["exit_reason"] = "CLOSED", tp_price, "TAKE_PROFIT"

    for symbol in assets:
        if any(t["asset"] == symbol and t["status"] == "OPEN" for t in journal_registry): continue
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=5"
        try:
            raw_c = requests.get(url, timeout=10).json()
            snapshot = [{"close": float(c[4]), "volume": float(c[5])} for c in raw_c]
        except Exception: continue
            
        signal = strategy_naked_noise(snapshot, len(snapshot)-1)
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

# ==========================================
# محرك المحاكاة الصارم والمعدل (Rigorous Testing Engine)
# ==========================================
def fetch_1_year_data(symbol):
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

def backtest_engine(candles, strategy_name, strategy_func, bracket):
    """محرك محاكاة احترافي يعالج قيوود الوقت، الانزلاق، التكاليف، ويمنع تداخل الصفقات"""
    wins, losses = 0, 0
    gross_profit, gross_loss = 0.0, 0.0
    
    MAX_HOLD_HOURS = 48         # حل مشكلة الصفقات اللانهائية
    FRICTION_DRAG = 0.3         # حل مشكلة الرسوم والانزلاق السعري الإجمالي (0.3% من قيمة الصفقة)
    
    i = 20 # نبدأ بعد توفير نافذة المؤشرات
    while i < len(candles) - 1:
        signal = strategy_func(candles, i)
        if signal == "NONE":
            i += 1
            continue
            
        # كسر انحياز النظرة المستقبلية عبر فرض سعر دخول واقعي
        entry_price = candles[i]["close"]
        direction = signal
        
        tp_price = entry_price * (1 + bracket/100) if direction == "LONG" else entry_price * (1 - bracket/100)
        sl_price = entry_price * (1 - bracket/100) if direction == "LONG" else entry_price * (1 + bracket/100)
        
        trade_closed = False
        final_pnl = 0.0
        max_future_idx = min(i + 1 + MAX_HOLD_HOURS, len(candles))
        exit_idx = max_future_idx - 1
        
        # فحص حركة السعر المستقبلية خطوة بخطوة
        for j in range(i + 1, max_future_idx):
            future_candle = candles[j]
            if direction == "LONG":
                if future_candle["low"] <= sl_price:
                    trade_closed, final_pnl, exit_idx = True, -bracket, j
                    break
                elif future_candle["high"] >= tp_price:
                    trade_closed, final_pnl, exit_idx = True, bracket, j
                    break
            else:
                if future_candle["high"] >= sl_price:
                    trade_closed, final_pnl, exit_idx = True, -bracket, j
                    break
                elif future_candle["low"] <= tp_price:
                    trade_closed, final_pnl, exit_idx = True, bracket, j
                    break
                    
        # إغلاق إجباري عند انتهاء الوقت (Time-Decay Force Close)
        if not trade_closed and max_future_idx < len(candles):
            trade_closed = True
            exit_idx = max_future_idx - 1
            close_price = candles[exit_idx]["close"]
            if direction == "LONG":
                final_pnl = ((close_price - entry_price) / entry_price) * 100
            else:
                final_pnl = ((entry_price - close_price) / entry_price) * 100
                
        if trade_closed:
            # تطبيق الاحتكاك المالي الفعلي للرسوم والانزلاق
            final_pnl -= FRICTION_DRAG
            if final_pnl > 0:
                wins += 1; gross_profit += final_pnl
            else:
                losses += 1; gross_loss += abs(final_pnl)
                
            # قفزة رشيقة للمؤشر: تمنع تداخل الصفقات وتسحب الأداء بأعلى سرعة معالجة
            i = exit_idx + 1
        else:
            i += 1
            
    total_trades = wins + losses
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else gross_profit
    avg_win = (gross_profit / wins) if wins > 0 else 0
    avg_loss = (gross_loss / losses) if losses > 0 else 0
    expectancy = ((win_rate / 100) * avg_win) - (((100 - win_rate) / 100) * avg_loss)
    
    return {
        "total_trades": total_trades,
        "win_rate": f"{win_rate:.2f}%",
        "profit_factor": f"{profit_factor:.2f}",
        "expectancy_per_trade": f"{expectancy:.3f}%",
        "evaluation": "VIABLE EDGE" if expectancy > 0 and total_trades > 20 else "FLAWED LOGIC"
    }

@app.route('/deep-test')
def run_strategy_lab():
    """المختبر الشامل: تشغيل الفلسفات الثلاثة معاً ومقارنتها فورياً"""
    assets = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "LINKUSDT"]
    fixed_brackets = {"BTCUSDT": 0.45, "LINKUSDT": 0.40, "ETHUSDT": 0.35, "SOLUSDT": 0.50}
    
    strategies_to_test = [
        {"name": "1_Naked_Noise_Baseline", "func": strategy_naked_noise},
        {"name": "2_Donchian_Breakout", "func": strategy_donchian_breakout},
        {"name": "3_Mean_Reversion_ZScore", "func": strategy_mean_reversion_zscore}
    ]
    
    lab_dashboard = {}
    
    for symbol in assets:
        candles = fetch_1_year_data(symbol)
        if len(candles) < 100: continue
        bracket = fixed_brackets.get(symbol, 0.40)
        
        lab_dashboard[symbol] = {}
        for strat in strategies_to_test:
            metrics = backtest_engine(candles, strat["name"], strat["func"], bracket)
            lab_dashboard[symbol][strat["name"]] = metrics
            
    return jsonify({
        "status": "STRATEGY_LAB_SIMULATION_COMPLETED",
        "simulation_rules": {
            "time_decay_limit": "Max 48 Hours per trade",
            "friction_drag": "0.3% round-trip absolute PnL deduction (Fees + Slippage)",
            "execution": "No overlap, jump index to exit candle"
        },
        "comparative_matrix": lab_dashboard
    })

@app.route('/')
def main_execution_endpoint():
    journal_data = load_immutable_journal()
    journal_data["journal_registry"] = reconcile_and_track_trades(journal_data["journal_registry"])
    save_immutable_journal(journal_data)
    
    return jsonify({
        "status": "LIVE_JOURNAL_ACTIVE",
        "message": "Collecting data silently in the background...",
        "active_positions": [t for t in journal_data["journal_registry"] if t["status"] == "OPEN"]
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
