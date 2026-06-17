import os
import time
import threading
import json
import urllib.request
import urllib.error
from datetime import datetime
from flask import Flask, jsonify

# إعداد خادم Flask
app = Flask(__name__)

global_data = {}
DATA_FILE = "data.json"
data_lock = threading.Lock()

@app.route('/')
def home():
    with data_lock:
        return jsonify({
            "status": "Halal Trading Bot is Running perfectly with 20 Shariah-Compliant Coins!",
            "monitored_coins_count": len(set(global_data.get("daily_stats", {}).keys())) - 4 if "daily_stats" in global_data else 20,
            "daily_stats": global_data.get("daily_stats", {}),
            "monthly_stats": global_data.get("monthly_stats", {}),
            "global_stats": global_data.get("global_stats", {})
        })

def run_trading_bot():
    global global_data
    TOKEN = os.environ['TOKEN']
    CHAT_ID = "199325566"
    
    # خريطة الـ 20 عملة المعتمدة والمتوافقة مع الضوابط الشرعية
    coin_mapping = {
        "BTCUSDT": "bitcoin", "ETHUSDT": "ethereum", "SOLUSDT": "solana",
        "LINKUSDT": "chainlink", "ADAUSDT": "cardano", "DOTUSDT": "polkadot",
        "NEARUSDT": "near", "ARBUSDT": "arbitrum", "OPUSDT": "optimism",
        "RENDERUSDT": "render", "RNDRUSDT": "render",
        "BNBUSDT": "binancecoin",   
        "POLUSDT": "polygon",       
        "AVAXUSDT": "avalanche",    
        "ALGOUSDT": "algorand",     
        "ATOMUSDT": "cosmos",       
        "FETUSDT": "fetch-ai",      
        "GRTUSDT": "the-graph",     
        "STXUSDT": "stacks",        
        "FTMUSDT": "fantom",        
        "LTCUSDT": "litecoin"       
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

    send_telegram("🚀 تم تحديث البوت وتعديل قيمة الدخول في الصفقة إلى 50$ للعملة الواحدة. جاري بدء المراقبة...")
    
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

                # تصفير وإرسال التقرير الشهري
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
                    save_needed = True

                # تصفير وإرسال التقرير اليومي
                if global_data["daily_stats"].get("date") != current_date:
                    old_date = global_data["daily_stats"].get("date", "غير معروف")
                    summary_day = (
                        f"📊 حصاد الـ 24 ساعة الماضية ({old_date}):\n\n"
                        f"✅ صفقات رابحة اليوم: {global_data['daily_stats']['wins']}\n"
                        f"🛑 صفقات خاسرة اليوم: {global_data['daily_stats']['losses']}\n"
                        f"💰 صافي حصاد اليوم: {global_data['daily_stats']['net_profit']:.2f}$\n"
                        f"🗓️ إجمالي أرباح الشهر الحالي: {global_data['monthly_stats']['net_profit']:.2f}$"
                    )
                    send_telegram(summary_day)
                    global_data["daily_stats"] = {"date": current_date, "wins": 0, "losses": 0, "net_profit": 0.0}
                    save_needed = True

            # جلب الأسعار اللحظية من Binance
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

                    # تحديث السجل التاريخي الرياضي (كل 5 دقائق) لعمق 20 قراءة آمنة
                    if current_time_seconds - global_data[cid]["last_history_time"] >= 300:
                        global_data[cid]["history"].append(price)
                        if len(global_data[cid]["history"]) > 20: 
                            global_data[cid]["history"].pop(0)
                        global_data[cid]["last_history_time"] = current_time_seconds
                        save_needed = True

                    # إدارة صفقات البيع المفتوحة والمطاردة (تحديث لحظي سريع كل 30 ثانية)
                    if global_data[cid]["is_holding"]:
                        buy_price = global_data[cid]['buy_price']
                        stop_loss_price = buy_price * 0.95   
                        activation_price = buy_price * 1.01  

                        if not global_data[cid]["trailing_active"] and price >= activation_price:
                            global_data[cid]["trailing_active"] = True
                            global_data[cid]["highest_price"] = price
                            send_telegram(f"🔥 {cid.upper()} تجاوزت +1%! تم تفعيل خوارزمية مطاردة الأرباح المتحركة. السعر الحالي: {price}$")
                            save_needed = True

                        if global_data[cid]["trailing_active"]:
                            if price > global_data[cid]["highest_price"]:
                                global_data[cid]["highest_price"] = price
                                save_needed = True
                            
                            drop_threshold = global_data[cid]["highest_price"] * 0.996
                            
                            if price <= drop_threshold:
                                diff = (price - buy_price) * global_data[cid]['held']
                                
                                global_data["global_stats"]["wins"] += 1
                                global_data["global_stats"]["net_profit"] += diff
                                global_data["monthly_stats"]["wins"] += 1
                                global_data["monthly_stats"]["net_profit"] += diff
                                global_data["daily_stats"]["wins"] += 1
                                global_data["daily_stats"]["net_profit"] += diff
                                
                                msg = (f"🚀 بيع ذكي بمطاردة الأرباح: {cid.upper()}\n"
                                       f"سعر الشراء: {buy_price:.2f}$\n"
                                       f"أعلى قمة رصدت: {global_data[cid]['highest_price']:.2f}$\n"
                                       f"سعر البيع الفعلي: {price:.2f}$\n"
                                       f"💰 صافي الربح المستخلص: {diff:.2f}$\n"
                                       f"📈 الكلي التراكمي: {global_data['global_stats']['net_profit']:.2f}$")
                                send_telegram(msg)
                                
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
                            
                            msg = (f"🛑 بيع بوقف الخسارة ثابت (5%): {cid.upper()}\n"
                                   f"الخسارة: {diff:.2f}$\n"
                                   f"📈 الكلي التراكمي: {global_data['global_stats']['net_profit']:.2f}$")
                            send_telegram(msg)
                            
                            global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0})
                            save_needed = True

                    # قناص فرص الشراء (تم هنا تعديل حجم رأس المال المخصص للصفقة إلى 50$)
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
                    with open(DATA_FILE, 'w') as f: 
                        json.dump(global_data, f)
            
            time.sleep(30)
            
        except Exception as e: 
            send_telegram(f"⚠️ خطأ في حلقة البوت: {str(e)}")
            time.sleep(30)

if __name__ == "__main__":
    threading.Thread(target=run_trading_bot, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
