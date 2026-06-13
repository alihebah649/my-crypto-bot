import json, os, urllib.request

TOKEN = os.environ['TOKEN']
CHAT_ID = "199325566"
DATA_FILE = "data.json"

# قائمة العملات
coins = ["bitcoin", "ethereum", "chainlink", "near", "arbitrum", "optimism", "render", "solana"]

def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f: return json.load(f)
    return {c: {"history": [], "held": 0.0, "buy_price": 0.0, "is_holding": False} for c in coins}

def save_data(data):
    with open(DATA_FILE, 'w') as f: json.dump(data, f)

def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = json.dumps({"chat_id": CHAT_ID, "text": text}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except: pass

def run_bot():
    data = load_data()
    try:
        url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={','.join(coins)}&order=market_cap_desc"
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
            lower, upper = sma - (1.5 * std), sma + (1.5 * std)
            
            if not data[cid]["is_holding"] and price <= lower:
                data[cid].update({'held': 150 / price, 'buy_price': price, 'is_holding': True})
                send_telegram(f"🎯 شراء: {c['symbol'].upper()} بسعر {price}")
            elif data[cid]["is_holding"] and (price >= data[cid]['buy_price'] * 1.015):
                send_telegram(f"💰 بيع: {c['symbol'].upper()} بربح 1.5%")
                data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False})
        
        save_data(data)
    except Exception as e: send_telegram(f"⚠️ خطأ: {str(e)}")

if __name__ == "__main__": run_bot()
