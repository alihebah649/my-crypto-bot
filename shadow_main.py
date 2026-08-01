import asyncio
import json
import os
import csv
import threading
import pandas as pd
import numpy as np
from datetime import datetime, timezone
import websockets
import requests
from flask import Flask
import time

# ==========================================
# 1. QUANT ENGINES (V2.2.1 FIXED RISK)
# ==========================================

class DynamicRiskEngine:
    def __init__(self, risk_per_trade_pct=0.01, max_exposure_pct=0.25):
        self.risk_per_trade_pct = risk_per_trade_pct # 1% مخاطرة فعلية من رأس المال
        self.max_exposure_pct = max_exposure_pct

    def calculate_position_size(self, current_equity, entry_price, atr, stop_loss_multiplier=2.0, remaining_exposure=0, cash_available=0):
        if pd.isna(atr) or atr <= 0: 
            # قيد أمان صارم: إذا كان ال ATR غير متوفر، لا تستخدم كامل الرصيد، بل استخدم نسبة ثابتة آمنة (مثلاً 5% من الكاش) كحد أدنى أو ارفض
            return min(current_equity * 0.05, cash_available)
        
        # 1. حساب الحجم بناءً على مخاطرة الـ ATR
        risk_amount = current_equity * self.risk_per_trade_pct
        risk_per_share = atr * stop_loss_multiplier
        ideal_shares = risk_amount / risk_per_share
        ideal_position_usd = ideal_shares * entry_price
        
        # 2. قيود صارمة جداً لمنع دخول كامل الرصيد بأي شكل من الأشكال:
        # ألا يتجاوز حجم الصفقة الحد الأقصى المسموح للمخاطرة (مثلاً 5% من إجمالي المحفظة كقيمة أسمية للصفقة الواحدة لضمان التنوع)
        max_notional_per_trade = current_equity * 0.05 
        
        actual_position_usd = min(ideal_position_usd, max_notional_per_trade, remaining_exposure, cash_available)
        
        return max(actual_position_usd, 0.0)

class GlobalPortfolioTracker:
    def __init__(self, initial_balance=10000.0, analytics_dir="analytics"):
        self.initial_balance = initial_balance
        self.cash = initial_balance
        self.positions = {}
        self.analytics_dir = analytics_dir
        os.makedirs(self.analytics_dir, exist_ok=True)
        self.trade_history = []

    def get_current_equity(self, current_prices):
        equity = self.cash
        for sym, pos in self.positions.items():
            equity += pos["crypto_held"] * current_prices.get(sym, pos["entry_price"])
        return equity

    def get_current_exposure(self, current_prices):
        exposure = 0.0
        for sym, pos in self.positions.items():
            exposure += pos["crypto_held"] * current_prices.get(sym, pos["entry_price"])
        return exposure

    def execute_buy(self, symbol, executed_price, position_size_usd, atr):
        if position_size_usd > self.cash or position_size_usd <= 0:
            return False
            
        crypto_amount = position_size_usd / executed_price
        self.cash -= position_size_usd
        
        self.positions[symbol] = {
            "crypto_held": crypto_amount,
            "entry_price": executed_price,
            "highest_price": executed_price,
            "atr_at_entry": atr,
            "hard_stop": executed_price - (atr * 2.0),
            "trailing_stop": executed_price - (atr * 2.5)
        }
        return True

    def execute_sell(self, symbol, executed_price, exit_reason="SIGNAL"):
        if symbol not in self.positions: return False, 0, 0
        
        pos = self.positions.pop(symbol)
        revenue = pos["crypto_held"] * executed_price
        invested = pos["crypto_held"] * pos["entry_price"]
        pnl = revenue - invested
        pnl_pct = (pnl / invested) * 100
        
        self.cash += revenue
        return True, round(pnl, 2), round(pnl_pct, 2)

    def update_trailing_stops(self, symbol, current_price):
        if symbol in self.positions:
            pos = self.positions[symbol]
            if current_price > pos["highest_price"]:
                pos["highest_price"] = current_price
                new_trail = current_price - (pos["atr_at_entry"] * 2.5)
                if new_trail > pos["trailing_stop"]:
                    pos["trailing_stop"] = new_trail

    def check_exits(self, symbol, current_price):
        if symbol not in self.positions: return None
        pos = self.positions[symbol]
        if current_price <= pos["hard_stop"]: return "HARD_STOP"
        if current_price <= pos["trailing_stop"]: return "TRAILING_STOP"
        return None

# ==========================================
# 2. MARKET DATA & INDICATORS ENGINE
# ==========================================

class OHLCVResampler:
    def __init__(self, timeframe_seconds=60):
        self.tf = timeframe_seconds
        self.current_candles = {}
        self.history = {}

    def process_tick(self, symbol, price, volume, timestamp):
        minute_ts = int(timestamp // self.tf) * self.tf
        if symbol not in self.history: self.history[symbol] = []
            
        if symbol not in self.current_candles or self.current_candles[symbol]['ts'] != minute_ts:
            if symbol in self.current_candles:
                self.history[symbol].append(self.current_candles[symbol])
                if len(self.history[symbol]) > 200: self.history[symbol].pop(0)
            
            self.current_candles[symbol] = {
                'ts': minute_ts, 'open': price, 'high': price, 'low': price, 'close': price, 'volume': volume
            }
        else:
            c = self.current_candles[symbol]
            c['high'] = max(c['high'], price)
            c['low'] = min(c['low'], price)
            c['close'] = price
            c['volume'] += volume

    def get_dataframe(self, symbol):
        if symbol not in self.history or len(self.history[symbol]) < 2:
            return pd.DataFrame()
        return pd.DataFrame(self.history[symbol])

class QuantIndicators:
    @staticmethod
    def calculate_all(df, rsi_period=14, ema_period=100, atr_period=14):
        if len(df) < max(rsi_period, ema_period, atr_period) + 1:
            return None, None, None

        df['ema100'] = df['close'].ewm(span=ema_period, adjust=False).mean()

        delta = df['close'].diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        ema_up = up.ewm(alpha=1/rsi_period, adjust=False).mean()
        ema_down = down.ewm(alpha=1/rsi_period, adjust=False).mean()
        rs = ema_up / ema_down
        df['rsi'] = 100 - (100 / (1 + rs))

        df['prev_close'] = df['close'].shift(1)
        df['tr1'] = df['high'] - df['low']
        df['tr2'] = (df['high'] - df['prev_close']).abs()
        df['tr3'] = (df['low'] - df['prev_close']).abs()
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        df['atr'] = df['tr'].ewm(alpha=1/atr_period, adjust=False).mean()

        last_row = df.iloc[-1]
        return last_row['ema100'], last_row['rsi'], last_row['atr']

class ScoreEngine:
    @staticmethod
    def evaluate(current_price, ema100, rsi):
        if pd.isna(ema100) or pd.isna(rsi): return "HOLD"
        score = 0
        if current_price > ema100: score += 50
        if rsi < 40: score += 30
        if rsi > 70: score -= 50
        
        if score >= 80: return "BUY"
        if score <= -50: return "SELL"
        return "HOLD"

# ==========================================
# 3. INFRASTRUCTURE & FLASK
# ==========================================

app = Flask(__name__)
@app.route('/')
def home(): return {"status": "healthy v2.2.1"}, 200

def run_flask(): app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "199325566")

def send_telegram_message(message: str):
    if not TELEGRAM_TOKEN: return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=5)
    except: pass

# ==========================================
# 4. LIVE TRADING LOOP
# ==========================================

ISLAMIC_ASSETS = ["BTC-USD", "ETH-USD", "BNB-USD", "SOL-USD", "AVAX-USD", "LINK-USD", "MATIC-USD"]

portfolio = GlobalPortfolioTracker(initial_balance=10000.0)
resampler = OHLCVResampler(timeframe_seconds=60)
risk_engine = DynamicRiskEngine(risk_per_trade_pct=0.01, max_exposure_pct=0.25)
current_prices = {}

async def start_live_shadow_engine():
    send_telegram_message("🤖 بوت V2.2.1 يعمل: تم فرض قيود صارمة على حجم الصفقات ومنع دخول كامل الرصيد.")
    
    while True:
        try:
            async with websockets.connect("wss://ws-feed.exchange.coinbase.com", ping_interval=20) as ws:
                await ws.send(json.dumps({"type": "subscribe", "product_ids": ISLAMIC_ASSETS, "channels": ["ticker"]}))
                
                while True:
                    response = await ws.recv()
                    data = json.loads(response)
                    if data.get("type") != "ticker": continue
                    
                    symbol = data.get("product_id")
                    if symbol not in ISLAMIC_ASSETS: continue
                    
                    price = float(data['price'])
                    current_prices[symbol] = price
                    timestamp = time.time()
                    
                    resampler.process_tick(symbol, price, float(data.get('last_size', 0)), timestamp)
                    
                    portfolio.update_trailing_stops(symbol, price)
                    exit_reason = portfolio.check_exits(symbol, price)
                    
                    if exit_reason:
                        success, pnl, pct = portfolio.execute_sell(symbol, price, exit_reason)
                        if success:
                            eq = portfolio.get_current_equity(current_prices)
                            send_telegram_message(f"🔴 إغلاق آلي ({exit_reason})\nالعملة: {symbol}\nالربح/خسارة: {pct}%\nالرصيد: ${eq:.2f}")
                        continue

                    df = resampler.get_dataframe(symbol)
                    if df.empty: continue
                    
                    ema100, rsi, atr = QuantIndicators.calculate_all(df)
                    signal = ScoreEngine.evaluate(price, ema100, rsi)
                    
                    if signal == "SELL" and symbol in portfolio.positions:
                        success, pnl, pct = portfolio.execute_sell(symbol, price, "SIGNAL")
                        if success:
                            eq = portfolio.get_current_equity(current_prices)
                            send_telegram_message(f"🔴 بيع استراتيجي\nالعملة: {symbol}\nالربح: {pct}%\nالرصيد: ${eq:.2f}")
                            
                    elif signal == "BUY" and symbol not in portfolio.positions:
                        current_equity = portfolio.get_current_equity(current_prices)
                        current_exposure = portfolio.get_current_exposure(current_prices)
                        max_allowed_exposure = current_equity * risk_engine.max_exposure_pct
                        remaining_exp = max_allowed_exposure - current_exposure
                        
                        if remaining_exp <= 50: continue
                        
                        # حساب حجم الدخول الآمن مع تمرير السيولة المتاحة (Cash)
                        size_usd = risk_engine.calculate_position_size(
                            current_equity=current_equity, 
                            entry_price=price, 
                            atr=atr, 
                            remaining_exposure=remaining_exp,
                            cash_available=portfolio.cash
                        )
                        
                        if size_usd >= 10: # الحد الأدنى المسموح للصفقة
                            if portfolio.execute_buy(symbol, price, size_usd, atr):
                                eq = portfolio.get_current_equity(current_prices)
                                clean_name = symbol.split("-")[0]
                                send_telegram_message(
                                    f"=== صفقة شراء جديدة V2.2.1 ===\n"
                                    f"العملة: {clean_name}\n"
                                    f"المبلغ المستخدم: ${size_usd:.2f}\n"
                                    f"سعر الدخول: ${price:.2f}\n"
                                    f"الرصيد الكلي: ${eq:.2f}\n"
                                    f"RSI: {rsi:.1f}"
                                )
                                
        except Exception as e:
            print(f"WS Error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=lambda: asyncio.run(start_live_shadow_engine()), daemon=True).start()
    run_flask()
