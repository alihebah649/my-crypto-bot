import asyncio
import json
import os
import csv
import threading
import pandas as pd
import numpy as np
from datetime import datetime, UTC
import websockets
import requests
from flask import Flask

# --- 1. إعداد سيرفر Flask لاستقبال نبضات UptimeRobot ---
app = Flask(__name__)

@app.route('/')
def home():
    return {"status": "healthy", "engine": "running", "timestamp": datetime.now(UTC).isoformat()}, 200

def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# --- 2. إعدادات تلجرام بأمان من Render ---
TELEGRAM_TOKEN = os.getenv("TOKEN", "8672887924:AAGaLFIEbk_2MHq9gMb5ja2FJhVj-oG3M0I")
TELEGRAM_CHAT_ID = "199325566"

def send_telegram_message(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code != 200:
            print(f"⚠️ فشل إرسال تنبيه تلجرام: {response.text}")
    except Exception as e:
        print(f"⚠️ خطأ في الاتصال بتلجرام: {e}")

# --- 3. محرك الحسابات الفنية اللحظية ---
class AlphaSignalEngine:
    def __init__(self, rsi_period=14, ema_period=9):
        self.rsi_period = rsi_period
        self.ema_period = ema_period
        self.prices = []

    def update_price(self, price: float):
        self.prices.append(price)
        if len(self.prices) > 100: self.prices.pop(0)

    def calculate_indicators(self):
        if len(self.prices) < self.rsi_period + 1: return None, None
        df = pd.DataFrame(self.prices, columns=["price"])
        df["ema"] = df["price"].ewm(span=self.ema_period, adjust=False).mean()
        delta = df["price"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
        rs = gain / (loss + 1e-9)
        rsi = 100 - (100 / (1 + rs))
        return round(df["ema"].iloc[-1], 2), round(rsi.iloc[-1], 2)

    def get_signal(self, current_price, rsi):
        if rsi is None: return "HOLD"
        if rsi < 30: return "BUY"
        elif rsi > 70: return "SELL"
        return "HOLD"

# --- 4. هيكل تجميع وحفظ البيانات الإحصائية المطوّر ---
class ExecutionMetricsTracker:
    def __init__(self, analytics_dir="analytics"):
        self.latencies = []
        self.slippages = []
        self.total_signals = 0
        self.total_executed = 0
        self.trade_records = []
        self.analytics_dir = analytics_dir
        os.makedirs(self.analytics_dir, exist_ok=True)

    def record_signal(self): self.total_signals += 1

    def record_execution(self, timestamp, side, live_price, executed_price, volume, latency_ms, slippage_bps, rsi):
        self.latencies.append(latency_ms)
        self.slippages.append(slippage_bps)
        self.total_executed += 1
        self.trade_records.append({
            "timestamp": timestamp, "side": side, "live_price": live_price,
            "executed_price": executed_price, "volume": volume,
            "latency_ms": latency_ms, "slippage_bps": slippage_bps, "rsi": rsi
        })

    def save_data_to_analytics(self):
        if not self.latencies: return
        csv_file_path = os.path.join(self.analytics_dir, "shadow_trades_log.csv")
        file_exists = os.path.isfile(csv_file_path)
        with open(csv_file_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "side", "live_price", "executed_price", "volume", "latency_ms", "slippage_bps", "rsi"])
            if not file_exists: writer.writeheader()
            writer.writerows(self.trade_records)

# --- 5. محرك التداول الورقي اللانهائي المستمر 24/7 ---
async def start_live_shadow_engine():
    coinbase_ws_url = "wss://ws-feed.exchange.coinbase.com"
    tracker = ExecutionMetricsTracker()
    engine = AlphaSignalEngine(rsi_period=14, ema_period=9)
    tick_count = 0
    
    send_telegram_message("🤖 *بوت علي للتداول يعمل الآن على Render!*\n🎯 الوضع: *تداول ورقي مستمر 24/7*\n🔌 جاري الاتصال بالبث الحي لـ Coinbase...")
    
    while True:
        try:
            async with websockets.connect(coinbase_ws_url, ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps({"type": "subscribe", "product_ids": ["BTC-USD"], "channels": ["ticker"]}))
                print("✅ متصل بنجاح مع بث Coinbase اللحظي.")
                
                while True:
                    response = await ws.recv()
                    data = json.loads(response)
                    if data.get("type") != "ticker" or "price" not in data: continue
                    
                    tick_count += 1
                    live_price = float(data['price'])
                    live_volume = float(data.get('last_size', 0))
                    
                    engine.update_price(live_price)
                    ema, rsi = engine.calculate_indicators()
                    
                    if rsi is None: continue
                    
                    signal = engine.get_signal(live_price, rsi)
                    if signal in ["BUY", "SELL"]:
                        tracker.record_signal()
                        start_time = datetime.now(UTC)
                        await asyncio.sleep(np.random.uniform(0.02, 0.08))
                        latency = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
                        slippage = round(np.random.uniform(0.3, 2.5), 2)
                        factor = (1 + (slippage / 10000)) if signal == "BUY" else (1 - (slippage / 10000))
                        executed_price = round(live_price * factor, 2)
                        
                        tracker.record_execution(datetime.now(UTC).isoformat(), signal, live_price, executed_price, live_volume, latency, slippage, rsi)
                        tracker.save_data_to_analytics()
                        
                        # إشعارات فورية معربة بالكامل
                        emoji = "🟢" if signal == "BUY" else "🔴"
                        action_arabic = "شراء" if signal == "BUY" else "بيع"
                        
                        send_telegram_message(
                            f"{emoji} *تنفيذ صفقة تداول ورقي (محاكي)*\n"
                            f"• *الإجراء:* {action_arabic}\n"
                            f"• *سعر السوق اللحظي:* ${live_price:.2f}\n"
                            f"• *السعر التنفيذي المحاكي:* ${executed_price:.2f}\n"
                            f"• *مؤشر القوة النسبية RSI:* {rsi} | *المتوسط الأسي EMA:* {ema:.2f}\n"
                            f"• *زمن الاستجابة:* {latency}ms | *الانزلاق السعري:* {slippage} bps"
                        )
        except Exception as e:
            print(f"⚠️ انقطع الاتصال، جاري إعادة المحاولة... الخطأ: {e}")
            await asyncio.sleep(5)

def start_trading_loop():
    asyncio.run(start_live_shadow_engine())

if __name__ == "__main__":
    trading_thread = threading.Thread(target=start_trading_loop, daemon=True)
    trading_thread.start()
    run_flask()
