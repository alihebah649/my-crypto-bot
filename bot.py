import os
import time
import threading
import json
import urllib.request
import urllib.error
from flask import Flask

# إعداد خادم Flask لإبقاء السيرفر حياً
app = Flask(__name__)

@app.route('/')
def home():
    return "Halal Trading Bot is running smoothly!"

def run_trading_bot():
    TOKEN = os.environ['TOKEN']
    CHAT_ID = "199325566"
    DATA_FILE = "data.json"
    
    # القائمة النقية المتوافقة مع الشريعة الإسلامية
    coins = [
        "bitcoin", "ethereum", "solana", "chainlink", "cardano", 
        "polkadot", "near", "arbitrum", "optimism", "render"
    ]

    def send_telegram(text):
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            data = json.dumps({"chat_id": CHAT_ID, "text": text}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
        except Exception as e: 
            print(f"Telegram Error: {e}")

    # إعلان بدء التشغيل والتشخيص
    send_telegram("🔄 تم إعادة تشغيل السيرفر وتحديث الكود بنجاح. أبدأ الفحص الآن!")
    
    while True:
        try:
            data = {}
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r') as f: 
                    try:
                        data = json.load(f)
                    except json.JSONDecodeError:
                        data = {}
            
            # --- حماية برمجية حاسمة لمنع خطأ 'total_profit' ---
            # هذا الجزء يفحص الملف وإذا وجد أي نقص في أي عملة يكملها تلقائياً دون انهيار
            for c in coins:
                if c not in data:
                    data[c] = {}
                if "history" not in data[c]: data[c]["history"] = []
                if "held" not in data[c]: data[c]["held"] = 0.0
                if "buy_price" not in data[c]: data[c]["buy_price"] = 0.0
                if "is_holding" not in data[c]: data[c]["is_holding"] = False
                if "total_profit" not in data[c]: data[c]["total_profit"] = 0.0

            time.sleep(2) 
            url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={','.join(coins)}"
            
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as f:
                market = json.loads(f.read().decode())
            
            sample_readings = 0
            
            for c in market:
                cid = c['id']
                price = c['current_price']
                
                if cid not in data:
                    continue
                    
                h = data[cid]["history"]
                h.append(price)
                
                # تخفيض الحد لتسريع التشخيص (3 قراءات فقط للتأكد من عمل البوت)
                if len(h) > 3: h.pop(0)
                
                if cid == "bitcoin":
                    sample_readings = len(h)
                
                if len(h) < 3:
                    continue
                
                sma = sum(h) / len(h)
                std = (sum((x - sma)**2 for x in h) / len(h))**0.5
                lower = sma - (1.0 * std)
                
                # --- منطق الشراء ---
                if not data[cid]["is_holding"] and price <= lower:
                    data[cid].update({'held': 150 / price, 'buy_price': price, 'is_holding': True})
                    send_telegram(f"🎯 شراء: {c['symbol'].upper()} بسعر {price}$")
                
                # --- منطق البيع (جني أرباح 1% أو وقف خسارة 5%) ---
                elif data[cid]["is_holding"]:
                    take_profit_price = data[cid]['buy_price'] * 1.01 
                    stop_loss_price = data[cid]['buy_price'] * 0.95   
                    
                    if price >= take_profit_price:
                        diff = (price - data[cid]['buy_price']) * data[cid]['held']
                        data[cid]['total_profit'] += diff
                        send_telegram(f"✅ بيع بربح: {c['symbol'].upper()}\nالربح: {diff:.2f}$\nالإجمالي الحالي: {data[cid]['total_profit']:.2f}$")
                        data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False})
                        
                    elif price <= stop_loss_price:
                        diff = (price - data[cid]['buy_price']) * data[cid]['held']
                        data[cid]['total_profit'] += diff # ستكون القيمة سالبة وتخصم تلقائياً
                        send_telegram(f"🛑 بيع بوقف الخسارة: {c['symbol'].upper()}\nالخسارة: {diff:.2f}$\nالإجمالي الحالي: {data[cid]['total_profit']:.2f}$")
                        data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False})
            
            # حفظ البيانات المحدثة
            with open(DATA_FILE, 'w') as f: json.dump(data, f)
            
            # تقرير التشخيص المؤقت لضمان الجمع بنجاح
            if sample_readings < 3:
                send_telegram(f"🔍 تقرير تشخيصي: جاري جمع البيانات بنجاح. القراءات الحالية: {sample_readings}/3")
            
            time.sleep(900) # فحص هادئ كل 15 دقيقة لمنع الحظر
            
        except urllib.error.HTTPError as e:
            if e.code == 429:
                send_telegram("🚫 CoinGecko طلب انتظار (Rate Limit 429). سأرتاح لـ 10 دقائق لتجنب الحظر.")
                time.sleep(600)
            else:
                send_telegram(f"🚫 خطأ اتصال CoinGecko كود: {e.code}")
                time.sleep(300)
        except Exception as e: 
            send_telegram(f"⚠️ خطأ عام أوقف البوت: {str(e)}")
            time.sleep(300)

if __name__ == "__main__":
    threading.Thread(target=run_trading_bot, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
