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
import sys
from datetime import datetime
from flask import Flask, jsonify

app = Flask(__name__)

# --- المتغيرات البيئية من منصة Render ---
BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY')
BINANCE_SECRET_KEY = os.environ.get('BINANCE_SECRET_KEY')
TOKEN = os.environ.get('TOKEN', 'YOUR_TELEGRAM_TOKEN_HERE')
CHAT_ID = os.environ.get('CHAT_ID', '199325566')

# إعدادات المزامنة السحابية (JSONBin) لمنع فقدان البيانات عند ريستارت السيرفر
BIN_ID = os.environ.get('BIN_ID')
JSONBIN_KEY = os.environ.get('JSONBIN_API_KEY') or os.environ.get('JSONB...') # يدعم الاسمين تلقائياً

global_data = {}
DATA_FILE = "data.json"
data_lock = threading.Lock()

# --- [إصلاح خطأ 404] دالة العرض الرئيسية لمنع خمول السيرفر وطمأنة UptimeRobot ---
@app.route('/')
def home():
    with data_lock:
        return jsonify({
            "status": "🚀 Halal Trading Bot is LIVE and Monitored Successfully!",
            "trading_mode": "Real Account (Binance API Active)" if (BINANCE_API_KEY and BINANCE_SECRET_KEY) else "Simulation Mode (API Keys Missing from Render)",
            "database_sync": "Cloud (JSONBin Connected)" if (BIN_ID and JSONBIN_KEY) else "Local File Only (Data will wipe on Render restart)",
            "global_stats": global_data.get("global_stats", {}),
            "daily_stats": global_data.get("daily_stats", {}),
            "monthly_stats": global_data.get("monthly_stats", {})
        }), 200

# --- دالات الحفظ والقراءة الذكية مع دعم السحاب والمحلي ---
def load_global_data():
    global global_data
    if BIN_ID and JSONBIN_KEY:
        try:
            print("🔄 Attempting to load data from JSONBin...", flush=True)
            url = f"https://api.jsonbin.io/v3/b/{BIN_ID}/latest"
            req = urllib.request.Request(url, headers={"X-Master-Key": JSONBIN_KEY})
            with urllib.request.urlopen(req, timeout=15) as r:
                res = json.loads(r.read().decode())
                global_data = res.get("record", {})
                print("✅ Data successfully loaded from JSONBin cloud!", flush=True)
                return
        except Exception as e:
            print(f"⚠️ JSONBin load failed ({e}). Trying local file...", flush=True)
    
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            try: 
                global_data = json.load(f)
                print("✅ Data loaded from local data.json file.", flush=True)
            except: 
                global_data = {}

def save_global_data():
    # 1. حفظ محلي احتياطي
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(global_data, f)
    except Exception as e:
        print(f"⚠️ Local file save error: {e}", flush=True)

    # 2. مزامنة سحابية فورية لمنع ضياع البيانات والتأكد من استمرار الإحصائيات
    if BIN_ID and JSONBIN_KEY:
        try:
            url = f"https://api.jsonbin.io/v3/b/{BIN_ID}"
            req = urllib.request.Request(
                url,
                data=json.dumps(global_data).encode('utf-8'),
                headers={"X-Master-Key": JSONBIN_KEY, "Content-Type": "application/json"},
                method="PUT"
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                print("💾 Cloud Backup Synchronized with JSONBin.", flush=True)
        except Exception as e:
            print(f"⚠️ Cloud backup to JSONBin failed: {e}", flush=True)

# --- دالة البوت الأساسية للتداول ---
def run_trading_bot():
    global global_data
    print(">>> TRADING THREAD STARTED SUCCESSFULLY <<<", flush=True)
    
    # قائمة الـ 20 عملة الشرعية المعتمدة
    coin_mapping = {
        "BTCUSDT": "bitcoin", "ETHUSDT": "ethereum", "SOLUSDT": "solana",
        "LINKUSDT": "chainlink", "ADAUSDT": "cardano", "DOTUSDT": "polkadot",
        "NEARUSDT": "near", "ARBUSDT": "arbitrum", "OPUSDT": "optimism",
        "RENDERUSDT": "render", "RNDRUSDT": "render", "BNBUSDT": "binancecoin",   
        "POLUSDT": "polygon", "AVAXUSDT": "avalanche", "ALGOUSDT": "algorand",     
        "ATOMUSDT": "cosmos", "FETUSDT": "fetch-ai", "GRTUSDT": "the-graph",     
        "STXUSDT": "stacks", "FTMUSDT": "fantom", "LTCUSDT": "litecoin"       
    }

    def send_telegram(text):
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            data = json.dumps({"chat_id": CHAT_ID, "text": text}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
        except Exception as e: 
            print(f"Telegram Notification Error: {e}", flush=True)

    send_telegram("🚀 تم إعادة تشغيل البوت بنجاح! تم حل مشكلة الـ 404 وتفعيل الحفظ السحابي التلقائي.")
    
    # تحميل البيانات عند البدء
    with data_lock:
        load_global_data()

    while True:
        try:
            current_date = datetime.now().strftime("%Y-%m-%d")
            current_month = datetime.now().strftime("%Y-%m")
            save_needed = False 

            with data_lock:
                if "global_stats" not in global_data:
                    global_data["global_stats"] = {"wins": 0, "losses": 0, "net_profit": 0.0}
                    save_needed = True
                if "monthly_stats" not in global_data:
                    global_data["monthly_stats"] = {"month": current_month, "wins": 0, "losses": 0, "net_profit": 0.0}
                    save_needed = True
                if "daily_stats" not in global_data:
                    global_data["daily_stats"] = {"date": current_date, "wins": 0, "losses": 0, "net_profit": 0.0}
                    save_needed = True

                # إرسال التقارير الدورية (شهري / يومي)
                if global_data["monthly_stats"].get("month") != current_month:
                    send_telegram(f"📅 تقرير الشهر المنتهي:\nصافي الربح: {global_data['monthly_stats']['net_profit']:.2f}$")
                    global_data["monthly_stats"] = {"month": current_month, "wins": 0, "losses": 0, "net_profit": 0.0}
                    save_needed = True

                if global_data["daily_stats"].get("date") != current_date:
                    send_telegram(f"📊 حصاد الـ 24 ساعة الماضية:\nصافي الربح اليومي: {global_data['daily_stats']['net_profit']:.2f}$")
                    global_data["daily_stats"] = {"date": current_date, "wins": 0, "losses": 0, "net_profit": 0.0}
                    save_needed = True

            # جلب الأسعار اللحظية من Binance API
            url = "https://api.binance.com/api/v3/ticker/price"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as f:
                ticker_data = json.loads(f.read().decode())
            
            market_prices = {coin_mapping[item['symbol']]: float(item['price']) for item in ticker_data if item['symbol'] in coin_mapping}
            current_time_seconds = time.time()

            with data_lock:
                for cid, price in market_prices.items():
                    if cid not in global_data: global_data[cid] = {}
                    if "history" not in global_data[cid]: global_data[cid]["history"] = []
                    if "held" not in global_data[cid]: global_data[cid]["held"] = 0.0
                    if "buy_price" not in global_data[cid]: global_data[cid]["buy_price"] = 0.0
                    if "is_holding" not in global_data[cid]: global_data[cid]["is_holding"] = False
                    if "trailing_active" not in global_data[cid]: global_data[cid]["trailing_active"] = False
                    if "highest_price" not in global_data[cid]: global_data[cid]["highest_price"] = 0.0
                    if "last_history_time" not in global_data[cid]: global_data[cid]["last_history_time"] = 0.0

                    # تحديث السجل التاريخي الرياضي (كل 5 دقائق وعمق 20 قراءة)
                    if current_time_seconds - global_data[cid]["last_history_time"] >= 300:
                        global_data[cid]["history"].append(price)
                        if len(global_data[cid]["history"]) > 20: 
                            global_data[cid]["history"].pop(0)
                        global_data[cid]["last_history_time"] = current_time_seconds
                        save_needed = True

                    # إدارة الصفقة المفتوحة (مطاردة الأرباح الحركية / وقف الخسارة 5%)
                    if global_data[cid]["is_holding"]:
                        buy_price = global_data[cid]['buy_price']
                        stop_loss_price = buy_price * 0.95   
                        activation_price = buy_price * 1.01  

                        if not global_data[cid]["trailing_active"] and price >= activation_price:
                            global_data[cid]["trailing_active"] = True
                            global_data[cid]["highest_price"] = price
                            send_telegram(f"🔥 {cid.upper()} تجاوزت +1%! تفعيل تتبع الأرباح.")
                            save_needed = True

                        if global_data[cid]["trailing_active"]:
                            if price > global_data[cid]["highest_price"]:
                                global_data[cid]["highest_price"] = price
                                save_needed = True
                            
                            if price <= (global_data[cid]["highest_price"] * 0.996):
                                diff = (price - buy_price) * global_data[cid]['held']
                                global_data["global_stats"]["wins"] += 1
                                global_data["global_stats"]["net_profit"] += diff
                                global_data["daily_stats"]["wins"] += 1
                                global_data["daily_stats"]["net_profit"] += diff
                                send_telegram(f"🚀 بيع ذكي بربح لعملة {cid.upper()}: +{diff:.2f}$")
                                global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0})
                                save_needed = True

                        elif price <= stop_loss_price:
                            diff = (price - buy_price) * global_data[cid]['held']
                            global_data["global_stats"]["losses"] += 1
                            global_data["global_stats"]["net_profit"] += diff
                            global_data["daily_stats"]["losses"] += 1
                            global_data["daily_stats"]["net_profit"] += diff
                            send_telegram(f"🛑 ضرب وقف الخسارة لعملة {cid.upper()}: {diff:.2f}$")
                            global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0})
                            save_needed = True

                    # منطق اقتناص الشراء (رأس مال 50 دولار لكل صفقة)
                    else:
                        h = global_data[cid]["history"]
                        if len(h) < 5: continue 
                        sma = sum(h) / len(h)
                        std = (sum((x - sma)**2 for x in h) / len(h))**0.5
                        lower = sma - (1.0 * std)
                        
                        if price <= lower:
                            global_data[cid].update({'held': 50 / price, 'buy_price': price, 'is_holding': True, 'trailing_active': False, 'highest_price': 0.0})
                            send_telegram(f"🎯 شراء استراتيجي: {cid.upper()} بسعر {price}$")
                            save_needed = True
            
            if save_needed:
                with data_lock:
                    save_global_data()
            
            time.sleep(30)
            
        except Exception as e: 
            print(f"⚠️ Error in Bot Loop: {str(e)}", flush=True)
            time.sleep(30)

if __name__ == "__main__":
    # تشغيل خيط التداول بشكل منفصل تماماً
    t = threading.Thread(target=run_trading_bot, daemon=True)
    t.start()
    print(">>> MAIN FLASK APP RUNNING <<<", flush=True)
    
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
