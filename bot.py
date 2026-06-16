import os
import time
import threading
import json
import urllib.request
import urllib.error
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "Diagnostic Bot is running!"

def run_trading_bot():
    TOKEN = os.environ['TOKEN']
    CHAT_ID = "199325566"
    DATA_FILE = "data.json"
    
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

    # رسالة بدء التشغيل للتشخيص
    send_telegram("🔄 تم إعادة تشغيل السيرفر أو تحديث الكود. أبدأ من جديد!")
    
    while True:
        try:
            data = {}
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r') as f: data = json.load(f)
            else:
                data = {c: {"history": [], "held": 0.0, "buy_price": 0.0, "is_holding": False, "total_profit": 0.0} for c in coins}

            time.sleep(2) 
            url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={','.join(coins)}"
            
            # محاولة جلب البيانات مع صيد الأخطاء بدقة
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as f:
                market = json.loads(f.read().decode())
            
            # أخذ عينة لعملة واحدة (بيتكوين مثلاً) للتقرير التشخيصي
            sample_readings = 0
            
            for c in market:
                cid = c['id']
                price = c['current_price']
                
                if cid not in data:
                    data[cid] = {"history": [], "held": 0.0, "buy_price": 0.0, "is_holding": False, "total_profit": 0.0}
                    
                h = data[cid]["history"]
                h.append(price)
                
                # تخفيض الحد الأقصى للتاريخ إلى 3 قراءات فقط للتشخيص
                if len(h) > 3: h.pop(0)
                
                if cid == "bitcoin":
                    sample_readings = len(h)
                
                # تخفيض شرط البدء إلى 3 قراءات
                if len(h) < 3:
                    continue
                
                sma = sum(h) / len(h)
                std = (sum((x - sma)**2 for x in h) / len(h))**0.5
                lower = sma - (1.0 * std)
                
                if not data[cid]["is_holding"] and price <= lower:
                    data[cid].update({'held': 150 / price, 'buy_price': price, 'is_holding': True})
                    send_telegram(f"🎯 شراء: {c['symbol'].upper()} بسعر {price}$")
                
                elif data[cid]["is_holding"]:
                    take_profit_price = data[cid]['buy_price'] * 1.01 
                    stop_loss_price = data[cid]['buy_price'] * 0.95   
                    
                    if price >= take_profit_price:
                        diff = (price - data[cid]['buy_price']) * data[cid]['held']
                        data[cid]['total_profit'] += diff
                        send_telegram(f"✅ بيع بربح: {c['symbol'].upper()}\nالربح: {diff:.2f}$")
                        data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False})
                        
                    elif price <= stop_loss_price:
                        diff = (price - data[cid]['buy_price']) * data[cid]['held']
                        data[cid]['total_profit'] += diff 
                        send_telegram(f"🛑 بيع بوقف الخسارة: {c['symbol'].upper()}\nالخسارة: {diff:.2f}$")
                        data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False})
            
            with open(DATA_FILE, 'w') as f: json.dump(data, f)
            
            # إرسال تقرير تشخيصي كل دورة فحص للتأكد أن البوت لا يزال مستيقظاً ويجمع البيانات
            if sample_readings < 3:
                send_telegram(f"🔍 تقرير تشخيصي: جاري جمع البيانات. القراءات الحالية: {sample_readings}/3")
            
            time.sleep(900) # فحص كل 15 دقيقة
            
        except urllib.error.HTTPError as e:
            # هذا السطر سيكشف إذا كان CoinGecko يحظر البوت سراً
            send_telegram(f"🚫 تم حظر الاتصال من CoinGecko! الكود: {e.code}")
            time.sleep(600)
        except Exception as e: 
            send_telegram(f"⚠️ خطأ عام أوقف البوت: {str(e)}")
            time.sleep(300)

if __name__ == "__main__":
    threading.Thread(target=run_trading_bot, daemon=True).start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
