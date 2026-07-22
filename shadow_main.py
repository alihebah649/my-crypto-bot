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

# --- 4. إدارة المحفظة المالية والصفقات والتحليلات ---
class PortfolioTracker:
    def __init__(self, initial_balance=10000.0, analytics_dir="analytics"):
        self.balance = initial_balance
        self.initial_balance = initial_balance
        self.crypto_held = 0.0
        self.last_buy_price = 0.0
        self.has_position = False
        
        self.total_trades = 0
        self.winning_trades = 0
        self.total_pnl = 0.0
        
        self.analytics_dir = analytics_dir
        os.makedirs(self.analytics_dir, exist_ok=True)

    def process_trade(self, side, executed_price):
        pnl = 0.0
        pnl_pct = 0.0
        trade_status = "EXEC"

        if side == "BUY" and not self.has_position:
            # شراء بكامل السيولة المتوفرة لمحاكاة كاملة
            self.crypto_held = self.balance / executed_price
            self.last_buy_price = executed_price
            self.balance = 0.0
            self.has_position = True
            self.total_trades += 1
            trade_status = "OPEN_POSITION"
            
        elif side == "SELL" and self.has_position:
            # بيع كامل الكمية المحفوظة وإغلاق المركز مالياً
            revenue = self.crypto_held * executed_price
            pnl = revenue - (self.crypto_held * self.last_buy_price)
            pnl_pct = (pnl / (self.crypto_held * self.last_buy_price)) * 100
            
            self.balance = revenue
            self.crypto_held = 0.0
            self.has_position = False
            self.total_trades += 1
            self.total_pnl += pnl
            
            if pnl > 0:
                self.winning_trades += 1
            trade_status = "CLOSE_POSITION"
            
        return trade_status, round(pnl, 2), round(pnl_pct, 2), round(self.get_total_equity(executed_price), 2)

    def get_total_equity(self, current_price):
        if self.has_position:
            return self.crypto_held * current_price
        return self.balance

    def save_to_csv(self, record):
        csv_file_path = os.path.join(self.analytics_dir, "shadow_trades_log.csv")
        file_exists = os.path.isfile(csv_file_path)
        with open(csv_file_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(record.keys()))
            if not file_exists: writer.writeheader()
            writer.writerow(record)

    def send_daily_report(self, current_price):
        equity = self.get_total_equity(current_price)
        net_return_pct = ((equity - self.initial_balance) / self.initial_balance) * 100
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0.0
        
        report_msg = (
            f"📊 *التقرير الدوري لأداء البوت والربحية* 📊\n\n"
            f"• *رأس المال الحالي الكلي:* ${equity:,.2f}\n"
            f"• *رأس المال البدائي:* ${self.initial_balance:,.2f}\n"
            f"• *صافي الأرباح/الخسائر:* ${self.total_pnl:,.2f}\n"
            f"• *معدل العائد الإجمالي:* {net_return_pct:.2f}%\n"
            f"• *إجمالي الصفقات المنفذة:* {self.total_trades}\n"
            f"• *الصفقات الرابحة:* {self.winning_trades}\n"
            f"• *نسبة النجاح (Win Rate):* {win_rate:.2f}%\n"
            f"• *حالة المركز الحالي:* {'🔄 ممتلك للمراكز' if self.has_position else '💵 سيولة نقدية جاهزة'}"
        )
        send_telegram_message(report_msg)

# --- 5. محرك التداول الورقي اللانهائي المستمر 24/7 ---
portfolio = PortfolioTracker()

async def start_live_shadow_engine():
    coinbase_ws_url = "wss://ws-feed.exchange.coinbase.com"
    engine = AlphaSignalEngine(rsi_period=14, ema_period=9)
    
    send_telegram_message("🤖 *بوت علي للتداول يعمل الآن على Render!*\n🎯 الوضع: *تداول ورقي متقدم + تتبع كامل للأرباح 24/7*\n💰 المحفظة الافتراضية: *$10,000*\n🔌 جاري الاتصال بـ Coinbase...")
    
    while True:
        try:
            async with websockets.connect(coinbase_ws_url, ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps({"type": "subscribe", "product_ids": ["BTC-USD"], "channels": ["ticker"]}))
                
                while True:
                    response = await ws.recv()
                    data = json.loads(response)
                    if data.get("type") != "ticker" or "price" not in data: continue
                    
                    live_price = float(data['price'])
                    live_volume = float(data.get('last_size', 0))
                    
                    engine.update_price(live_price)
                    ema, rsi = engine.calculate_indicators()
                    
                    if rsi is None: continue
                    
                    signal = engine.get_signal(live_price, rsi)
                    
                    # تصفية إشارات التكرار لضمان فتح وإغلاق منطقي للمراكز
                    if (signal == "BUY" and portfolio.has_position) or (signal == "SELL" and not portfolio.has_position):
                        continue
                        
                    if signal in ["BUY", "SELL"]:
                        start_time = datetime.now(UTC)
                        await asyncio.sleep(np.random.uniform(0.02, 0.08))
                        latency = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
                        slippage = round(np.random.uniform(0.3, 2.5), 2)
                        factor = (1 + (slippage / 10000)) if signal == "BUY" else (1 - (slippage / 10000))
                        executed_price = round(live_price * factor, 2)
                        
                        # معالجة الصفقة مالياً في المحفظة
                        status, pnl, pnl_pct, total_equity = portfolio.process_trade(signal, executed_price)
                        
                        # تسجيل البيانات
                        record = {
                            "timestamp": datetime.now(UTC).isoformat(), "side": signal, "live_price": live_price,
                            "executed_price": executed_price, "volume": live_volume, "latency_ms": latency,
                            "slippage_bps": slippage, "rsi": rsi, "pnl": pnl, "portfolio_equity": total_equity
                        }
                        portfolio.save_to_csv(record)
                        
                        # إرسال تقرير فوري دقيق مع الربح والخسارة
                        emoji = "🟢" if signal == "BUY" else "🔴"
                        action_arabic = "شراء (فتح مركز)" if signal == "BUY" else "بيع (إغلاق وتسييل)"
                        
                        pnl_text = f"• *الربح/الخسارة لهذه الصفقة:* ${pnl} ({pnl_pct}%)\n" if signal == "SELL" else ""
                        
                        send_telegram_message(
                            f"{emoji} *تم تنفيذ تداول محاكي ناجح*\n"
                            f"• *الإجراء:* {action_arabic}\n"
                            f"• *سعر السوق اللحظي:* ${live_price:.2f}\n"
                            f"• *السعر التنفيذي الفعلي:* ${executed_price:.2f}\n"
                            {pnl_text}
                            f"• *إجمالي قيمة المحفظة الآن:* ${total_equity:.2f}\n"
                            f"• *مؤشر RSI:* {rsi} | *المتوسط EMA:* {ema:.2f}\n"
                            f"• *الاستجابة:* {latency}ms | *الانزلاق:* {slippage} bps"
                        )
        except Exception as e:
            print(f"⚠️ خطأ في الاتصال، إعادة محاولة... {e}")
            await asyncio.sleep(5)

# --- 6. خيط مستقل لبث التقرير التلقائي كل 12 ساعة ---
def daily_report_scheduler():
    import time
    while True:
        # ينتظر 12 ساعة (43200 ثانية) لإرسال التقرير الدوري التالي تلقائياً
        time.sleep(43200)
        try:
            # جلب آخر سعر معروف لإرسال التقرير بدقة
            csv_file_path = "analytics/shadow_trades_log.csv"
            if os.path.isfile(csv_file_path):
                df = pd.read_csv(csv_file_path)
                if not df.empty:
                    last_price = float(df['executed_price'].iloc[-1])
                    portfolio.send_daily_report(last_price)
        except Exception as e:
            print(f"Error sending periodic report: {e}")

def start_trading_loop():
    asyncio.run(start_live_shadow_engine())

if __name__ == "__main__":
    # خيط التداول
    threading.Thread(target=start_trading_loop, daemon=True).start()
    # خيط التقرير الدوري
    threading.Thread(target=daily_report_scheduler, daemon=True).start()
    # تشغيل Flask
    run_flask()
