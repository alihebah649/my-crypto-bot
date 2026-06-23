import os
import threading
from flask import Flask

app = Flask(__name__)

# 1. مسار الـ Health Check الأساسي لريندر
@app.route('/')
def home():
    return "🤖 My Halal Trading Bot is Alive and Running!", 200

def run_trading_bot():
    # هنا تضع حلقة الـ while True الرئيسية الخاصة بـ بوت التداول الخاص بك
    print("🚀 Trading Bot Loop Started Successfully...", flush=True)
    # كود التداول الخاص بك يستمر هنا...

if __name__ == "__main__":
    # 2. تشغيل البوت في خيط معالجة منفصل (Background Thread) فوراً
    t = threading.Thread(target=run_trading_bot, daemon=True)
    t.start()
    
    # 3. تشغيل Flask فوراً على المنفذ المطلوب لتخطي فحص ريندر
    port = int(os.environ.get('PORT', 8080))
    print(f"⚡ Launching Flask server on port {port}...", flush=True)
    
    # use_reloader=False ضرورية جداً لمنع تشغيل البوت مرتين في الخلفية
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
