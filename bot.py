import os
import time
import threading
import json
import urllib.request
import urllib.parse
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

# --- إعدادات إدارة المخاطر والأرباح المتقدمة للمحترفين ---
RISK_STOP_LOSS_PCT = 0.02       # وقف الخسارة الأساسي (2%) حماية من التقلبات
REWARD_ACTIVATION_PCT = 0.02    # تفعيل مطاردة الأرباح للنصف المتبقي عند صعود 2%
TRAILING_DROP_PCT = 0.005       # نسبة تراجع المطاردة من القمة (0.5%)

# مفاتيح بينانس الحقيقية (تُجلب من بيئة العمل للحماية)
BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY', 'YOUR_API_KEY_HERE')
BINANCE_SECRET_KEY = os.environ.get('BINANCE_SECRET_KEY', 'YOUR_SECRET_KEY_HERE')

@app.route('/')
def home():
    with data_lock:
        return jsonify({
            "status": "Halal Quantitative Trading Bot is Running with 4 Professional Filters!",
            "monitored_coins_count": len(set(global_data.get("daily_stats", {}).keys())) - 4 if "daily_stats" in global_data else 20,
            "daily_stats": global_data.get("daily_stats", {}),
            "monthly_stats": global_data.get("monthly_stats", {}),
            "global_stats": global_data.get("global_stats", {})
        })

# --- أدوات التشفير والاتصال لمنصة بينانس الحقيقية ---
def binance_signature(query_string, secret_key):
    return hmac.new(secret_key.encode('utf-8'), query_string.encode('utf-8'), hashlib.sha256).hexdigest()

def send_binance_signed_request(endpoint, method="POST", params={}):
    if BINANCE_API_KEY == 'YOUR_API_KEY_HERE':
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

# 📈 [الاستراتيجية الأولى]: فلتر الاتجاه العام EMA 200 لإطار الساعة من سيرفرات بينانس مباشرة
def get_binance_ema200(symbol):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=200"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            klines = json.loads(response.read().decode())
        if len(klines) < 200: return None
        closes = [float(k[4]) for k in klines]
        
        # حساب المتوسط الأسي الحسابي بدقة
        k = 2 / (200 + 1)
        ema = closes[0]
        for price in closes[1:]:
            ema = (price * k) + (ema * (1 - k))
        return ema
    except:
        return None

# --- نظام التداول الذكي الشامل ---
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
            data = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
        except Exception as e: print(f"Telegram Error: {e}")

    # دالة توليد الجداول التقريرية لليوم والشهر بدقة بالغة وثبات الأبعاد
    def generate_report_table(stats_key, title, period_value):
        table_lines = []
        table_lines.append(f"📊 *{title}*")
        table_lines.append(f"📅 التاريخ/الفترة: {period_value}\n")
        table_lines.append("```")
        table_lines.append("COIN     | WIN | LOSS | NET PROFIT")
        table_lines.append("----------------------------------")
        
        coin_stats = global_data.get(stats_key, {}).get("coins", {})
        total_wins = 0
        total_losses = 0
        total_profit = 0.0
        
        for c_id, stats in coin_stats.items():
            ticker = c_id.upper()
            for k, v in coin_mapping.items():
                if v == c_id:
                    ticker = k.replace("USDT", "")
                    break
            
            wins = stats.get("wins", 0)
            losses = stats.get("losses", 0)
            profit = stats.get("net_profit", 0.0)
            
            total_wins += wins
            total_losses += losses
            total_profit += profit
            
            table_lines.append(f"{ticker:<8} | {wins:<3} | {losses:<4} | {profit:+.2f}$")
        
        table_lines.append("----------------------------------")
        table_lines.append(f"TOTAL    | {total_wins:<3} | {total_losses:<4} | {total_profit:+.2f}$")
        table_lines.append("```")
        return "\n".join(table_lines)

    # دالة مساعدة لتسجيل الأرباح/الخسائر التراكمية لكل عملة على حدة لتغذية الجداول
    def record_transaction_stats(cid, is_win, amount):
        for key in ["global_stats", "daily_stats", "monthly_stats"]:
            if key == "global_stats":
                if is_win: global_data[key]["wins"] += 1
                else: global_data[key]["losses"] += 1
                global_data[key]["net_profit"] += amount
            else:
                if cid not in global_data[key]["coins"]: 
                    global_data[key]["coins"][cid] = {"wins": 0, "losses": 0, "net_profit": 0.0}
                if is_win: 
                    global_data[key]["wins"] += 1
                    global_data[key]["coins"][cid]["wins"] += 1
                else: 
                    global_data[key]["losses"] += 1
                    global_data[key]["coins"][cid]["losses"] += 1
                global_data[key]["net_profit"] += amount
                global_data[key]["coins"][cid]["net_profit"] += amount

    send_telegram("🚀 تم تشغيل البوت الاحترافي المحدث بحزم الحماية المتقدمة وجداول الحصاد المزدوجة!")
    
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
                # تهيئة هياكل تخزين الإحصائيات لضمان عدم حدوث كراش
                if "global_stats" not in global_data:
                    global_data["global_stats"] = {"wins": 0, "losses": 0, "net_profit": 0.0}
                    save_needed = True
                if "monthly_stats" not in global_data or "coins" not in global_data["monthly_stats"]:
                    global_data["monthly_stats"] = {"month": current_month, "wins": 0, "losses": 0, "net_profit": 0.0, "coins": {}}
                    save_needed = True
                if "daily_stats" not in global_data or "coins" not in global_data["daily_stats"]:
                    global_data["daily_stats"] = {"date": current_date, "wins": 0, "losses": 0, "net_profit": 0.0, "coins": {}}
                    save_needed = True

                # 1. إرسال وتصفير الجدول الشهري (نهاية الشهر)
                if global_data["monthly_stats"].get("month") != current_month:
                    old_month = global_data["monthly_stats"].get("month", "غير معروف")
                    send_telegram(generate_report_table("monthly_stats", "التقرير الشهري لحصاد المحفظة الشامل", old_month))
                    global_data["monthly_stats"] = {"month": current_month, "wins": 0, "losses": 0, "net_profit": 0.0, "coins": {}}
                    save_needed = True

                # 2. إرسال وتصفير الجدول اليومي (نهاية اليوم)
                if global_data["daily_stats"].get("date") != current_date:
                    old_date = global_data["daily_stats"].get("date", "غير معروف")
                    send_telegram(generate_report_table("daily_stats", "التقرير اليومي للحصاد كل 24 ساعة", old_date))
                    global_data["daily_stats"] = {"date": current_date, "wins": 0, "losses": 0, "net_profit": 0.0, "coins": {}}
                    save_needed = True

            # جلب الأسعار اللحظية من بينانس
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
                    
                    # تهيئة متغيرات الفلاتر الجديدة لحماية الصفقات المفتوحة
                    if "partial_profit_taken" not in global_data[cid]: global_data[cid]["partial_profit_taken"] = False
                    if "break_even_active" not in global_data[cid]: global_data[cid]["break_even_active"] = False

                    # تحديث السجل التاريخي للبوت (كل 5 دقائق)
                    if current_time_seconds - global_data[cid]["last_history_time"] >= 300:
                        global_data[cid]["history"].append(price)
                        if len(global_data[cid]["history"]) > 20: global_data[cid]["history"].pop(0)
                        global_data[cid]["last_history_time"] = current_time_seconds
                        save_needed = True

                    # --- إدارة وتتبع صفقات البيع بالآليات المتقدمة المدمجة ---
                    if global_data[cid]["is_holding"]:
                        buy_price = global_data[cid]['buy_price']
                        held_qty = global_data[cid]['held']
                        profit_pct = (price - buy_price) / buy_price

                        # [الاستراتيجية الثانية]: تأمين التعادل Break-Even بمجرد صعود السعر +1%
                        if not global_data[cid]["break_even_active"] and profit_pct >= 0.01:
                            global_data[cid]["break_even_active"] = True
                            send_telegram(f"🛡️ {cid.upper()} حققت +1%! تم تفعيل نظام Break-Even ونقل خط الحماية لنقطة الدخول لمنع أي خسائر.")
                            save_needed = True

                        # [الاستراتيجية الثالثة]: جني الأرباح الجزئي ببيع 50% من الكمية عند صعود +1.5%
                        if not global_data[cid]["partial_profit_taken"] and profit_pct >= 0.015:
                            half_qty = round(held_qty * 0.5, 4)
                            diff_half = (price - buy_price) * half_qty
                            
                            record_transaction_stats(cid, is_win=True, amount=diff_half)
                            send_telegram(f"💰 تأمين أرباح جزئية: تم بيع 50% من كمية {cid.upper()} بنجاح بربح: {diff_half:.2f}$. النصف الآخر مستمر للمطاردة قمم أعلى!")
                            
                            global_data[cid]["held"] -= half_qty
                            global_data[cid]["partial_profit_taken"] = True
                            save_needed = True

                        # تنشيط المطاردة البرمجية للنصف المتبقي عند صعود +2%
                        if not global_data[cid]["trailing_active"] and profit_pct >= REWARD_ACTIVATION_PCT:
                            global_data[cid]["trailing_active"] = True
                            global_data[cid]["highest_price"] = price
                            send_telegram(f"🔥 {cid.upper()} ضربت هدف +2%! تفعيل مطاردة الأرباح الفوقية للنصف المتبقي. السعر الحركي: {price}$")
                            save_needed = True

                        # تنفيذ آليات الخروج الذكي والمطاردة
                        if global_data[cid]["trailing_active"]:
                            if price > global_data[cid]["highest_price"]:
                                global_data[cid]["highest_price"] = price
                                save_needed = True
                            
                            drop_line = global_data[cid]["highest_price"] * (1.0 - TRAILING_DROP_PCT)
                            if price <= drop_line:
                                diff_remain = (price - buy_price) * global_data[cid]['held']
                                record_transaction_stats(cid, is_win=True, amount=diff_remain)
                                send_telegram(f"🚀 إغلاق النصف المتبقي بمطاردة الأرباح: {cid.upper()}\nسعر البيع النهائي: {price:.2f}$\n💰 الربح الإضافي: {diff_remain:.2f}$")
                                global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0, 'partial_profit_taken': False, 'break_even_active': False})
                                save_needed = True
                        else:
                            # تحديد سعر الوقف الفعلي بناءً على حالة فلتر تأمين التعادل
                            if global_data[cid]["break_even_active"]:
                                effective_stop_price = buy_price * 1.001 # الخروج بسعر الشراء + الرسوم طردياً
                            else:
                                effective_stop_price = buy_price * (1.0 - RISK_STOP_LOSS_PCT) # الوقف المحكم الجديد 2%

                            if price <= effective_stop_price:
                                diff_final = (price - buy_price) * global_data[cid]['held']
                                
                                if global_data[cid]["break_even_active"]:
                                    record_transaction_stats(cid, is_win=True, amount=diff_final) # تعتبر صفقة رابحة/متعادلة طالما لم تخسر
                                    send_telegram(f"🛡️ خروج آمن ومؤمن بالكامل بنقطة التعادل (Break-Even) لعملة {cid.upper()}: صافي التصفية: {diff_final:.2f}$")
                                else:
                                    record_transaction_stats(cid, is_win=False, amount=diff_final)
                                    send_telegram(f"🛑 خروج حتمي بوقف الخسارة المحكم المحمي (2%): {cid.upper()}\nالخسارة المحتواة: {diff_final:.2f}$")
                                
                                global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0, 'partial_profit_taken': False, 'break_even_active': False})
                                save_needed = True

                    # --- قناص فرص الشراء الخوارزمي المزود بفلاتر المحترفين ---
                    else:
                        h = global_data[cid]["history"]
                        if len(h) < 20: continue 
                        
                        sma = sum(h) / len(h)
                        std = (sum((x - sma)**2 for x in h) / len(h))**0.5
                        lower_band = sma - (1.0 * std)
                        
                        if price <= lower_band:
                            symbol_binance = [k for k, v in coin_mapping.items() if v == cid][0]
                            
                            # [الاستراتيجية الأولى]: تفعيل فلتر الاتجاه العام لـ EMA 200 لمنع صيد السكاكين الساقطة
                            ema200 = get_binance_ema200(symbol_binance)
                            if ema200 and price < ema200:
                                # السوق العام هابط للعملة، نتجاهل الصفقة فوراً لحماية رأس المال
                                continue
                            
                            # [الاستراتيجية الرابعة]: إدارة الحجم الديناميكي للصفقة بناءً على معامل الانحراف الحركي (التقلب)
                            volatility_ratio = std / sma if sma > 0 else 0.01
                            if volatility_ratio > 0.015:
                                entry_allocation = 25.0  # تقلب جنوني وعالٍ جداً -> خفض مخاطرة الدخول للنصف
                                vol_msg = "⚠️ تقلب مرتفع (تم خفض حجم الدخول تلقائياً لـ 25$ حمايةً لك)"
                            elif volatility_ratio < 0.005:
                                entry_allocation = 65.0  # عملة مستقرة وحركتها موزونة -> رفع حجم الشراء لـ 65$ لتعظيم الربح
                                vol_msg = "🍏 تقلب منخفض وآمن (تم رفع حجم الدخول لـ 65$ لزيادة الحصاد)"
                            else:
                                entry_allocation = 50.0  # تقلب معياري طبيعي
                                vol_msg = "⚖️ تقلب معتدل (حجم دخول قياسي 50$)"
                                
                            # تنفيذ الشراء الافتراضي الآمن وتأمين البيانات
                            global_data[cid].update({'held': entry_allocation / price, 'buy_price': price, 'is_holding': True, 'trailing_active': False, 'highest_price': 0.0, 'partial_profit_taken': False, 'break_even_active': False})
                            send_telegram(f"🎯 قناص المحترفين: شراء استراتيجي لعملة {cid.upper()} بسعر {price}$.\n📊 طبيعة الحركة: {vol_msg}")
                            
                            # إرسال أمر حماية احتياطي متطابق لمنصة بينانس عبر OCO
                            oco_params = {
                                "symbol": symbol_binance,
                                "side": "SELL",
                                "quantity": round(entry_allocation / price, 4),
                                "price": round(price * 1.03, 2),        
                                "stopPrice": round(price * 0.985, 2),    
                                "stopLimitPrice": round(price * (1.0 - RISK_STOP_LOSS_PCT), 2) 
                            }
                            send_binance_signed_request("/api/v3/order/oco", method="POST", params=oco_params)
                            save_needed = True
            
            if save_needed:
                with data_lock:
                    with open(DATA_FILE, 'w') as f: json.dump(global_data, f)
            
            time.sleep(30)
            
        except urllib.error.HTTPError as e:
            if e.code in [429, 418]:
                send_telegram(f"⚠️ تقييد مؤقت للسرعة من جدار حماية بينانس (كود {e.code}). سأنام لـ 15 دقيقة لحماية حسابك من الحظر. الصفقات الحالية مؤمنة ذاتياً.")
                time.sleep(900)
            else:
                send_telegram(f"⚠️ خطأ اتصال شبكي كود ({e.code}): {str(e)}")
                time.sleep(30)
        except Exception as e: 
            send_telegram(f"⚠️ خطأ غير متوقع في الحلقة الحركية: {str(e)}")
            time.sleep(30)

if __name__ == "__main__":
    threading.Thread(target=run_trading_bot, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
