import os
import time
import threading
import json
import urllib.request
import urllib.parse
import urllib.error
import hmac
import hashlib
import math
from datetime import datetime
from flask import Flask, jsonify

app = Flask(__name__)

# --- الإعدادات العالمية ---
global_data = {}
DATA_FILE = "data.json"
data_lock = threading.Lock()

# إعدادات التداول
RISK_STOP_LOSS_PCT = 0.015       
REWARD_ACTIVATION_PCT = 0.03    
TRAILING_DROP_PCT = 0.005       
MAX_OPEN_POSITIONS = 3          

# المتغيرات البيئية
BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY', 'YOUR_API_KEY_HERE')
BINANCE_SECRET_KEY = os.environ.get('BINANCE_SECRET_KEY', 'YOUR_SECRET_KEY_HERE')
TOKEN = os.environ.get('TOKEN', 'YOUR_TELEGRAM_TOKEN_HERE')
CHAT_ID = os.environ.get('CHAT_ID', '199325566')

# خرائط العملات
COIN_MAPPING = {
    "BTCUSDT": "bitcoin", "ETHUSDT": "ethereum", "SOLUSDT": "solana",
    "LINKUSDT": "chainlink", "ADAUSDT": "cardano", "DOTUSDT": "polkadot",
    "NEARUSDT": "near", "ARBUSDT": "arbitrum", "OPUSDT": "optimism",
    "RENDERUSDT": "render", "BNBUSDT": "binancecoin",   
    "POLUSDT": "polygon", "AVAXUSDT": "avalanche", "ALGOUSDT": "algorand",     
    "ATOMUSDT": "cosmos", "FETUSDT": "fetch-ai", "GRTUSDT": "the-graph",     
    "STXUSDT": "stacks", "FTMUSDT": "fantom", "LTCUSDT": "litecoin"       
}

# الذاكرة المؤقتة
exchange_filters = {}
ema_200_cache = {}

# --- الدوال المساعدة ---

def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10): pass
    except Exception as e: print(f"Telegram Error: {e}")

def binance_signature(query_string, secret_key):
    return hmac.new(secret_key.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()

def send_binance_signed_request(endpoint, method="POST", params={}):
    if BINANCE_API_KEY == 'YOUR_API_KEY_HERE':
        return {"mock_success": True, "executedQty": params.get("quoteOrderQty", 10)/100.0, "status": "FILLED"}
    
    base_url = "https://api.binance.com"
    params['timestamp'] = int(time.time() * 1000)
    query_string = urllib.parse.urlencode(params)
    signature = binance_signature(query_string, BINANCE_SECRET_KEY)
    full_url = f"{base_url}{endpoint}?{query_string}&signature={signature}"
    
    req = urllib.request.Request(full_url, method=method)
    req.add_header('X-MBX-APIKEY', BINANCE_API_KEY)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"⚠️ Binance API Error ({endpoint}): {e}")
        return {"error": str(e)}

def fetch_exchange_filters():
    global exchange_filters
    try:
        url = "https://api.binance.com/api/v3/exchangeInfo"
        with urllib.request.urlopen(url, timeout=15) as response:
            data = json.loads(response.read().decode())
            for s_data in data['symbols']:
                if s_data['symbol'] in COIN_MAPPING:
                    for f in s_data['filters']:
                        if f['filterType'] == 'LOT_SIZE':
                            exchange_filters[s_data['symbol']] = {"stepSize": float(f['stepSize'])}
    except Exception as e: print(f"خطأ جلب الفلاتر: {e}")

def format_step_size(symbol, quantity):
    if symbol not in exchange_filters: return round(quantity, 4)
    step = exchange_filters[symbol]['stepSize']
    return math.floor(quantity / step) * step

def get_binance_ema200(symbol):
    current_time = time.time()
    if symbol in ema_200_cache and (current_time - ema_200_cache[symbol]["timestamp"] < 1800):
        return ema_200_cache[symbol]["value"]
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=200"
        with urllib.request.urlopen(url, timeout=10) as response:
            klines = json.loads(response.read().decode())
            closes = [float(k[4]) for k in klines]
            k = 2 / (200 + 1)
            ema = closes[0]
            for price in closes[1:]: ema = (price * k) + (ema * (1 - k))
            ema_200_cache[symbol] = {"value": ema, "timestamp": current_time}
            return ema
    except: return None

# --- دوال التقارير ---

def generate_report_table(stats_key, title, period_value):
    lines = [f"📊 *{title}*", f"📅 {period_value}\n", "```", "COIN     | W | L | PROFIT", "-----------------------------"]
    coin_stats = global_data.get(stats_key, {}).get("coins", {})
    t_wins, t_loss, t_profit = 0, 0, 0.0
    for c_id, s in coin_stats.items():
        ticker = c_id[:6].upper()
        t_wins += s.get("wins", 0); t_loss += s.get("losses", 0); t_profit += s.get("net_profit", 0.0)
        lines.append(f"{ticker:<8} | {s.get('wins',0):<1} | {s.get('losses',0):<1} | {s.get('net_profit',0):+.2f}")
    lines.append("-----------------------------")
    lines.append(f"TOTAL    | {t_wins} | {t_loss} | {t_profit:+.2f}$")
    lines.append("```")
    return "\n".join(lines)

def record_transaction_stats(cid, is_win, amount):
    for key in ["global_stats", "daily_stats", "monthly_stats"]:
        if cid not in global_data[key].get("coins", {}):
            if key != "global_stats": global_data[key]["coins"][cid] = {"wins": 0, "losses": 0, "net_profit": 0.0}
        
        if is_win: global_data[key]["wins"] += 1; 
        else: global_data[key]["losses"] += 1
        global_data[key]["net_profit"] += amount
        
        if key != "global_stats":
            if is_win: global_data[key]["coins"][cid]["wins"] += 1
            else: global_data[key]["coins"][cid]["losses"] += 1
            global_data[key]["coins"][cid]["net_profit"] += amount

# --- الحلقة الرئيسية ---

@app.route('/')
def home():
    return jsonify({"status": "Bot Active"})

def run_trading_bot():
    global global_data
    fetch_exchange_filters()
    
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f: global_data = json.load(f)
    else:
        global_data = {"global_stats":{"wins":0,"losses":0,"net_profit":0.0}, "daily_stats":{"date":"none","wins":0,"losses":0,"net_profit":0.0,"coins":{}}, "monthly_stats":{"month":"none","wins":0,"losses":0,"net_profit":0.0,"coins":{}}}

    send_telegram("🚀 البوت بدأ العمل بنظام الأمان الكامل!")

    while True:
        try:
            curr_d = datetime.now().strftime("%Y-%m-%d")
            curr_m = datetime.now().strftime("%Y-%m")
            save_needed = False
            
            with data_lock:
                # تحديث التواريخ
                if global_data["monthly_stats"]["month"] != curr_m:
                    send_telegram(generate_report_table("monthly_stats", "التقرير الشهري", global_data["monthly_stats"]["month"]))
                    global_data["monthly_stats"] = {"month": curr_m, "wins":0, "losses":0, "net_profit":0.0, "coins":{}}
                    save_needed = True
                if global_data["daily_stats"]["date"] != curr_d:
                    send_telegram(generate_report_table("daily_stats", "التقرير اليومي", global_data["daily_stats"]["date"]))
                    global_data["daily_stats"] = {"date": curr_d, "wins":0, "losses":0, "net_profit":0.0, "coins":{}}
                    save_needed = True

            # جلب الأسعار
            url = "https://api.binance.com/api/v3/ticker/price"
            with urllib.request.urlopen(url, timeout=15) as f: ticker_data = json.loads(f.read().decode())
            prices = {COIN_MAPPING[item['symbol']]: float(item['price']) for item in ticker_data if item['symbol'] in COIN_MAPPING}
            
            with data_lock:
                for cid, price in prices.items():
                    if cid not in global_data: global_data[cid] = {"history":[], "held":0.0, "buy_price":0.0, "is_holding":False, "trailing":False, "highest":0.0, "break_even":False, "partial":False, "last_t":0}
                    
                    # تحديث التاريخ
                    if time.time() - global_data[cid]["last_t"] >= 300:
                        global_data[cid]["history"] = (global_data[cid]["history"] + [price])[-20:]
                        global_data[cid]["last_t"] = time.time()
                        save_needed = True

                    symbol_binance = [k for k, v in COIN_MAPPING.items() if v == cid][0]
                    
                    if global_data[cid]["is_holding"]:
                        # منطق البيع (الوقف، الربح، المطاردة)
                        buy_p = global_data[cid]['buy_price']
                        profit = (price - buy_p) / buy_p
                        
                        # Break Even
                        if not global_data[cid]["break_even"] and profit >= 0.01:
                            global_data[cid]["break_even"] = True
                            save_needed = True
                            
                        # Partial Profit
                        if not global_data[cid]["partial"] and profit >= 0.015:
                            half = format_step_size(symbol_binance, global_data[cid]['held'] * 0.5)
                            res = send_binance_signed_request("/api/v3/order", "POST", {"symbol":symbol_binance, "side":"SELL", "type":"MARKET", "quantity":half})
                            if "error" not in res:
                                record_transaction_stats(cid, True, (price-buy_p)*half)
                                global_data[cid]["held"] -= half
                                global_data[cid]["partial"] = True
                                save_needed = True
                        
                        # Trailing Stop
                        if not global_data[cid]["trailing"] and profit >= REWARD_ACTIVATION_PCT:
                            global_data[cid]["trailing"] = True
                            global_data[cid]["highest"] = price
                        
                        if global_data[cid]["trailing"]:
                            if price > global_data[cid]["highest"]: global_data[cid]["highest"] = price
                            if price <= global_data[cid]["highest"] * (1 - TRAILING_DROP_PCT):
                                # Sell All
                                qty = format_step_size(symbol_binance, global_data[cid]['held'])
                                res = send_binance_signed_request("/api/v3/order", "POST", {"symbol":symbol_binance, "side":"SELL", "type":"MARKET", "quantity":qty})
                                if "error" not in res:
                                    record_transaction_stats(cid, True, (price-buy_p)*qty)
                                    global_data[cid].update({'held':0.0, 'is_holding':False, 'trailing':False, 'partial':False, 'break_even':False})
                                    save_needed = True
                        
                        # Stop Loss
                        elif price <= buy_p * (1.001 if global_data[cid]["break_even"] else (1 - RISK_STOP_LOSS_PCT)):
                            qty = format_step_size(symbol_binance, global_data[cid]['held'])
                            res = send_binance_signed_request("/api/v3/order", "POST", {"symbol":symbol_binance, "side":"SELL", "type":"MARKET", "quantity":qty})
                            if "error" not in res:
                                record_transaction_stats(cid, False, (price-buy_p)*qty)
                                global_data[cid].update({'held':0.0, 'is_holding':False, 'trailing':False, 'partial':False, 'break_even':False})
                                save_needed = True

                    else:
                        # منطق الشراء
                        h = global_data[cid]["history"]
                        if len(h) < 20: continue
                        sma = sum(h)/len(h)
                        std = (sum((x-sma)**2 for x in h)/len(h))**0.5
                        if price <= sma - std:
                            ema200 = get_binance_ema200(symbol_binance)
                            if ema200 and price >= ema200:
                                amt = 25.0 if (std/sma)>0.015 else 50.0
                                res = send_binance_signed_request("/api/v3/order", "POST", {"symbol":symbol_binance, "side":"BUY", "type":"MARKET", "quoteOrderQty":amt})
                                if "error" not in res:
                                    global_data[cid].update({'held':float(res.get('executedQty', 0)), 'buy_price':price, 'is_holding':True})
                                    save_needed = True

            if save_needed:
                with open(DATA_FILE, 'w') as f: json.dump(global_data, f)
            time.sleep(30)
        except Exception as e:
            print(f"Loop Error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    threading.Thread(target=run_trading_bot, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
