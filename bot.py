import os
import time
import threading
import json
import urllib.request
import urllib.error
from datetime import datetime
from flask import Flask, jsonify

# إعداد خادم Flask لإبقاء السيرفر حياً على Render وتقديم الإحصائيات لـ UptimeRobot
app = Flask(__name__)

global_data = {}
DATA_FILE = "data.json"

@app.route('/')
def home():
    # عند زيارة الرابط أو قيام UptimeRobot بطلب الفحص، تظهر كافة التقارير لحظياً
    return jsonify({
        "status": "Halal Trading Bot is Running perfectly with Trailing Take Profit!",
        "daily_stats": global_data.get("daily_stats", {}),
        "monthly_stats": global_data.get("monthly_stats", {}),
        "global_stats": global_data.get("global_stats", {})
    })

def run_trading_bot():
    global global_data
    TOKEN = os.environ['TOKEN']
    CHAT_ID = "199325566"
    
    # خريطة الربط الذكي بين رموز Binance ومعرفات العملات
    coin_mapping = {
        "BTCUSDT": "bitcoin", "ETHUSDT": "ethereum", "SOLUSDT": "solana",
        "LINKUSDT": "chainlink", "ADAUSDT": "cardano", "DOTUSDT": "polkadot",
        "NEARUSDT": "near", "ARBUSDT": "arbitrum", "OPUSDT": "optimism",
        "RENDERUSDT": "render", "RNDRUSDT": "render"
    }
    
    coins = list(set(coin_mapping.values()))

    def send_telegram(text):
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            data = json.dumps({"chat_id": CHAT_ID, "text": text}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
        except Exception as e: 
            print(f"Telegram Error: {e}")

    send_telegram("🚀 تم تشغيل البوت بنجاح! نظام جني الأرباح المتحرك (Trailing TP) والتقارير المتقدمة (يومي/شهري/كلي) يعمل الآن بالفحص الذكي كل 30 ثانية.")
    
    while True:
        try:
            # تحميل البيانات من الملف بأمان
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r') as f: 
                    try: global_data = json.load(f)
                    except: global_data = {}
            
            current_date = datetime.now().strftime("%Y-%m-%d")
            current_month = datetime.now().strftime("%Y-%m")

            # تأمين وجود هياكل الإحصائيات الثلاثة
            if "global_stats" not in global_data:
                global_data["global_stats"] = {"wins": 0, "losses": 0, "net_profit": 0.0}
            if "monthly_stats" not in global_data:
                global_data["monthly_stats"] = {"month": current_month, "wins": 0, "losses": 0, "net_profit": 0.0}
            if "daily_stats" not in global_data:
                global_data["daily_stats"] = {"date": current_date, "wins": 0, "losses": 0, "net_profit": 0.0}

            # --- 1. فحص إرسال وتصفير التقرير الشهري ---
            if global_data["monthly_stats"].get("month") != current_month:
                old_month = global_data["monthly_stats"].get("month", "غير معروف")
                summary_month = (
                    f"📅 تقرير حصاد الشهر المنتهي ({old_month}):\n\n"
                    f"✅ إجمالي الصفقات الرابحة: {global_data['monthly_stats']['wins']}\n"
                    f"🛑 إجمالي الصفقات الخاسرة: {global_data['monthly_stats']['losses']}\n"
                    f"💰 صافي الربح الشهري: {global_data['monthly_stats']['net_profit']:.2f}$\n"
                    f"📈 إجمالي الأرباح التراكمية الكلية: {global_data['global_stats']['net_profit']:.2f}$"
                )
                send_telegram(summary_month)
                global_data["monthly_stats"] = {"month": current_month, "wins": 0, "losses": 0, "net_profit": 0.0}

            # --- 2. فحص إرسال وتصفير التقرير اليومي ---
            if global_data["daily_stats"].get("date") != current_date:
                old_date = global_data["daily_stats"].get("date", "غير معروف")
                summary_day = (
                    f"📊 حصاد الـ 24 ساعة الماضية ({old_date}):\n\n"
                    f"✅ صفقات رابحة اليوم: {global_data['daily_stats']['wins']}\n"
                    f"🛑 صفقات خاسرة اليوم: {global_data['daily_stats']['losses']}\n"
                    f"💰 صافي حصاد اليوم: {global_data['daily_stats']['net_profit']:.2f}$\n"
                    f"🗓️ إجمالي أرباح الشهر الحالي حتى الآن: {global_data['monthly_stats']['net_profit']:.2f}$"
                )
                send_telegram(summary_day)
                global_data["daily_stats"] = {"date": current_date, "wins": 0, "losses": 0, "net_profit": 0.0}

            # --- 3. جلب الأسعار اللحظية من Binance ---
            url = "https://api.binance.com/api/v3/ticker/price"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as f:
                ticker_data = json.loads(f.read().decode())
            
            market_prices = {coin_mapping[item['symbol']]: float(item['price']) for item in ticker_data if item['symbol'] in coin_mapping}
            
            current_time_seconds = time.time()

            # --- 4. معالجة العملات وإدارة الصفقات والمطاردة ---
            for cid, price in market_prices.items():
                if cid not in global_data: global_data[cid] = {}
                if "history" not in global_data[cid]: global_data[cid]["history"] = []
                if "held" not in global_data[cid]: global_data[cid]["held"] = 0.0
                if "buy_price" not in global_data[cid]: global_data[cid]["buy_price"] = 0.0
                if "is_holding" not in global_data[cid]: global_data[cid]["is_holding"] = False
                if "trailing_active" not in global_data[cid]: global_data[cid]["trailing_active"] = False
                if "highest_price" not in global_data[cid]: global_data[cid]["highest_price"] = 0.0
                if "last_history_time" not in global_data[cid]: global_data[cid]["last_history_time"] = 0.0

                # تحديث التاريخ الإحصائي (History) كل 5 دقائق (300 ثانية) فقط للمحافظة على أبعاد استراتيجيتك الأصلية
                if current_time_seconds - global_data[cid]["last_history_time"] >= 300:
                    global_data[cid]["history"].append(price)
                    if len(global_data[cid]["history"]) > 3: 
                        global_data[cid]["history"].pop(0)
                    global_data[cid]["last_history_time"] = current_time_seconds

                # نظام إدارة الصفقة الحالية (Trailing Take Profit + Stop Loss) - يعمل كل 30 ثانية لدقة قصوى
                if global_data[cid]["is_holding"]:
                    buy_price = global_data[cid]['buy_price']
                    stop_loss_price = buy_price * 0.95   # وقف الخسارة الثابت 5%
                    activation_price = buy_price * 1.01  # تنشيط المطاردة المتحركة فور الصعود +1%

                    # تفعيل وضع المطاردة إذا تخطينا حاجز الـ 1% صعوداً ولم تفعل من قبل
                    if not global_data[cid]["trailing_active"] and price >= activation_price:
                        global_data[cid]["trailing_active"] = True
                        global_data[cid]["highest_price"] = price
                        send_telegram(f"🔥 {cid.upper()} اقتنصت هدف +1%! تم تفعيل خوارزمية مطاردة الأرباح التكتيكية. أعلى سعر حالي: {price}$")

                    # إذا كانت المطاردة نشطة، نحدث أعلى قمة أو ننفذ أمر البيع عند الارتداد هبوطاً
                    if global_data[cid]["trailing_active"]:
                        if price > global_data[cid]["highest_price"]:
                            global_data[cid]["highest_price"] = price
                        
                        # نبيع فوراً إذا ارتد السعر لأسفل بنسبة 0.4% من أعلى قمة رصدها البوت
                        drop_threshold = global_data[cid]["highest_price"] * 0.996
                        
                        if price <= drop_threshold:
                            diff = (price - buy_price) * global_data[cid]['held']
                            
                            # زيادة كافة العدادات بقيم النجاح والأرباح المحققة
                            global_data["global_stats"]["wins"] += 1
                            global_data["global_stats"]["net_profit"] += diff
                            global_data["monthly_stats"]["wins"] += 1
                            global_data["monthly_stats"]["net_profit"] += diff
                            global_data["daily_stats"]["wins"] += 1
                            global_data["daily_stats"]["net_profit"] += diff
                            
                            msg = (f"🚀 بيع ذكي بمطاردة الأرباح: {cid.upper()}\n"
                                   f"سعر الشراء الأساسي: {buy_price:.4f}$\n"
                                   f"أعلى قمة تاريخية تم رصدها: {global_data[cid]['highest_price']:.4f}$\n"
                                   f"سعر التنفيذ الفعلي: {price:.4f}$\n"
                                   f"💰 صافي الربح المستخلص: {diff:.2f}$\n"
                                   f"📊 اليومي الحالي: {global_data['daily_stats']['net_profit']:.2f}$\n"
                                   f"📅 الشهري الحالي: {global_data['monthly_stats']['net_profit']:.2f}$\n"
                                   f"📈 الإجمالي الكلي: {global_data['global_stats']['net_profit']:.2f}$")
                            send_telegram(msg)
                            
                            # تصفير بيانات العملة المستهدفة وعودتها لساحة المراقبة
                            global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0})

                    # تفعيل وقف الخسارة لحماية رأس المال إذا هبطت العملة مباشرة دون لمس عتبة الأرباح
                    elif price <= stop_loss_price:
                        diff = (price - buy_price) * global_data[cid]['held']
                        
                        global_data["global_stats"]["losses"] += 1
                        global_data["global_stats"]["net_profit"] += diff
                        global_data["monthly_stats"]["losses"] += 1
                        global_data["monthly_stats"]["net_profit"] += diff
                        global_data["daily_stats"]["losses"] += 1
                        global_data["daily_stats"]["net_profit"] += diff
                        
                        msg = (f"🛑 بيع اضطراري بوقف الخسارة (5%): {cid.upper()}\n"
                               f"الخسارة الفعلية: {diff:.2f}$\n"
                               f"📊 حصيلة اليوم: {global_data['daily_stats']['net_profit']:.2f}$\n"
                               f"📈 الإجمالي الكلي: {global_data['global_stats']['net_profit']:.2f}$")
                        send_telegram(msg)
                        
                        global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0})

                # منطق اقتناص الفرص والشراء (يحتاج لاكتمال 3 قراءات للمؤشر بفارق 5 دقائق لكل قراءة)
                else:
                    h = global_data[cid]["history"]
                    if len(h) < 3: continue
                    
                    sma = sum(h) / len(h)
                    std = (sum((x - sma)**2 for x in h) / len(h))**0.5
                    lower = sma - (1.0 * std)
                    
                    if price <= lower:
                        global_data[cid].update({'held': 150 / price, 'buy_price': price, 'is_holding': True, 'trailing_active': False, 'highest_price': 0.0})
                        send_telegram(f"🎯 رصد إشارة شراء استراتيجية: {cid.upper()} بسعر دخول {price}$")
            
            # حفظ كافة التعديلات والإحصائيات في قاعدة البيانات المصغرة json
            with open(DATA_FILE, 'w') as f: json.dump(global_data, f)
            
            # دورة فحص سريعة جداً (30 ثانية) لاقتناص قمم الأسعار اللحظية بدقة متناهية
            time.sleep(30)
            
        except Exception as e: 
            send_telegram(f"⚠️ تنبيه؛ حدث خطأ في نظام البوت الرئيسي: {str(e)}")
            time.sleep(30)

if __name__ == "__main__":
    # تشغيل سكريبت التداول داخل تسلسل برمي خلفي مستقل
    threading.Thread(target=run_trading_bot, daemon=True).start()
    # تشغيل سيرفر الويب على المنفذ المخصص من Render
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
