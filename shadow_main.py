import asyncio
import json
import os
import csv
import pandas as pd
import numpy as np
from datetime import datetime, UTC
import websockets
import requests

# --- إعدادات تلجرام المطابقة لـ Render ---
# تم تعديل KEY القراءة إلى "TOKEN" ليطابق لوحة تحكم Render الخاصة بك تماماً
TELEGRAM_TOKEN = os.getenv("TOKEN", "8672887924:AAGaLFIEbk_2MHq9gMb5ja2FJhVj-oG3M0I")
TELEGRAM_CHAT_ID = "199325566"

def send_telegram_message(message: str):
    """دالة إرسال إشعارات فورية إلى حسابك على تلجرام"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code != 200:
            print(f"⚠️ Telegram Alert Failed: {response.text}")
    except Exception as e:
        print(f"⚠️ Telegram Connection Error: {e}")

# --- 1. محرك الحسابات الفنية اللحظية ---
class AlphaSignalEngine:
    def __init__(self, rsi_period=14, ema_period=9):
        self.rsi_period = rsi_period
        self.ema_period = ema_period
        self.prices = []

    def update_price(self, price: float):
        self.prices.append(price)
        if len(self.prices) > 100:
            self.prices.pop(0)

    def calculate_indicators(self):
        if len(self.prices) < self.rsi_period + 1:
            return None, None
            
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

# --- 2. هيكل تجميع وحفظ البيانات الإحصائية المطوّر ---
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

        avg_latency = sum(self.latencies) / len(self.latencies)
        avg_slippage = sum(self.slippages) / len(self.slippages)
        exec_rate = (self.total_executed / self.total_signals) * 100 if self.total_signals > 0 else 0

        summary_data = {
            "session_end_time": datetime.now(UTC).isoformat(),
            "execution_rate_pct": round(exec_rate, 2),
            "total_signals": self.total_signals,
            "total_executed": self.total_executed,
            "latency_profile": {"avg_ms": round(avg_latency, 2), "min_ms": min(self.latencies), "max_ms": max(self.latencies)},
            "slippage_profile": {"avg_bps": round(avg_slippage, 2), "max_bps": max(self.slippages)}
        }
        with open(os.path.join(self.analytics_dir, "shadow_session_summary.json"), mode="w", encoding="utf-8") as f:
            json.dump(summary_data, f, indent=4, ensure_ascii=False)

    def generate_summary_report(self):
        if not self.latencies: return ""
        exec_rate = (self.total_executed / self.total_signals) * 100 if self.total_signals > 0 else 0
        avg_latency = sum(self.latencies)/len(self.latencies)
        avg_slippage = sum(self.slippages)/len(self.slippages)
        
        report = (
            "📊 *PRODUCTION READINESS REPORT*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"📈 *Execution Rate:* {exec_rate:.2f}% ({self.total_executed}/{self.total_signals})\n"
            f"⏱️ *Avg Latency:* {avg_latency:.2f}ms\n"
            f"📉 *Avg Slippage:* {avg_slippage:.2f} bps\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "💾 _Analytics Saved Successfully._"
        )
        return report

# --- 3. محرك تشغيل الـ Shadow Trading المتكامل ---
async def start_live_shadow_engine(max_ticks: int = 40):
    coinbase_ws_url = "wss://ws-feed.exchange.coinbase.com"
    tracker = ExecutionMetricsTracker()
    engine = AlphaSignalEngine(rsi_period=14, ema_period=9)
    tick_count = 0
    
    send_telegram_message("🚀 *Shadow Trading Engine Started...* \n🔌 Connecting to Coinbase WebSocket...")
    
    try:
        async with websockets.connect(coinbase_ws_url) as ws:
            await ws.send(json.dumps({"type": "subscribe", "product_ids": ["BTC-USD"], "channels": ["ticker"]}))
            print("✅ Connected to Coinbase! Streaming live market data...\n")
            
            while tick_count < max_ticks:
                response = await ws.recv()
                data = json.loads(response)
                if data.get("type") != "ticker" or "price" not in data: continue
                
                tick_count += 1
                live_price = float(data['price'])
                live_volume = float(data.get('last_size', 0))
                
                engine.update_price(live_price)
                ema, rsi = engine.calculate_indicators()
                
                if rsi is None:
                    print(f"⏳ Warming up Indicators ({tick_count:02d}/15) | Price: {live_price:.2f}")
                    continue
                
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
                    
                    # إرسال صفقة فورية للتملجرام
                    emoji = "🟢" if signal == "BUY" else "🔴"
                    send_telegram_message(
                        f"{emoji} *TRADE SIGNAL GENERATED*\n"
                        f"• *Action:* {signal}\n"
                        f"• *Market Price:* ${live_price:.2f}\n"
                        f"• *Executed:* ${executed_price:.2f}\n"
                        f"• *RSI:* {rsi} | *EMA:* {ema:.2f}\n"
                        f"• *Latency:* {latency}ms"
                    )
                    print(f"🎯 [SIGNAL:{signal}] | Price: {live_price:.2f} | ⏱️ {latency}ms")
                else:
                    print(f"💤 Live Tick {tick_count:02d} | Price: {live_price:.2f} | RSI: {rsi} | Mode: HOLD")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        send_telegram_message(f"❌ *Engine Error:* `{str(e)}`")
        
    tracker.save_data_to_analytics()
    report = tracker.generate_summary_report()
    if report:
        send_telegram_message(report)

if __name__ == "__main__":
    asyncio.run(start_live_shadow_engine(max_ticks=40))
