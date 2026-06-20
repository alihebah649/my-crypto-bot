import os
import time
import threading
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime
from flask import Flask, jsonify

app = Flask(__name__)

# --- المتغيرات البيئية ---
BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY')
BINANCE_SECRET_KEY = os.environ.get('BINANCE_SECRET_KEY')
TOKEN = os.environ.get('TOKEN', 'YOUR_TELEGRAM_TOKEN_HERE')
CHAT_ID = os.environ.get('CHAT_ID', '199325566')
BIN_ID = os.environ.get('BIN_ID')
JSONBIN_KEY = os.environ.get('JSONBIN_API_KEY') or os.environ.get('JSONBIN_KEY')

global_data = {}
DATA_FILE = "data.json"
data_lock = threading.Lock()

# --- إعدادات إدارة المخاطر المحسنة والمثبتة ---
RISK_CONFIG = {
    'entry_amount_usd': 50.0,      # تم تثبيت مبلغ الدخول للصفقة الواحدة إلى 50 دولار بناءً على رغبتك
    'stop_loss': 0.025,            # 2.5% وقف خسارة لحماية رأس المال
    'trailing_activation': 0.015,  # 1.5% تفعيل التتبع الحركي لبدء حجز الأرباح
    'trailing_stop': 0.005,        # 0.5% حماية الأرباح عند الارتداد من القمة
    'initial_capital': 1000.0      # رأس المال الافتراضي الأولي لحساب النمو
}

# --- دالة تحديث الإحصائيات المتقدمة لـ Flask ---
@app.route('/')
def home():
    with data_lock:
        stats = global_data.get("global_stats", {})
        total_trades = stats.get('wins', 0) + stats.get('losses', 0)
        win_rate = (stats.get('wins', 0) / total_trades * 100) if total_trades > 0 else 0
        
        avg_win = stats.get('total_win_amount', 0) / stats.get('wins', 1) if stats.get('wins', 0) > 0 else 0
        avg_loss = stats.get('total_loss_amount', 0) / stats.get('losses', 1) if stats.get('losses', 0) > 0 else 0
        profit_factor = (stats.get('total_win_amount', 0) / stats.get('total_loss_amount', 1)) if stats.get('total_loss_amount', 0) > 0 else 0
        
        current_capital = RISK_CONFIG['initial_capital'] + stats.get('net_profit', 0.0)
        
        return jsonify({
            "status": "🚀 Halal Trading Bot with Advanced Risk Management Running Live",
            "risk_config": RISK_CONFIG,
            "account_summary": {
                "initial_capital": f"${RISK_CONFIG['initial_capital']:.2f}",
                "current_capital": f"${current_capital:.2f}",
                "net_profit": f"${stats.get('net_profit', 0.0):.2f}"
            },
            "performance": {
                "total_trades": total_trades,
                "win_rate": f"{win_rate:.1f}%",
                "avg_win": f"${avg_win:.2f}",
                "avg_loss": f"${avg_loss:.2f}",
                "profit_factor": f"{profit_factor:.2f}",
                "expected_value_per_trade": f"${(avg_win * (win_rate/100)) - (avg_loss * ((100-win_rate)/100)):.2f}"
            },
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }), 200

# --- دوال الحفظ والتحميل السحابي والمحلي ---
def load_global_data():
    global global_data
    if BIN_ID and JSONBIN_KEY:
        try:
            url = f"https://api.jsonbin.io/v3/b/{BIN_ID}/latest"
            req = urllib.request.Request(url, headers={"X-Master-Key": JSONBIN_KEY})
            with urllib.request.urlopen(req, timeout=15) as r:
                response = json.loads(r.read().decode())
                global_data = response.get('record', {})
                print("✅ Data loaded from JSONBin cloud!", flush=True)
                return
        except Exception as e:
            print(f"⚠️ JSONBin load failed ({e}). Trying local...", flush=True)
    
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                global_data = json.load(f)
                print("✅ Data loaded from local file.", flush=True)
                return
        except:
            pass
    global_data = {}

def save_global_data():
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(global_data, f, indent=2)
    except Exception as e:
        print(f"⚠️ Local save error: {e}", flush=True)
    
    if BIN_ID and JSONBIN_KEY:
        try:
            url = f"https://api.jsonbin.io/v3/b/{BIN_ID}"
            req = urllib.request.Request(
                url,
                data=json.dumps(global_data).encode('utf-8'),
                headers={"X-Master-Key": JSONBIN_KEY, "Content-Type": "application/json"},
                method="PUT"
            )
            urllib.request.urlopen(req, timeout=15)
            print("💾 Cloud backup synchronized!", flush=True)
        except Exception as e:
            print(f"⚠️ Cloud backup failed: {e}", flush=True)

# --- دالة البوت المحسنة والآمنة ---
def run_trading_bot():
    global global_data
    print(">>> TRADING BOT WITH FIXED RISK MANAGEMENT STARTED <<<", flush=True)
    
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
        if not TOKEN or TOKEN == 'YOUR_TELEGRAM_TOKEN_HERE':
            return
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            data = json.dumps({"chat_id": CHAT_ID, "text": text}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            print(f"Telegram error: {e}", flush=True)

    with data_lock:
        load_global_data()
        if "global_stats" not in global_data:
            global_data["global_stats"] = {
                "wins": 0, "losses": 0, "net_profit": 0.0,
                "total_win_amount": 0.0, "total_loss_amount": 0.0
            }
        if "monthly_stats" not in global_data:
            global_data["monthly_stats"] = {"month": datetime.now().strftime("%Y-%m"), "wins": 0, "losses": 0, "net_profit": 0.0}
        if "daily_stats" not in global_data:
            global_data["daily_stats"] = {"date": datetime.now().strftime("%Y-%m-%d"), "wins": 0, "losses": 0, "net_profit": 0.0}
        save_global_data()

    send_telegram("🚀 تم تشغيل البوت بنجاح! وضع المحاكاة نشط بقيمة 50$ لكل صفقة وتتبع ذكي للأرباح.")

    consecutive_failures = 0
    
    while True:
        try:
            current_date = datetime.now().strftime("%Y-%m-%d")
            current_month = datetime.now().strftime("%Y-%m")
            save_needed = False

            with data_lock:
                if global_data["monthly_stats"].get("month") != current_month:
                    send_telegram(f"📅 تقرير الشهر الجديد: {global_data['monthly_stats']['net_profit']:.2f}$")
                    global_data["monthly_stats"] = {"month": current_month, "wins": 0, "losses": 0, "net_profit": 0.0}
                    save_needed = True

                if global_data["daily_stats"].get("date") != current_date:
                    send_telegram(f"📊 حصاد اليوم المنتهي: {global_data['daily_stats']['net_profit']:.2f}$")
                    global_data["daily_stats"] = {"date": current_date, "wins": 0, "losses": 0, "net_profit": 0.0}
                    save_needed = True

            # جلب الأسعار من بينانس
            try:
                url = "https://api.binance.com/api/v3/ticker/price"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=15) as f:
                    ticker_data = json.loads(f.read().decode())
                consecutive_failures = 0
            except Exception as e:
                consecutive_failures += 1
                print(f"⚠️ Binance API error ({consecutive_failures}): {e}", flush=True)
                time.sleep(60 if consecutive_failures < 5 else 300)
                continue
            
            market_prices = {}
            for item in ticker_data:
                if item['symbol'] in coin_mapping:
                    market_prices[coin_mapping[item['symbol']]] = float(item['price'])
            
            current_time_seconds = time.time()

            with data_lock:
                for cid, price in market_prices.items():
                    if cid not in global_data:
                        global_data[cid] = {}
                    
                    for key in ["history", "held", "buy_price", "is_holding", 
                               "trailing_active", "highest_price", "last_history_time"]:
                        if key not in global_data[cid]:
                            if key == "history": global_data[cid][key] = []
                            elif key in ["held", "buy_price", "highest_price"]: global_data[cid][key] = 0.0
                            elif key in ["is_holding", "trailing_active"]: global_data[cid][key] = False
                            elif key == "last_history_time": global_data[cid][key] = 0.0

                    # تحديث السجل الرياضي (كل 5 دقائق)
                    if current_time_seconds - global_data[cid]["last_history_time"] >= 300:
                        global_data[cid]["history"].append(price)
                        if len(global_data[cid]["history"]) > 20:
                            global_data[cid]["history"].pop(0)
                        global_data[cid]["last_history_time"] = current_time_seconds
                        save_needed = True

                    # --- إدارة الصفقة المفتوحة (تتبع حركي ذكي ومطلق) ---
                    if global_data[cid]["is_holding"]:
                        buy_price = global_data[cid]['buy_price']
                        if buy_price == 0: continue
                        
                        stop_loss_price = buy_price * (1 - RISK_CONFIG['stop_loss'])
                        activation_price = buy_price * (1 + RISK_CONFIG['trailing_activation'])
                        
                        # 1. تفقد تفعيل التتبع الحركي أولاً عند تجاوز هدف الأرباح المبدئي
                        if not global_data[cid]["trailing_active"] and price >= activation_price:
                            global_data[cid]["trailing_active"] = True
                            global_data[cid]["highest_price"] = price
                            send_telegram(f"🔥 {cid.upper()} - تجاوزت الـ +{RISK_CONFIG['trailing_activation']*100}% وبدأ التتبع الحركي لملاحقة أقصى ربح! السعر: {price}$")
                            save_needed = True

                        # 2. منطق ملاحقة السعر المتصاعد وحجز الربح عند الارتداد
                        if global_data[cid]["trailing_active"]:
                            if price > global_data[cid]["highest_price"]:
                                global_data[cid]["highest_price"] = price
                                save_needed = True
                            
                            trailing_stop_price = global_data[cid]["highest_price"] * (1 - RISK_CONFIG['trailing_stop'])
                            if price <= trailing_stop_price:
                                diff = (price - buy_price) * global_data[cid]['held']
                                global_data["global_stats"]["wins"] += 1
                                global_data["global_stats"]["net_profit"] += diff
                                global_data["global_stats"]["total_win_amount"] += diff
                                global_data["daily_stats"]["wins"] += 1
                                global_data["daily_stats"]["net_profit"] += diff
                                send_telegram(f"🚀 {cid.upper()} - خروج تتبع حركي ذكي بربح: +{diff:.2f}$ (أعلى قمة وصلها: {global_data[cid]['highest_price']:.2f}$)")
                                global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0})
                                save_needed = True
                                continue

                        # 3. وقف الخسارة الثابت (في حال ارتد السعر فوراً للأسفل دون صعود)
                        if price <= stop_loss_price and not global_data[cid]["trailing_active"]:
                            diff = (price - buy_price) * global_data[cid]['held']
                            global_data["global_stats"]["losses"] += 1
                            global_data["global_stats"]["net_profit"] += diff
                            global_data["global_stats"]["total_loss_amount"] += abs(diff)
                            global_data["daily_stats"]["losses"] += 1
                            global_data["daily_stats"]["net_profit"] += diff
                            send_telegram(f"🛑 {cid.upper()} - ضرب وقف الخسارة الثابت: {diff:.2f}$ (خسارة -{RISK_CONFIG['stop_loss']*100}%)")
                            global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0})
                            save_needed = True

                    # --- منطق الشراء المستقر بقيمة 50$ ---
                    else:
                        h = global_data[cid]["history"]
                        if len(h) < 5: continue
                        
                        sma = sum(h) / len(h)
                        variance = sum((x - sma)**2 for x in h) / len(h)
                        std = variance ** 0.5 if variance > 0 else 0.001
                        lower_band = sma - std
                        
                        if price <= lower_band and price > 0:
                            # شراء ثابت بقيمة 50 دولار تماماً كما حددت
                            position_size = RISK_CONFIG['entry_amount_usd'] / price
                            
                            global_data[cid].update({
                                'held': position_size,
                                'buy_price': price,
                                'is_holding': True,
                                'trailing_active': False,
                                'highest_price': 0.0
                            })
                            send_telegram(f"🎯 قناص الشراء: اقتناص {cid.upper()} بسعر {price:.2f}$ بإجمالي استثمار 50$")
                            save_needed = True

            if save_needed:
                with data_lock:
                    save_global_data()
            
            time.sleep(30)
            
        except Exception as e:
            print(f"⚠️ Error in Loop: {str(e)}", flush=True)
            time.sleep(60)

if __name__ == "__main__":
    t = threading.Thread(target=run_trading_bot, daemon=True)
    t.start()
    print(">>> MAIN FLASK APP RUNNING <<<", flush=True)
    
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
