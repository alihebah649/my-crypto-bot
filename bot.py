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

@app.route('/')
def home():
    # عرض كل الإحصائيات (اليومية، الشهرية، والكلية) عبر المتصفح
    return jsonify({
        "status": "Halal Trading Bot is Running!",
        "daily_stats": global_data.get("daily_stats", {}),
        "monthly_stats": global_data.get("monthly_stats", {}),
        "global_stats": global_data.get("global_stats", {})
    })

def run_trading_bot():
    global global_data
    TOKEN = os.environ['TOKEN']
    CHAT_ID = "199325566"
    
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

    send_telegram("🚀 تم الانتقال بنجاح إلى سيرفرات Binance API! نظام الإحصائيات (اليومي، الشهري، الكلي) يعمل الآن بكفاءة.")
    
    while True:
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r') as f: 
                    try: global_data = json.load(f)
                    except: global_data = {}
            
            # --- 1. إعداد تواريخ اليوم والشهر الحالي ---
            current_date = datetime.now().strftime("%Y-%m-%d")
            current_month = datetime.now().strftime("%Y-%m")

            if "global_stats" not in global_data:
                global_data["global_stats"] = {"wins": 0, "losses": 0, "net_profit": 0.0}

            if "monthly_stats" not in global_data:
                global_data["monthly_stats"] = {"month": current_month, "wins": 0, "losses": 0, "net_profit": 0.0}

            if "daily_stats" not in global_data:
                global_data["daily_stats"] = {"date": current_date, "wins": 0, "losses": 0, "net_profit": 0.0}

            # --- 2. فحص مرور شهر جديد ---
            if global_data["monthly_stats"].get("month") != current_month:
                old_month = global_data["monthly_stats"].get("month", "غير معروف")
                m_wins = global_data["monthly_stats"]["wins"]
                m_losses = global_data["monthly_stats"]["losses"]
                m_profit = global_data["monthly_stats"]["net_profit"]
                
                # إرسال تقرير الحصاد الشهري
                summary_month = (
                    f"📅 تقرير حصاد الشهر ({old_month}):\n\n"
                    f"✅ إجمالي الصفقات الرابحة: {m_wins}\n"
                    f"🛑 إجمالي الصفقات الخاسرة: {m_losses}\n"
                    f"💰 صافي الربح الشهري: {m_profit:.2f}$\n"
                    f"📈 إجمالي الربح التراكمي: {global_data['global_stats']['net_profit']:.2f}$"
                )
                send_telegram(summary_month)
                # تصفير العدادات الشهرية للشهر الجديد
                global_data["monthly_stats"] = {"month": current_month, "wins": 0, "losses": 0, "net_profit": 0.0}

            # --- 3. فحص مرور يوم جديد (24 ساعة) ---
            if global_data["daily_stats"].get("date") != current_date:
                old_date = global_data["daily_stats"].get("date", "غير معروف")
                d_wins = global_data["daily_stats"]["wins"]
                d_losses = global_data["daily_stats"]["losses"]
                d_profit = global_data["daily_stats"]["net_profit"]
                
                # إرسال تقرير الحصاد اليومي
                summary_day = (
                    f"📊 حصاد اليوم ({old_date}):\n\n"
                    f"✅ صفقات رابحة اليوم: {d_wins}\n"
                    f"🛑 صفقات خاسرة اليوم: {d_losses}\n"
                    f"💰 صافي الربح اليومي: {d_profit:.2f}$\n"
                    f"🗓️ إجمالي الربح هذا الشهر: {global_data['monthly_stats']['net_profit']:.2f}$"
                )
                send_telegram(summary_day)
                # تصفير العدادات اليومية لليوم الجديد فقط (الشهري يبقى كما هو)
                global_data["daily_stats"] = {"date": current_date, "wins": 0, "losses": 0, "net_profit": 0.0}


            # --- 4. معالجة وتحديث بيانات العملات ---
            for c in coins:
                if c not in global_data: global_data[c] = {}
                if "history" not in global_data[c]: global_data[c]["history"] = []
                if "held" not in global_data[c]: global_data[c]["held"] = 0.0
                if "buy_price" not in global_data[c]: global_data[c]["buy_price"] = 0.0
                if "is_holding" not in global_data[c]: global_data[c]["is_holding"] = False

            url = "https://api.binance.com/api/v3/ticker/price"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as f:
                ticker_data = json.loads(f.read().decode())
            
            market_prices = {coin_mapping[item['symbol']]: float(item['price']) for item in ticker_data if item['symbol'] in coin_mapping}
            
            for cid, price in market_prices.items():
                h = global_data[cid]["history"]
                h.append(price)
                if len(h) > 3: h.pop(0)
                if len(h) < 3: continue
                
                sma = sum(h) / len(h)
                std = (sum((x - sma)**2 for x in h) / len(h))**0.5
                lower = sma - (1.0 * std)
                
                if not global_data[cid]["is_holding"] and price <= lower:
                    global_data[cid].update({'held': 150 / price, 'buy_price': price, 'is_holding': True})
                    send_telegram(f"🎯 شراء: {cid.upper()} بسعر {price}$")
                
                elif global_data[cid]["is_holding"]:
                    take_profit_price = global_data[cid]['buy_price'] * 1.01 
                    stop_loss_price = global_data[cid]['buy_price'] * 0.95   
                    
                    # --- 5. تحديث الإحصائيات (الكلية، الشهرية، اليومية) عند البيع ---
                    if price >= take_profit_price:
                        diff = (price - global_data[cid]['buy_price']) * global_data[cid]['held']
                        
                        # تحديث جميع العدادات بزيادة 1 لصفقات الربح وإضافة قيمة الربح
                        global_data["global_stats"]["wins"] += 1
                        global_data["global_stats"]["net_profit"] += diff
                        global_data["monthly_stats"]["wins"] += 1
                        global_data["monthly_stats"]["net_profit"] += diff
                        global_data["daily_stats"]["wins"] += 1
                        global_data["daily_stats"]["net_profit"] += diff
                        
                        msg = (f"✅ بيع بربح: {cid.upper()}\n"
                               f"الربح من الصفقة: {diff:.2f}$\n"
                               f"💰 الربح اليومي: {global_data['daily_stats']['net_profit']:.2f}$\n"
                               f"🗓️ الربح الشهري: {global_data['monthly_stats']['net_profit']:.2f}$\n"
                               f"📈 الربح التراكمي الكلي: {global_data['global_stats']['net_profit']:.2f}$")
                        send_telegram(msg)
                        
                        global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False})
                        
                    elif price <= stop_loss_price:
                        diff = (price - global_data[cid]['buy_price']) * global_data[cid]['held']
                        
                        # تحديث جميع العدادات بزيادة 1 لصفقات الخسارة وإضافة قيمة الخسارة (diff بالسالب)
                        global_data["global_stats"]["losses"] += 1
                        global_data["global_stats"]["net_profit"] += diff 
                        global_data["monthly_stats"]["losses"] += 1
                        global_data["monthly_stats"]["net_profit"] += diff
                        global_data["daily_stats"]["losses"] += 1
                        global_data["daily_stats"]["net_profit"] += diff
                        
                        msg = (f"🛑 بيع بخسارة: {cid.upper()}\n"
                               f"الخسارة من الصفقة: {diff:.2f}$\n"
                               f"💰 الحصيلة اليومية: {global_data['daily_stats']['net_profit']:.2f}$\n"
                               f"🗓️ الحصيلة الشهرية: {global_data['monthly_stats']['net_profit']:.2f}$\n"
                               f"📈 الربح التراكمي الكلي: {global_data['global_stats']['net_profit']:.2f}$")
                        send_telegram(msg)
                        
                        global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False})
            
            with open(DATA_FILE, 'w') as f: json.dump(global_data, f)
            time.sleep(300)
            
        except Exception as e: 
            send_telegram(f"⚠️ خطأ: {str(e)}")
            time.sleep(60)

if __name__ == "__main__":
    threading.Thread(target=run_trading_bot, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
