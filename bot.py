import os
import time
import threading
import json
import urllib.request
import urllib.error
from flask import Flask

# إعداد خادم Flask لإبقاء السيرفر حياً على Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Halal Trading Bot is running perfectly on Binance API!"

def run_trading_bot():
    TOKEN = os.environ['TOKEN']
    CHAT_ID = "199325566"
    DATA_FILE = "data.json"
    
    # خريطة الربط الذكي بين رموز Binance ومعرفات العملات الخاصة بك
    coin_mapping = {
        "BTCUSDT": "bitcoin",
        "ETHUSDT": "ethereum",
        "SOLUSDT": "solana",
        "LINKUSDT": "chainlink",
        "ADAUSDT": "cardano",
        "DOTUSDT": "polkadot",
        "NEARUSDT": "near",
        "ARBUSDT": "arbitrum",
        "OPUSDT": "optimism",
        "RENDERUSDT": "render",
        "RNDRUSDT": "render"  # حماية إضافية للرمز القديم للعملة
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

    # إعلان الانتقال الناجح لـ Binance
    send_telegram("🚀 تم الانتقال بنجاح إلى سيرفرات Binance API الحصينة! أبدأ الفحص الآمن والتشخيص الآن...")
    
    while True:
        try:
            data = {}
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r') as f: 
                    try:
                        data = json.load(f)
                    except json.JSONDecodeError:
                        data = {}
            
            # تأمين هيكلة البيانات لكل العملات لتجنب أي نقص
            for c in coins:
                if c not in data: data[c] = {}
                if "history" not in data[c]: data[c]["history"] = []
                if "held" not in data[c]: data[c]["held"] = 0.0
                if "buy_price" not in data[c]: data[c]["buy_price"] = 0.0
                if "is_holding" not in data[c]: data[c]["is_holding"] = False
                if "total_profit" not in data[c]: data[c]["total_profit"] = 0.0

            # جلب الأسعار اللحظية من Binance (تتحمل الضغط العالي ولا تحظر السيرفرات)
            url = "https://api.binance.com/api/v3/ticker/price"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as f:
                ticker_data = json.loads(f.read().decode())
            
            # استخراج أسعار العملات المحددة فقط وتصفيتها
            market_prices = {}
            for item in ticker_data:
                sym = item['symbol']
                if sym in coin_mapping:
                    cid = coin_mapping[sym]
                    market_prices[cid] = float(item['price'])
            
            sample_readings = 0
            
            # معالجة استراتيجية التداول بناءً على أسعار Binance
            for cid, price in market_prices.items():
                h = data[cid]["history"]
                h.append(price)
                
                # إبقاء 3 قراءات فقط لتسريع عملية الفحص والتشخيص الحالية
                if len(h) > 3: h.pop(0)
                
                if cid == "bitcoin":
                    sample_readings = len(h)
                
                if len(h) < 3:
                    continue
                
                sma = sum(h) / len(h)
                std = (sum((x - sma)**2 for x in h) / len(h))**0.5
                lower = sma - (1.0 * std)
                
                # منطق الشراء
                if not data[cid]["is_holding"] and price <= lower:
                    data[cid].update({'held': 150 / price, 'buy_price': price, 'is_holding': True})
                    send_telegram(f"🎯 شراء عبر Binance: {cid.upper()} بسعر {price}$")
                
                # منطق البيع (ربح 1% أو خسارة 5%)
                elif data[cid]["is_holding"]:
                    take_profit_price = data[cid]['buy_price'] * 1.01 
                    stop_loss_price = data[cid]['buy_price'] * 0.95   
                    
                    if price >= take_profit_price:
                        diff = (price - data[cid]['buy_price']) * data[cid]['held']
                        data[cid]['total_profit'] += diff
                        send_telegram(f"✅ بيع بربح: {cid.upper()}\nالربح: {diff:.2f}$\nإجمالي أرباح العملة: {data[cid]['total_profit']:.2f}$")
                        data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False})
                        
                    elif price <= stop_loss_price:
                        diff = (price - data[cid]['buy_price']) * data[cid]['held']
                        data[cid]['total_profit'] += diff 
                        send_telegram(f"🛑 بيع بوقف الخسارة: {cid.upper()}\nالخسارة: {diff:.2f}$\nإجمالي أرباح العملة: {data[cid]['total_profit']:.2f}$")
                        data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False})
            
            # حفظ البيانات المحدثة بأمان
            with open(DATA_FILE, 'w') as f: json.dump(data, f)
            
            # إرسال تقرير تشخيصي مبدئي للتأكد من جمع البيانات بنجاح
            if sample_readings < 3:
                send_telegram(f"🔍 تقرير تشخيصي (Binance): جاري جمع البيانات حياً. القراءات الحالية: {sample_readings}/3")
            
            # فحص كل 5 دقائق (300 ثانية) وهو وقت ممتاز ومستقر جداً مع Binance
            time.sleep(300)
            
        except Exception as e: 
            send_telegram(f"⚠️ خطأ عام في نظام البوت: {str(e)}")
            time.sleep(60)

if __name__ == "__main__":
    threading.Thread(target=run_trading_bot, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
