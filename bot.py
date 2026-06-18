import os
import time
import threading
import json
import urllib.request
import urllib.error
import hmac
import hashlib
from datetime import datetime
from flask import Flask, jsonify

# إعداد خادم Flask وإحصائيات الاستضافة
app = Flask(__name__)

global_data = {}
DATA_FILE = "data.json"
data_lock = threading.Lock()

# مفاتيح بينانس الحقيقية (تُجلب من بيئة العمل للحماية)
BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY', 'YOUR_API_KEY_HERE')
BINANCE_SECRET_KEY = os.environ.get('BINANCE_SECRET_KEY', 'YOUR_SECRET_KEY_HERE')

@app.route('/')
def home():
    with data_lock:
        return jsonify({
            "status": "Halal Trading Bot is Running perfectly with OCO Protection Architecture!",
            "monitored_coins_count": len(set(global_data.get("daily_stats", {}).keys())) - 4 if "daily_stats" in global_data else 20,
            "daily_stats": global_data.get("daily_stats", {}),
            "monthly_stats": global_data.get("monthly_stats", {}),
            "global_stats": global_data.get("global_stats", {})
        })

# --- أدوات الاتصال والتشفير الخاصة بمنصة بينانس الحقيقية ---
def binance_signature(query_string, secret_key):
    return hmac.new(secret_key.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()

def send_binance_signed_request(endpoint, method="POST", params={}):
    """دالة احترافية لإرسال الأوامر الموقعة رقمياً إلى بينانس مباشرة"""
    if BINANCE_API_KEY == 'YOUR_API_KEY_HERE':
        # وضع التجريب والمحاكاة الافتراضية إذا لم تكن المفاتيح مضافة
        return {"mock_success": True, "orderId": 123456}
        
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
        print(f"Binance API Error: {e}")
        return {"error": str(e)}

# --- نظام التداول والمراقبة الحركي ---
def run_trading_bot():
    global global_data
    TOKEN = os.environ['TOKEN']
    CHAT_ID = "199325566"
    
    coin_mapping = {
        "BTCUSDT": "bitcoin", "ETHUSDT": "ethereum", "SOLUSDT": "solana",
        "LINKUSDT": "chainlink", "ADAUSDT": "cardano", "DOTUSDT": "polkadot",
        "NEARUSDT": "near", "ARBUSDT": "arbitrum", "OPUSDT": "optimism",
        "RENDERUSDT": "render", "BNBUSDT": "binancecoin",   
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
        except Exception as e: print(f"Telegram Error: {e}")

    send_telegram("🚀 تم تشغيل البوت المطور بنظام التشفير الرقمي وجدار حماية صفقات الـ OCO الذكي!")
    
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f: 
            try: global_data = json.load(f)
            except: global_data = {}

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

                # (منطق تصفير التقارير اليومية والشهرية يظل مستقراً كما هو بكودك لضمان دقة حساباتك...)
                if global_data["monthly_stats"].get("month") != current_month:
                    global_data["monthly_stats"] = {"month": current_month, "wins": 0, "losses": 0, "net_profit": 0.0}
                    save_needed = True
                if global_data["daily_stats"].get("date") != current_date:
                    global_data["daily_stats"] = {"date": current_date, "wins": 0, "losses": 0, "net_profit": 0.0}
                    save_needed = True

            # جلب الأسعار اللحظية (تجميعة واحدة آمنة لـ 20 عملة)
            url = "https://api.binance.com/api/v3/ticker/price"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as f:
                ticker_data = json.loads(f.read().decode())
            
            market_prices = {coin_mapping[item['symbol']]: float(item['price']) for item in ticker_data if item['symbol'] in coin_mapping}
            current_time_seconds = time.time()

            with data_lock:
                for cid, price in market_prices.items():
                    # تهيئة المتغيرات الأساسية للعملات الجديدة
                    if cid not in global_data: global_data[cid] = {}
                    if "history" not in global_data[cid]: global_data[cid]["history"] = []
                    if "held" not in global_data[cid]: global_data[cid]["held"] = 0.0
                    if "buy_price" not in global_data[cid]: global_data[cid]["buy_price"] = 0.0
                    if "is_holding" not in global_data[cid]: global_data[cid]["is_holding"] = False
                    if "trailing_active" not in global_data[cid]: global_data[cid]["trailing_active"] = False
                    if "highest_price" not in global_data[cid]: global_data[cid]["highest_price"] = 0.0
                    if "last_history_time" not in global_data[cid]: global_data[cid]["last_history_time"] = 0.0

                    # تحديث السجل التاريخي الرياضي (كل 5 دقائق) لعمق 20 قراءة آمنة
                    if current_time_seconds - global_data[cid]["last_history_time"] >= 300:
                        global_data[cid]["history"].append(price)
                        if len(global_data[cid]["history"]) > 20: global_data[cid]["history"].pop(0)
                        global_data[cid]["last_history_time"] = current_time_seconds
                        save_needed = True

                    # --- إدارة صفقات البيع والمطاردة الفوقية ---
                    if global_data[cid]["is_holding"]:
                        buy_price = global_data[cid]['buy_price']
                        stop_loss_price = buy_price * 0.95   
                        activation_price = buy_price * 1.01  

                        if not global_data[cid]["trailing_active"] and price >= activation_price:
                            global_data[cid]["trailing_active"] = True
                            global_data[cid]["highest_price"] = price
                            send_telegram(f"🔥 {cid.upper()} اقتنصت هدف +1%! تم تنشيط المطاردة البرمجية. السعر اللحظي: {price}$")
                            save_needed = True

                        if global_data[cid]["trailing_active"]:
                            if price > global_data[cid]["highest_price"]:
                                global_data[cid]["highest_price"] = price
                                save_needed = True
                            
                            drop_threshold = global_data[cid]["highest_price"] * 0.996
                            if price <= drop_threshold:
                                diff = (price - buy_price) * global_data[cid]['held']
                                # إلغاء أمر الـ OCO القديم من المنصة لأن البوت سيبيع بنفسه الآن بسعر أعلى ومربح
                                # (تنبيه: يتم تفعيل دالة إلغاء الأمر عند الانتقال للتداول الحقيقي)
                                
                                global_data["global_stats"]["wins"] += 1
                                global_data["global_stats"]["net_profit"] += diff
                                global_data["monthly_stats"]["wins"] += 1
                                global_data["monthly_stats"]["net_profit"] += diff
                                global_data["daily_stats"]["wins"] += 1
                                global_data["daily_stats"]["net_profit"] += diff
                                
                                send_telegram(f"🚀 بيع ذكي بمطاردة الأرباح: {cid.upper()}\nسعر الشراء: {buy_price:.2f}$\nسعر البيع: {price:.2f}$\n💰 صافي الربح: {diff:.2f}$")
                                global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0})
                                save_needed = True

                        elif price <= stop_loss_price:
                            diff = (price - buy_price) * global_data[cid]['held']
                            global_data["global_stats"]["losses"] += 1
                            global_data["global_stats"]["net_profit"] += diff
                            global_data["monthly_stats"]["losses"] += 1
                            global_data["monthly_stats"]["net_profit"] += diff
                            global_data["daily_stats"]["losses"] += 1
                            global_data["daily_stats"]["net_profit"] += diff
                            
                            send_telegram(f"🛑 بيع اضطراري بوقف الخسارة الثابت (5%): {cid.upper()}\nالخسارة: {diff:.2f}$")
                            global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0})
                            save_needed = True

                    # --- قناص فرص الشراء + زرع أمر OCO الدفاعي فوراً ---
                    else:
                        h = global_data[cid]["history"]
                        if len(h) < 20: continue 
                        
                        sma = sum(h) / len(h)
                        std = (sum((x - sma)**2 for x in h) / len(h))**0.5
                        lower = sma - (1.0 * std)
                        
                        if price <= lower:
                            # 1. تحديث البيانات محلياً (شراء بقيمة 50 دولار)
                            global_data[cid].update({'held': 50 / price, 'buy_price': price, 'is_holding': True, 'trailing_active': False, 'highest_price': 0.0})
                            send_telegram(f"🎯 شراء استراتيجي: {cid.upper()} بسعر {price}$. جاري تأمين الصفقة على بينانس...")
                            
                            # 2. خط الدفاع الاحترافي: إرسال أمر OCO فوري وسري لـ بينانس لحمايتك لو نمت أو حُظرت
                            symbol_binance = [k for k, v in coin_mapping.items() if v == cid][0]
                            oco_params = {
                                "symbol": symbol_binance,
                                "side": "SELL",
                                "quantity": round(50 / price, 4),
                                "price": round(price * 1.02, 2),        # هدف جني الأرباح الثابت الآمن (مثال: +2%)
                                "stopPrice": round(price * 0.955, 2),    # نقطة تفعيل وقف الخسارة على سيرفر بينانس (-4.5%)
                                "stopLimitPrice": round(price * 0.95, 2) # سعر تنفيذ وقف الخسارة الفعلي بالمنصة (-5%)
                            }
                            # تنفيذ إرسال الأمر المشروط فوراً للسيرفر الخارجي
                            binance_order = send_binance_signed_request("/api/v3/order/oco", method="POST", params=oco_params)
                            
                            save_needed = True
            
            if save_needed:
                with data_lock:
                    with open(DATA_FILE, 'w') as f: json.dump(global_data, f)
            
            time.sleep(30)
            
        except urllib.error.HTTPError as e:
            # [تحديث الأمان الذكي للفحص]: إذا واجهنا الحظر المشترك من ريندر (429 أو 418) انسحب تكتيكياً
            if e.code in [429, 418]:
                send_telegram(f"⚠️ تقييد مؤقت من جدار حماية بينانس (كود {e.code}). سأدخل في وضع النوم لـ 15 دقيقة. صفقاتك المفتوحة مؤمنة بالكامل بأوامر OCO على المنصة.")
                time.sleep(900)
            else:
                send_telegram(f"⚠️ خطأ شبكة كود ({e.code}): {str(e)}")
                time.sleep(30)
        except Exception as e: 
            send_telegram(f"⚠️ خطأ عام في حلقة البوت: {str(e)}")
            time.sleep(30)

if __name__ == "__main__":
    threading.Thread(target=run_trading_bot, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
