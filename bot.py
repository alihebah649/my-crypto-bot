import json, os, urllib.request, time, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# خادم وهمي لمنع Render من إغلاق البوت
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_server():
    server = HTTPServer(('0.0.0.0', int(os.environ.get('PORT', 8080))), SimpleHandler)
    server.serve_forever()

# منطق البوت الأساسي
def run_trading_bot():
    TOKEN = os.environ['TOKEN']
    CHAT_ID = "199325566"
    DATA_FILE = "data.json"
    coins = ["bitcoin", "ethereum", "chainlink", "near", "arbitrum", "optimism", "render", "solana"]

    def send_telegram(text):
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            data = json.dumps({"chat_id": CHAT_ID, "text": text}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
        except: pass

    while True:
        try:
            # تحميل البيانات
            data = {}
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r') as f: data = json.load(f)
            else:
                data = {c: {"history": [], "held": 0.0, "buy_price": 0.0, "is_holding": False, "total_profit": 0.0} for c in coins}

            url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={','.join(coins)}"
            with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=15) as f:
                market = json.loads(f.read().decode())
            
            for c in market:
                cid = c['id']
                price = c['current_price']
                h = data[cid]["history"]
                h.append(price)
                if len(h) > 20: h.pop(0)
                
                sma = sum(h) / len(h)
                std = (sum((x - sma)**2 for x in h) / len(h))**0.5
                lower = sma - (1.5 * std)
                
                if not data[cid]["is_holding"] and price <= lower:
                    data[cid].update({'held': 150 / price, 'buy_price': price, 'is_holding': True})
                    send_telegram(f"🎯 شراء: {c['symbol'].upper()} بسعر {price}$")
                
                elif data[cid]["is_holding"] and (price >= data[cid]['buy_price'] * 1.015):
                    diff = (price - data[cid]['buy_price']) * data[cid]['held']
                    data[cid]['total_profit'] += diff
                    send_telegram(f"✅ بيع: {c['symbol'].upper()}\nالربح: {diff:.2f}$\nالإجمالي: {data[cid]['total_profit']:.2f}$")
                    data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False})
            
            with open(DATA_FILE, 'w') as f: json.dump(data, f)
            time.sleep(60)
        except Exception as e: 
            send_telegram(f"⚠️ خطأ: {str(e)}")
            time.sleep(300)

if __name__ == "__main__":
    # تشغيل الخادم الوهمي في مسار والبوت في مسار آخر
    threading.Thread(target=run_server, daemon=True).start()
