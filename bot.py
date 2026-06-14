import os
import time
import threading
import json
import urllib.request
from flask import Flask

# إعداد خادم Flask البسيط لإرضاء Render
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_trading_bot():
    # هنا ضع نفس منطق التداول الخاص بك
    # (نفس الكود الذي كنت تستخدمه سابقاً في GitHub)
    while True:
        try:
            # منطق التداول هنا
            time.sleep(60)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    # تشغيل البوت في خيط منفصل (Thread)
    threading.Thread(target=run_trading_bot, daemon=True).start()
    # تشغيل خادم Flask
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
