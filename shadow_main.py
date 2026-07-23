import asyncio
import json
import os
import csv
import threading
import pandas as pd
import numpy as np
from datetime import datetime, UTC, timedelta
import websockets
import requests
from flask import Flask
import time

app = Flask(__name__)

@app.route('/')
def home():
    return {"status": "healthy", "engine": "running", "timestamp": datetime.now(UTC).isoformat()}, 200

def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

TELEGRAM_TOKEN = os.getenv("TOKEN", "8672887924:AAGaLFIEbk_2MHq9gMb5ja2FJhVj-oG3M0I")
TELEGRAM_CHAT_ID = "199325566"
telegram_cooldown_until = 0.0

def send_telegram_message(message: str):
    global telegram_cooldown_until
    if time.time() < telegram_cooldown_until:
        print(f"ℹ️ [تخطي تلجرام]: {message.replace('\n', ' | ')}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=5)
        if response.status_code == 429:
            try:
                res_data = response.json()
                retry_after = int(res_data.get("parameters", {}).get("retry_after", 300))
            except Exception:
                retry_after = 300
            telegram_cooldown_until = time.time() + retry_after
            print(f"⚠️ تجميد تلجرام لـ {retry_after} ثانية.")
        elif response.status_code != 200:
            print(f"⚠️ فشل تلجرام: {response.text}")
    except Exception as e:
        print(f"⚠️ خطأ تلجرام: {e}")

class AlphaSignalEngine:
    def __init__(self, rsi_period=14, ema_period=9):
        self.rsi_period = rsi_period
        self.ema_period = ema_period
        self.prices = {}

    def update_price(self, symbol: str, price: float):
        if symbol not in self.prices: self.prices[symbol] = []
        self.prices[symbol].append(price)
        if len(self.prices[symbol]) > 100: self.prices[symbol].pop(0)

    def calculate_indicators(self, symbol: str):
        if symbol not in self.prices or len(self.prices[symbol]) < self.rsi_period + 1: return None, None
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

class MultiPortfolioTracker:
    def __init__(self, initial_balance=10000.0, analytics_dir="analytics"):
        self.initial_balance = initial_balance
        self.analytics_dir = analytics_dir
        os.makedirs(self.analytics_dir, exist_ok=True)
        self.portfolios = {}
        self.recent_trades = []
        
    def _init_symbol(self, symbol):
        if symbol not in self.portfolios:
            self.portfolios[symbol] = {
                "balance": self.initial_balance, "crypto_held": 0.0, "last_buy_price": 0.0,
                "has_position": False, "total_trades": 0, "winning_trades": 0, "total_pnl": 0.0
            }

    def process_trade(self, symbol, side, executed_price, rsi_value):
        self._init_symbol(symbol)
        p = self.portfolios[symbol]
        pnl, pnl_pct, total_equity, used_amount = 0.0, 0.0, 0.0, 0.0

        if side == "BUY" and not p["has_position"]:
            used_amount = p["balance"]
            p["crypto_held"] = p["balance"] / executed_price
            p["last_buy_price"] = executed_price
            p["balance"] = 0.0
            p["has_position"] = True
            p["total_trades"] += 1
            
        elif side == "SELL" and p["has_position"]:
            revenue = p["crypto_held"] * executed_price
            pnl = revenue - (p["crypto_held"] * p["last_buy_price"])
            pnl_pct = (pnl / (p["crypto_held"] * p["last_buy_price"])) * 100
            p["balance"] = revenue
            p["crypto_held"] = 0.0
            p["has_position"] = False
            p["total_trades"] += 1
            p["total_pnl"] += pnl
            is_win = 1 if pnl > 0 else 0
            if pnl > 0: p["winning_trades"] += 1
            
            self.recent_trades.append({
                "timestamp": datetime.now(UTC), "symbol": symbol, "win": is_win, "loss": 1 - is_win, "pnl": pnl
            })
            
        total_equity = p["crypto_held"] * executed_price if p["has_position"] else p["balance"]
        return pnl, pnl_pct, total_equity, used_amount

    def save_to_csv(self, record):
        csv_file_path = os.path.join(self.analytics_dir, "shadow_trades_log.csv")
        file_exists = os.path.isfile(csv_file_path)
        with open(csv_file_path, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(record.keys()))
            if not file_exists: writer.writeheader()
            writer.writerow(record)

    def generate_harvest_report(self, title_type: str, delta_days: int):
        now = datetime.now(UTC)
        cutoff_time = now - timedelta(days=delta_days)
        filtered_trades = [t for t in self.recent_trades if t["timestamp"] >= cutoff_time]
        current_date_str = now.strftime("%Y-%m-%d")
        header = f"📊 حصاد {title_type} الشامل 📊\n📅 التاريخ المنتهي: {current_date_str}\n\n"
        
        if not filtered_trades:
            header += "🚫 لا توجد صفقات مسجلة في هذه الفترة بعد."
            send_telegram_message(header)
            return

        summary = {}
        for t in filtered_trades:
            sym = t["symbol"].split("-")[0]
            if sym not in summary: summary[sym] = {"win": 0, "loss": 0, "net": 0.0}
            summary[sym]["win"] += t["win"]
            summary[sym]["loss"] += t["loss"]
            summary[sym]["net"] += t["pnl"]
            
        report_msg = header
        report_msg += "COIN      | WIN | LOSS | NET (FEES)\n"
        report_msg += "--------------------------------------\n"
        total_win, total_loss, total_net = 0, 0, 0.0
        
        for coin, data in summary.items():
            total_win += data["win"]
            total_loss += data["loss"]
            total_net += data["net"]
            report_msg += f"{coin:<9} | {data['win']:<3} | {data['loss']:<4} | {data['net']:.2f}$\n"
            
        report_msg += "--------------------------------------\n"
        report_msg += f"TOTAL     | {total_win:<3} | {total_loss:<4} | {total_net:.2f}$"
        send_telegram_message(report_msg)

ISLAMIC_ASSETS = ["BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "AVAX-USD", "LINK-USD", "MATIC-USD"]
portfolio = MultiPortfolioTracker()
engine = AlphaSignalEngine(rsi_period=14, ema_period=9)
last_trade_time = {asset: 0 for asset in ISLAMIC_ASSETS}

async def start_live_shadow_engine():
    send_telegram_message("🤖 بوت المحاكاة المطور جاهز وبدأ رصد العملات...")
    while True:
        try:
            async with websockets.connect("wss://ws-feed.exchange.coinbase.com", ping_interval=20, ping_timeout=20) as ws:
                subscribe_msg = {"type": "subscribe", "product_ids": ISLAMIC_ASSETS, "channels": ["ticker"]}
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
                    if (signal == "BUY" and has_pos) or (signal == "SELL" and not has_pos): continue
                        
                    if signal in ["BUY", "SELL"]:
                        current_timestamp = time.time()
                        if current_timestamp - last_trade_time[symbol] < 300: continue
                        last_trade_time[symbol] = current_timestamp
                        
                        start_time = datetime.now(UTC)
                        await asyncio.sleep(np.random.uniform(0.02, 0.08))
                        latency = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
                        slippage = round(np.random.uniform(0.3, 2.5), 2)
                        factor = (1 + (slippage / 10000)) if signal == "BUY" else (1 - (slippage / 10000))
                        executed_price = round(live_price * factor, 2)
                        
                        pnl, pnl_pct, total_equity, used_amount = portfolio.process_trade(symbol, signal, executed_price, rsi)
                        record = {
                            "timestamp": datetime.now(UTC).isoformat(), "symbol": symbol, "side": signal, "live_price": live_price,
                            "executed_price": executed_price, "volume": live_volume, "latency_ms": latency,
                            "slippage_bps": slippage, "rsi": rsi, "pnl": pnl, "portfolio_equity": total_equity
                        }
                        portfolio.save_to_csv(record)
                        clean_symbol = symbol.split("-")[0]
                        
                        if signal == "BUY":
                            msg = "🟢 **صفقة شراء جديدة**\n"
                            msg += f"1️⃣ **المبلغ المستخدم لشراء الصفقة:** ${used_amount}\n"
                            msg += f"2️⃣ **اسم العملة:** {clean_symbol}\n"
                            msg += f"3️⃣ **سبب الشراء:** هبوط مؤشر الـ RSI إلى {rsi} (منطقة ذروة البيع ولحظة ارتداد فني)."
                        else:
                            msg = "🔴 **صفقة بيع جديدة**\n"
                            msg += f"1️⃣ **الربح والخسارة الناتجة:** {pnl}$ ({pnl_pct}%)\n"
                            msg += f"2️⃣ **سبب الإغلاق:** صعود مؤشر الـ RSI إلى {rsi} (منطقة ذروة الشراء وبدء جني الأرباح).\n"
                            msg += f"3️⃣ **اسم العملة:** {clean_symbol}\n"
                            msg += f"📊 إجمالي المحفظة الحالي: ${total_equity}"
                        send_telegram_message(msg)
        except Exception as e:
            print(f"⚠️ خطأ اتصال: {e}")
            await asyncio.sleep(5)

def advanced_report_scheduler():
    ONE_DAY, ONE_WEEK, ONE_MONTH = 86400, 86400 * 7, 86400 * 30
    start_time = time.time()
    last_day = last_week = last_month = start_time
    while True:
        time.sleep(60)
        current_time = time.time()
        if current_time - last_day >= ONE_DAY:
            try: portfolio.generate_harvest_report("اليوم", 1)
            except Exception: pass
            last_day = current_time
        if current_time - last_week >= ONE_WEEK:
            try: portfolio.generate_harvest_report("الأسبوع", 7)
            except Exception: pass
            last_week = current_time
        if current_time - last_month >= ONE_MONTH:
            try: portfolio.generate_harvest_report("الشهر", 30)
            except Exception: pass
            last_month = current_time

def start_trading_loop():
    asyncio.run(start_live_shadow_engine())

if __name__ == "__main__":
    threading.Thread(target=start_trading_loop, daemon=True).start()
    threading.Thread(target=advanced_report_scheduler, daemon=True).start()
    run_flask()
