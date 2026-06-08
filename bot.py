import time, urllib.request, json, os

# قراءة التوكن من خزنة GitHub التي أعددناها
TOKEN = os.environ['TOKEN']
CHAT_ID = "199325566"
usd_balance = 1000.0

coins = ["bitcoin", "ethereum", "cardano", "solana", "polkadot", "polygon-ecosystem-token", "avalanche-2", "binancecoin"]
history = {c: [] for c in coins}
portfolio = {c: {"held": 0.0, "buy_price": 0.0, "is_holding": False} for c in coins}

def send_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        data = json.dumps({"chat_id": CHAT_ID, "text": text}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except: pass

def get_bollinger(prices):
    if len(prices) < 20: return None, None
    sma = sum(prices) / 20
    variance = sum((x - sma) ** 2 for x in prices) / 20
    std_dev = (variance ** 0.5)
    return sma - (2 * std_dev), sma + (2 * std_dev)

def run_bot():
    try:
        url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids={','.join(coins)}&order=market_cap_desc"
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=15) as response:
            data = json.loads(response.read().decode())
        
        for c in data:
            coin_id = c['id']
            price = c['current_price']
            history[coin_id].append(price)
            if len(history[coin_id]) > 20: history[coin_id].pop(0)
            
            lower, upper = get_bollinger(history[coin_id])
            
            # الشراء
            if lower and not portfolio[coin_id]['is_holding'] and price <= lower:
                portfolio[coin_id].update({'held': (150 * 0.98) / price, 'buy_price': price, 'is_holding': True})
                send_telegram(f"🎯 شراء تلقائي: {c['symbol'].upper()} بسعر {price}")
            
            # البيع
            elif portfolio[coin_id]['is_holding']:
                if price >= portfolio[coin_id]['buy_price'] * 1.02 or (upper and price >= upper):
                    send_telegram(f"💰 بيع تلقائي: {c['symbol'].upper()} | الربح: {((price/portfolio[coin_id]['buy_price'])-1)*100:.2f}%")
                    portfolio[coin_id].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False})
        
        # إشعار للتأكيد أن البوت فحص السوق بنجاح
        send_telegram("✅ تم فحص السوق بنجاح من السحابة.")
        
    except Exception as e:
        send_telegram(f"⚠️ حدث خطأ في البوت: {str(e)}")

if __name__ == "__main__":
    run_bot()
