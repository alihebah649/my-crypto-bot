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
EMA_TOLERANCE = 0.995           # سماحية 0.5% تحت الـ EMA

# المتغيرات البيئية (تأكد من إضافتها في Render)
BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY', 'YOUR_API_KEY_HERE')
BINANCE_SECRET_KEY = os.environ.get('BINANCE_SECRET_KEY', 'YOUR_SECRET_KEY_HERE')
TOKEN = os.environ.get('TOKEN', 'YOUR_TELEGRAM_TOKEN_HERE')
CHAT_ID = os.environ.get('CHAT_ID', '199325566')

COIN_MAPPING = {
    "BTCUSDT": "bitcoin", "ETHUSDT": "ethereum", "SOLUSDT": "solana",
    "LINKUSDT": "chainlink", "ADAUSDT": "cardano", "DOTUSDT": "polkadot",
    "NEARUSDT": "near", "ARBUSDT": "arbitrum", "OPUSDT": "optimism",
    "RENDERUSDT": "render", "BNBUSDT": "binancecoin",   
    "POLUSDT": "polygon", "AVAXUSDT": "avalanche", "ALGOUSDT": "algorand",     
    "ATOMUSDT": "cosmos", "FETUSDT": "fetch-ai", "GRTUSDT": "the-graph",     
    "STXUSDT": "stacks", "FTMUSDT": "fantom", "LTCUSDT": "litecoin"       
}

exchange_filters = {}
ema_cache = {}

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

def get_binance_ema(symbol, period=100):
    current_time = time.time()
    cache_key = f"{symbol}_{period}"
    if cache_key in ema_cache and (current_time - ema_cache[cache_key]["timestamp"] < 1800):
        return ema_cache[cache_key]["value"]
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit={period}"
        with urllib.request.urlopen(url, timeout=10) as response:
            klines = json.loads(response.read().decode())
            closes = [float(k[4]) for k in klines]
            k = 2 / (period + 1)
            ema = closes[0]
            for price in closes[1:]: ema = (price * k) + (ema * (1 - k))
            ema_cache[cache_key] = {"value": ema, "timestamp": current_time}
            return ema
    except: return None

# --- الحلقات ---

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

    send_telegram("🚀 البوت بدأ العمل (وضع التشخيص)!")

    while True:
        try:
            curr_d = datetime.now().strftime("%Y-%m-%d")
            curr_m = datetime.now().strftime("%Y-%m")
            save_needed = False
            
            # (منطق التقارير والأسعار ... تم اختصاره لتوفير المساحة، هو نفس المنطق السابق)
            url = "https://api.binance.com/api/v3/ticker/price"
            with urllib.request.urlopen(url, timeout=15) as f: ticker_data = json.loads(f.read().decode())
            prices = {COIN_MAPPING[item['symbol']]: float(item['price']) for item in ticker_data if item['symbol'] in COIN_MAPPING}
            
            with data_lock:
                for cid, price in prices.items():
                    if cid not in global_data: global_data[cid] = {"history":[], "held":0.0, "buy_price":0.0, "is_holding":False, "trailing":False, "highest":0.0, "break_even":False, "partial":False, "last_t":0}
                    
                    if time.time() - global_data[cid]["last_t"] >= 300:
                        global_data[cid]["history"] = (global_data[cid]["history"] + [price])[-20:]
                        global_data[cid]["last_t"] = time.time()
                        save_needed = True

                    symbol_binance = [k for k, v in COIN_MAPPING.items() if v == cid][0]
                    
                    if global_data[cid]["is_holding"]:
                        # (منطق البيع كما هو...)
                        buy_p = global_data[cid]['buy_price']
                        # ... [نفس كود البيع] ...
                        pass 

                    else:
                        # --- منطق الشراء مع التشخيص ---
                        h = global_data[cid]["history"]
                        
                        # تشخيص: هل البيانات جاهزة؟
                        if len(h) < 20:
                            print(f"DEBUG: {cid} - History warming up ({len(h)}/20)")
                            continue
                            
                        sma = sum(h)/len(h)
                        std = (sum((x-sma)**2 for x in h)/len(h))**0.5
                        
                        # تشخيص: هل السعر منخفض بما يكفي؟
                        if price <= sma - std:
                            ema_val = get_binance_ema(symbol_binance, period=100)
                            
                            # تشخيص: فحص الـ EMA
                            if ema_val and price >= (ema_val * EMA_TOLERANCE):
                                amt = 25.0 if (std/sma)>0.015 else 50.0
                                res = send_binance_signed_request("/api/v3/order", "POST", {"symbol":symbol_binance, "side":"BUY", "type":"MARKET", "quoteOrderQty":amt})
                                if "error" not in res:
                                    global_data[cid].update({'held':float(res.get('executedQty', 0)), 'buy_price':price, 'is_holding':True})
                                    save_needed = True
                            else:
                                print(f"DEBUG: {cid} REJECTED - EMA check failed. Price: {price}, EMA: {ema_val}")
                        else:
                            print(f"DEBUG: {cid} REJECTED - Dip not strong enough. Price: {price}, Target: {sma - std}")

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
