import os
import json
import requests

def fetch_binance_historical_data():
    print("⏳ جاري سحب البيانات التاريخية مباشرة من Binance API العامة...")
    
    # سحب أحدث 500 شمعة (كل شمعة تمثل 5 دقائق مثلاً 5m أو دقيقة 1m) لزوج BTCUSDT
    symbol = "BTCUSDT"
    interval = "5m"
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit=500"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        raw_candles = response.json()
        
        # ترتيب البيانات لتصبح ميكانيكية حتمية ومفهومة للبوت
        formatted_ticks = []
        for c in raw_candles:
            formatted_ticks.append({
                "timestamp": float(c[0]),      # وقت فتح الشمعة
                "open_price": float(c[1]),     # سعر الفتح
                "high": float(c[2]),           # أعلى سعر
                "low": float(c[3]),            # أدنى سعر
                "close_price": float(c[4]),    # سعر الإغلاق
                "bid_vol": float(c[5]) * 0.6,  # محاكاة لحجم طلبات الشراء
                "ask_vol": float(c[5]) * 0.4   # محاكاة لحجم طلبات البيع
            })
            
        print(f"✅ تم سحب {len(formatted_ticks)} نقطة بيانات بنجاح من Binance!")
        return formatted_ticks
    except Exception as e:
        print(f"❌ فشل سحب البيانات من Binance: {e}")
        return None

def save_to_local_and_jsonbin(data):
    if not data:
        return
        
    # 1. الحفظ المحلي في السيرفر (مجلد data) ليقرأ منه ملف main_replay.py
    os.makedirs("data", exist_ok=True)
    local_path = "data/binance_24h_data.json"
    with open(local_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    print(f"💾 تم حفظ البيانات محلياً في السيرفر بمسار: {local_path}")
    
    # 2. إرسال وتحديث البيانات في منصة JSONBIN (سحابياً)
    # ملاحظة: تأكد من إضافة الـ Master Key والـ Bin ID في إعدادات Render (Environment Variables)
    jsonbin_key = os.getenv("JSONBIN_API_KEY")
    jsonbin_id = os.getenv("JSONBIN_BIN_ID")
    
    if jsonbin_key and jsonbin_id:
        print("☁️ جاري مزامنة البيانات مع منصة JSONBIN...")
        headers = {
            "Content-Type": "application/json",
            "X-Master-Key": jsonbin_key
        }
        bin_url = f"https://api.jsonbin.io/v3/b/{jsonbin_id}"
        try:
            res = requests.put(bin_url, json=data, headers=headers, timeout=15)
            if res.status_code == 200:
                print("✨ تم قفل ومزامنة البيانات السحابية في JSONBIN بنجاح!")
            else:
                print(f"⚠️ فشل التحديث في JSONBIN، كود الاستجابة: {res.status_code}")
        except Exception as e:
            print(f"⚠️ حدث خطأ أثناء الاتصال بـ JSONBIN: {e}")
    else:
        print("ℹ️ لم يتم العثور على متغيرات JSONBIN البيئية في Render، تم الاكتفاء بالنسخة المحلية.")

if __name__ == "__main__":
    market_data = fetch_binance_historical_data()
    save_to_local_and_jsonbin(market_data)
