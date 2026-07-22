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
import time

# --- 1. إعداد سيرفر Flask لضمان العمل 24/7 ---
app = Flask(__name__)

@app.route('/')
def home():
    return {"status": "healthy", "engine": "running", "timestamp": datetime.now(UTC).isoformat()}, 200

def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# --- 2. إعدادات تلجرام بأمان وسحب التوكن من Render ---
TELEGRAM_TOKEN = os.getenv("TOKEN", "8672887924:AAGaLFIEbk_2MHq9gMb5ja2FJhVj-oG3M0I")
TELEGRAM_CHAT_ID = "199325566"

def send_telegram_message(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 429:
            print(f"⚠️ تلجرام يطلب التهدئة (429): {response.text}")
        elif response.status_code != 200:
            print(f"⚠️ فشل إرسال تنبيه تلجرام: {response.text}")
    except Exception as e:
        print(f"⚠️ خطأ في الاتصال بتلجرام: {e}")

# --- 3. محرك الحسابات الفنية اللحظية المتعدد لكل عملة ---
class AlphaSignalEngine:
    def __init__(self, rsi_period=14, ema_period=9):
        self.rsi_period = rsi_period
        self.ema_period = ema_period
        self.prices = {}

    def update_price(self, symbol: str, price: float):
        if symbol not in self.prices:
            self.prices[symbol] = []
        self.prices[symbol].append(price)
        if len(self.prices[symbol]) > 100: 
            self.prices[symbol].pop(0)

    def calculate_indicators(self, symbol: str):
        if symbol not in self.prices or len(self.prices[symbol]) < self.rsi_period + 1: 
            return None, None
        df = pd.DataFrame(self.prices[symbol], columns=["price"])
        df["ema"] = df["price"].ewm(span=self.ema_period, adjust=False).mean()
        delta = df["price"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
        rs = gain / (loss + 1e-9)
        rsi = 100 - (100 / (1 + rs))
        return round(df["ema"].iloc[-1], 2), round(rsi.iloc[-1], 2)

    def get_signal(self, rsi):
        if rsi is None: return "HOLD"
        if rsi < 30: return "BUY"
        elif rsi > 70: return "SELL"
        return "HOLD"

# --- 4. إدارة المحافظ المالية المستقلة والصفقات الفورية والتحليلات ---
class MultiPortfolioTracker:
    def __init__(self, initial_balance=10000.0, analytics_dir="analytics"):
        self.initial_balance = initial_balance
        self.analytics_dir = analytics_dir
        os.makedirs(self.analytics_dir, exist_ok=True)
        self.portfolios = {}
        
    def _init_symbol(self, symbol):
        if symbol not in self.portfolios:
            self.portfolios[symbol] = {
                "balance": self.initial_balance,
                "crypto_held": 0.0,
                "last_buy_price": 0.0,
                "has_position": False,
                "total_trades": 0,
                "winning_trades": 0,
                "total_pnl": 0.0
            }

    def process_trade(self, symbol, side, executed_price):
        self._init_symbol(symbol)
        p = self.portfolios[symbol]
        pnl = 0.0
        pnl_pct = 0.0
        trade_status = "EXEC"

        if side == "BUY" and not p["has_position"]:
            p["crypto_held"] = p["balance"] / executed_price
            p["last_buy_price"] = executed_price
            p["balance"] = 0.0
            p["has_position"] = True
            p["total_trades"] += 1
            trade_status = "OPEN_POSITION"
            
        elif side == "SELL" and p["has_position"]:
            revenue = p["crypto_held"] * executed_price
            pnl = revenue - (p["crypto_held"] * p["last_buy_price"])
            pnl_pct = (pnl / (p["crypto_held"] * p["last_buy_price"])) * 100
            
            p["balance"] = revenue
            p["crypto_held"] = 0.0
            p["has_position"] = False
            p["total_trades"] += 1
            p["total_pnl"] += pnl
            
            if pnl > 0:
                p["winning_trades"] += 1
            trade_status = "CLOSE_POSITION"
            
        total_equity = p["crypto_held"] * executed_price if p["has_position"] else p["balance"]
        return trade_status, round(pnl, 2), round(pnl_pct, 2), round(total_equity, 2)

    def save_to_csv(self, record):
        csv_file_path = os.path.join(self.analytics_dir, "shadow_trades_log.csv")
        file_exists = os.path.isfile(csv_file_path)
        with open(csv_file_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(record.keys()))
            if not file_exists: writer.writeheader()
            writer.writerow(record)

    def send_periodic_report(self):
        if not self.portfolios:
            send_telegram_message("📊 *التقرير الدوري لأداء البوت:*\nلا توجد صفقات منفذة حتى الآن.")
            return

        report_msg = "📊 *التقرير الدوري الشامل للمحفظة الإسلامية المتعددة* 📊\n\n"
        grand_total_pnl = 0.0
        
        for symbol, p in self.portfolios.items():
            win_rate = (p["winning_trades"] / p["total_trades"] * 100) if p["total_trades"] > 0 else 0.0
            grand_total_pnl += p["total_pnl"]
            
            clean_name = symbol.split("-")[0]
            report_msg += (
                f"🪙 *عملة {clean_name}:*\n"
                f"  • صافي الأرباح/الخسائر: ${p['total_pnl']:.2f}\n"
                f"  • إجمالي الصفقات: {p['total_trades']} | نسبة النجاح: {win_rate:.2f}%\n"
                f"  • الحالة: {'🔄 ممتلك للمركز' if p['has_position'] else '💵 سيولة متوفرة'}\n"
                f"───────────────────\n"
            )
        
        report_msg += f"📈 *إجمالي أرباح المحفظة الكلية المجمعة:* ${grand_total_pnl:,.2f}"
        send_telegram_message(report_msg)

# --- 5. محرك البث والتداول الورقي اللانهائي المستمر 24/7 ---
ISLAMIC_ASSETS = ["BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "AVAX-USD", "LINK-USD", "MATIC-USD"]

portfolio = MultiPortfolioTracker()
engine = AlphaSignalEngine(rsi_period=14, ema_period=9)

# قاموس لحفظ وقت آخر صفقة لكل عملة لتفادي حظر تلجرام (Cooldown: 5 دقائق)
last_trade_time = {asset: 0 for asset in ISLAMIC_ASSETS}

async def start_live_shadow_engine():
    coinbase_ws_url = "wss://ws-feed.exchange.coinbase.com"
    
    assets_string = ", ".join([a.split("-")[0] for a in ISLAMIC_ASSETS])
    send_telegram_message(
        f"🤖 *بوت علي المتعدد العملات يعمل الآن على Render!*\n"
        f"🎯 الوضع: *تداول ورقي إسلامي فوري (Spot) 24/7*\n"
        f"🪙 العملات المراقبة الحلال المعتمدة: \n`[{assets_string}]`\n"
        f"💰 المحفظة الافتراضية: *$10,000 لكل عملة بشكل مستقل*\n"
        f"🔌 جاري فتح الاتصال وقنوات البث المباشر..."
    )
    
    while True:
        try:
            async with websockets.connect(coinbase_ws_url, ping_interval=20, ping_timeout=20) as ws:
                subscribe_msg = {
                    "type": "subscribe",
                    "product_ids": ISLAMIC_ASSETS,
                    "channels": ["ticker"]
                }
                await ws.send(json.dumps(subscribe_msg))
                
                while True:
                    response = await ws.recv()
                    data = json.loads(response)
                    if data.get("type") != "ticker" or "price" not in data: continue
                    
                    symbol = data.get("product_id")
                    if symbol not in ISLAMIC_ASSETS: continue
                    
                    live_price = float(data['price'])
                    live_volume = float(data.get('last_size', 0))
                    
                    engine.update_price(symbol, live_price)
                    ema, rsi = engine.calculate_indicators(symbol)
                    
                    if rsi is None: continue
                    
                    signal = engine.get_signal(rsi)
                    
                    portfolio._init_symbol(symbol)
                    has_pos = portfolio.portfolios[symbol]["has_position"]
                    
                    # التحقق من تغيير الإشارة الفعلي
                    if (signal == "BUY" and has_pos) or (signal == "SELL" and not has_pos):
                        continue
                        
                    if signal in ["BUY", "SELL"]:
                        # حماية: التحقق من انقضاء فترة التهدئة (300 ثانية = 5 دقائق) للعملة المحددة منعاً لـ 429
                        current_timestamp = time.time()
                        if current_timestamp - last_trade_time[symbol] < 300:
                            continue
                        
                        last_trade_time[symbol] = current_timestamp
                        
                        start_time = datetime.now(UTC)
                        await asyncio.sleep(np.random.uniform(0.02, 0.08))
                        latency = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
                        slippage = round(np.random.uniform(0.3, 2.5), 2)
                        factor = (1 + (slippage / 10000)) if signal == "BUY" else (1 - (slippage / 10000))
                        executed_price = round(live_price * factor, 2)
                        
                        status, pnl, pnl_pct, total_equity = portfolio.process_trade(symbol, signal, executed_price)
                        
                        record = {
                            "timestamp": datetime.now(UTC).isoformat(), "symbol": symbol, "side": signal, "live_price": live_price,
                            "executed_price": executed_price, "volume": live_volume, "latency_ms": latency,
                            "slippage_bps": slippage, "rsi": rsi, "pnl": pnl, "portfolio_equity": total_equity
                        }
                        portfolio.save_to_csv(record)
                        
                        emoji = "🟢" if signal == "BUY" else "🔴"
                        clean_symbol = symbol.split("-")[0]
                        action_arabic = f"شراء (فتح مركز في {clean_symbol})" if signal == "BUY" else f"بيع (إغلاق وتسييل {clean_symbol})"
                        
                        pnl_text = f"• *الربح/الخسارة لهذه الصفقة:* ${pnl} ({pnl_pct}%)\n" if signal == "SELL" else ""
                        
                        msg = (
                            f"{emoji} *تم تنفيذ صفقة محاكاة ناجحة*\n"
                            f"• *العملة:* {clean_symbol}\n"
                            f"• *النوع:* {action_arabic}\n"
                            f"• *سعر السوق:* ${live_price:.2f}\n"
                            f"• *السعر المحاكي المنفذ:* ${executed_price:.2f}\n"
                            f"{pnl_text}"
                            f"• *إجمالي قيمة محفظة {clean_symbol} الآن:* ${total_equity:.2f}\n"
                            f"• *مؤشر RSI:* {rsi} | *مؤشر EMA:* {ema:.2f}\n"
                            f"• *زمن الاستجابة:* {latency}ms | *الانزلاق السعري:* {slippage} bps"
                        )
                        send_telegram_message(msg)
        except Exception as e:
            print(f"⚠️ خطأ في الاتصال، إعادة محاولة الاتصال خلال 5 ثوانٍ... {e}")
            await asyncio.sleep(5)

# --- 6. خيط مستقل لجدولة وإرسال التقرير الشامل التلقائي كل 12 ساعة ---
def daily_report_scheduler():
    import time
    while True:
        time.sleep(43200)
        try:
            portfolio.send_periodic_report()
        except Exception as e:
            print(f"Error sending periodic report: {e}")

def start_trading_loop():
    asyncio.run(start_live_shadow_engine())

if __name__ == "__main__":
    threading.Thread(target=start_trading_loop, daemon=True).start()
    threading.Thread(target=daily_report_scheduler, daemon=True).start()
    run_flask()
