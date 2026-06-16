import os
import time
import threading
import json
import urllib.request
import urllib.error
from flask import Flask, jsonify

# إعداد خادم Flask
app = Flask(__name__)

# تعريف المتغير global_data لحفظ الإحصائيات والبيانات
global_data = {}
DATA_FILE = "data.json"

@app.route('/')
def home():
    # عند زيارة الرابط، سيعرض لك الإحصائيات الحالية
    return jsonify({
        "status": "Halal Trading Bot is Running!",
        "stats": global_data.get("global_stats", {"wins": 0, "losses": 0, "net_profit": 0.0})
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

    send_telegram("🚀 تم الانتقال بنجاح إلى سيرفرات Binance API الحصينة! البوت الآن يعمل مع نظام الإحصائيات.")
    
    while True:
        try:
            # تحميل البيانات من الملف
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r') as f: 
                    try: global_data = json.load(f)
                    except: global_data = {}
            
            # التأكد من وجود قسم الإحصائيات
            if "global_stats" not in global_data:
                global_data["global_stats"] = {"wins": 0, "losses": 0, "net_profit": 0.0}

            # تجهيز العملات
            for c in coins:
                if c not in global_data: global_data[c] = {}
                if "history" not in global_data[c]: global_data[c]["history"] = []
                if "held" not in global_data[c]: global_data[c]["held"] = 0.0
                if "buy_price" not in global_data[c]: global_data[c]["buy_price"] = 0.0
                if "is_holding" not in global_data[c]: global_data[c]["is_holding"] = False

            # جلب الأسعار
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
                
                # منطق الشراء
                if not global_data[cid]["is_holding"] and price <= lower:
                    global_data[cid].update({'held': 150 / price, 'buy_price': price, 'is_holding': True})
                    send_telegram(f"🎯 شراء: {cid.upper()} بسعر {price}$")
                
                # منطق البيع
                elif global_data[cid]["is_holding"]:
                    take_profit_price = global_data[cid]['buy_price'] * 1.01 
                    stop_loss_price = global_data[cid]['buy_price'] * 0.95   
                    
                    if price >= take_profit_price:
                        diff = (price - global_data[cid]['buy_price']) * global_data[cid]['held']
                        global_data["global_stats"]["wins"] += 1
                        global_data["global_stats"]["net_profit"] += diff
                        send_telegram(f"✅ بيع بربح: {cid.upper()}\nالربح: {diff:.2f}$\nالربح الكلي: {global_data['global_stats']['net_profit']:.2f}$")
                        global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False})
                        
                    elif price <= stop_loss_price:
                        diff = (price - global_data[cid]['buy_price']) * global_data[cid]['held']
                        global_data["global_stats"]["losses"] += 1
                        global_data["global_stats"]["net_profit"] += diff 
                        send_telegram(f"🛑 بيع بخسارة: {cid.upper()}\nالخسارة: {diff:.2f}$\nالربح الكلي: {global_data['global_stats']['net_profit']:.2f}$")
                        global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False})
            
            # حفظ البيانات
            with open(DATA_FILE, 'w') as f: json.dump(global_data, f)
            time.sleep(300)
            
        except Exception as e: 
            send_telegram(f"⚠️ خطأ: {str(e)}")
            time.sleep(60)

if __name__ == "__main__":
    threading.Thread(target=run_trading_bot, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
