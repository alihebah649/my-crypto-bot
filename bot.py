import os
import time
import threading
import json
import urllib.request
import urllib.parse
import urllib.error
import concurrent.futures  
from datetime import datetime
from flask import Flask, jsonify

app = Flask(__name__)

# --- المتغيرات البيئية ---
BINANCE_API_KEY = os.environ.get('BINANCE_API_KEY')
BINANCE_SECRET_KEY = os.environ.get('BINANCE_SECRET_KEY')
TOKEN = os.environ.get('TOKEN', 'YOUR_TELEGRAM_TOKEN_HERE')
CHAT_ID = os.environ.get('CHAT_ID', '199325566')
BIN_ID = os.environ.get('BIN_ID')
JSONBIN_KEY = os.environ.get('JSONBIN_API_KEY') or os.environ.get('JSONBIN_KEY')

global_data = {}
DATA_FILE = "data.json"
data_lock = threading.Lock()

# --- إعدادات إدارة المخاطر الاستراتيجية المحدثة (إصدار 2.0) ---
RISK_CONFIG = {
    'entry_amount_usd': 50.0,
    'stop_loss': 0.012,            
    'early_protect': 0.015,        
    'trailing_activation': 0.026,  
    'trailing_stop': 0.004,        
    'initial_capital': 1000.0,
    'max_open_trades': 999,        
    'cooldown_hours': 2,           
    'btc_crash_threshold': -0.03,  
    'binance_fee_rate': 0.001,
    'top_coins': ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'LINKUSDT', 'ADAUSDT'], # العملات المؤهلة لوضع التعافي
    'max_recovery_percent': 0.4    # سقف تجميد رأس المال في وضع التعافي (40%)
}

# --- دوال المؤشرات ---
def calculate_ema(prices, period=100):
    if len(prices) < period:
        return sum(prices) / len(prices) if prices else 0
    ema = sum(prices[:period]) / period
    multiplier = 2 / (period + 1)
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def calculate_atr(ohlc_data, period=14):
    if len(ohlc_data) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(ohlc_data)):
        h = ohlc_data[i]['high']
        l = ohlc_data[i]['low']
        pc = ohlc_data[i-1]['close']
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs[-period:]) / period

def get_klines_ohlc(symbol, interval, limit=150): 
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as f:
            data = json.loads(f.read().decode())
            return [{
                'open': float(candle[1]),
                'high': float(candle[2]),
                'low': float(candle[3]),
                'close': float(candle[4]),
                'volume': float(candle[5]) # تم إضافة فلتر السيولة
            } for candle in data]
    except Exception as e:
        print(f"⚠️ Binance K-lines API Error for {symbol} ({interval}): {e}", flush=True)
        return []

def analyze_candlestick_patterns(ohlc_data):
    if len(ohlc_data) < 5:
        return "NEUTRAL", "بيانات غير كافية"

    c1 = ohlc_data[-1]  
    c2 = ohlc_data[-2]  
    c3 = ohlc_data[-3]  

    body1 = abs(c1['close'] - c1['open'])
    body2 = abs(c2['close'] - c2['open'])
    body3 = abs(c3['close'] - c3['open'])

    is_c1_bullish = c1['close'] > c1['open']
    is_c1_bearish = c1['close'] < c1['open']
    is_c2_bullish = c2['close'] > c2['open']
    is_c2_bearish = c2['close'] < c2['open']
    is_c3_bearish = c3['close'] < c3['open']

    lower_shadow1 = min(c1['close'], c1['open']) - c1['low']
    upper_shadow1 = c1['high'] - max(c1['close'], c1['open'])

    if is_c3_bearish and is_c2_bullish and c2['close'] >= c3['open'] and c2['open'] <= c3['close'] and body2 > body3:
        if is_c1_bullish and c1['close'] > c2['close']:
            return "BULLISH", "🛡️ نمط الثلاثي الخارجي الصاعد"
    if is_c3_bearish and body2 < (body3 * 0.3) and is_c1_bullish and c1['close'] > (c3['open'] + c3['close']) / 2:
        if c2['low'] < c3['low'] and c2['low'] < c1['low']:
            return "BULLISH", "🌌 نمط نجمة الصباح"
    if abs(c1['low'] - c2['low']) / (c1['low'] or 1) < 0.0005:
        if is_c2_bearish and is_c1_bullish:
            return "BULLISH", "⚖️ نمط قاع الملقط"
    if is_c2_bearish and is_c1_bullish and c1['close'] >= c2['open'] and c1['open'] <= c2['close'] and body1 > body2:
        if upper_shadow1 < (body1 * 0.5):  
            return "BULLISH", "🐋 نمط الابتلاع الشرائي"
    if is_c2_bearish and is_c1_bullish:
        if c1['open'] <= c2['close'] and c1['close'] > (c2['open'] + c2['close']) / 2 and c1['close'] < c2['open']:
            return "BULLISH", "🎯 نمط الخط الثاقب"
    if lower_shadow1 >= (2 * body1) and upper_shadow1 < (0.4 * body1) and body1 > 0:
        return "BULLISH", "🔨 شمعة المطرقة الانعكاسية"
    if upper_shadow1 >= (2 * body1) and lower_shadow1 < (0.4 * body1) and body1 > 0:
        if c1['close'] > c2['close']:  
            return "BULLISH", "🏹 شمعة المطرقة المقلوبة"

    return "NEUTRAL", "حركة عرضية طبيعية"

def analyze_bearish_patterns(ohlc_data):
    if len(ohlc_data) < 4:
        return "NEUTRAL", ""

    c1 = ohlc_data[-1]  
    c2 = ohlc_data[-2]  
    c3 = ohlc_data[-3]  

    body1 = abs(c1['close'] - c1['open'])
    body2 = abs(c2['close'] - c2['open'])
    body3 = abs(c3['close'] - c3['open'])

    is_c1_bearish = c1['close'] < c1['open']
    is_c2_bullish = c2['close'] > c2['open']
    is_c3_bullish = c3['close'] > c3['open']

    upper_shadow1 = c1['high'] - max(c1['close'], c1['open'])
    lower_shadow1 = min(c1['close'], c1['open']) - c1['low']

    if is_c2_bullish and is_c1_bearish and c1['close'] <= c2['open'] and c1['open'] >= c2['close'] and body1 > body2:
        return "BEARISH", "🐋 نمط الابتلاع البيعي"
    if upper_shadow1 >= (2 * body1) and lower_shadow1 < (0.4 * body1) and body1 > 0:
        return "BEARISH", "💫 شمعة الشهاب الهابطة"
    if abs(c1['high'] - c2['high']) / (c1['high'] or 1) < 0.0005:
        if is_c2_bullish and is_c1_bearish:
            return "BEARISH", "⚖️ قمة الملقط الهابطة"
    if is_c3_bullish and body2 < (body3 * 0.3) and is_c1_bearish and c1['close'] < (c3['open'] + c3['close']) / 2:
        return "BEARISH", "🌆 نمط نجمة المساء"

    return "NEUTRAL", ""

def build_telegram_table(stats_dict, title, period_label, period_value):
    coins = stats_dict.get("coins", {})
    if not coins:
        return f"📊 *{title}*\n📅 {period_label}: `{period_value}`\n\n🚫 لا توجد صفقات مسجلة في هذه الفترة بعد."
    table = f"📊 *{title}*\n📅 {period_label}: `{period_value}`\n\n```\n"
    table += f"{'COIN':<8} | {'WIN':<3} | {'LOSS':<4} | {'NET (FEES)':<10}\n---------------------------------\n"
    total_w, total_l, total_p = 0, 0, 0.0
    for c, s in coins.items():
        w, l, p = s.get("wins", 0), s.get("losses", 0), s.get("net_profit", 0.0)
        total_w += w; total_l += l; total_p += p
        table += f"{c:<8} | {w:<3} | {l:<4} | {p:+.2f}$\n"
    table += f"---------------------------------\n{'TOTAL':<8} | {total_w:<3} | {total_l:<4} | {total_p:+.2f}$\n```"
    return table

@app.route('/')
def home():
    with data_lock:
        stats = global_data.get("global_stats", {})
        total_trades = stats.get('wins', 0) + stats.get('losses', 0)
        win_rate = (stats.get('wins', 0) / total_trades * 100) if total_trades > 0 else 0
        current_capital = RISK_CONFIG['initial_capital'] + stats.get('net_profit', 0.0)
        open_trades = [k.upper() for k, v in global_data.items() if isinstance(v, dict) and v.get("is_holding", False)]
        recovery_trades = [k.upper() for k, v in global_data.items() if isinstance(v, dict) and v.get("is_recovering", False)]
        return jsonify({
            "status": "🚀 Halal Trading Bot (V2.0) Running",
            "account_summary": {"initial_capital": f"${RISK_CONFIG['initial_capital']:.2f}", "current_capital": f"${current_capital:.2f}", "net_profit": f"${stats.get('net_profit', 0.0):.2f}"},
            "protection_status": {"active_positions": open_trades, "recovery_mode_positions": recovery_trades},
            "performance": {"total_trades": total_trades, "win_rate": f"{win_rate:.1f}%"},
            "strategy": "Macro Support + Micro Execution + Volume Filter + Recovery Mode",
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }), 200

@app.route('/reset-my-stats')
def reset_my_stats():
    global global_data
    with data_lock:
        global_data["global_stats"] = {"wins": 0, "losses": 0, "net_profit": 0.0}
        global_data["monthly_stats"] = {"month": datetime.now().strftime("%Y-%m"), "coins": {}}
        global_data["weekly_stats"] = {"week": datetime.now().strftime("%Y-W%W"), "coins": {}}
        global_data["daily_stats"] = {"date": datetime.now().strftime("%Y-%m-%d"), "coins": {}}
        for key in list(global_data.keys()):
            if key not in ["global_stats", "monthly_stats", "weekly_stats", "daily_stats"] and isinstance(global_data[key], dict):
                global_data[key].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0, 'last_stop_loss_time': 0.0, 'atr_stop_loss': 0.0, 'is_recovering': False})
        save_global_data()
    return "⚡ Done! All stats reset successfully.", 200

def load_global_data():
    global global_data
    if BIN_ID and JSONBIN_KEY:
        try:
            url = f"https://api.jsonbin.io/v3/b/{BIN_ID}/latest"
            req = urllib.request.Request(url, headers={"X-Master-Key": JSONBIN_KEY})
            with urllib.request.urlopen(req, timeout=15) as r:
                global_data = json.loads(r.read().decode()).get('record', {})
                print("✅ Data loaded from JSONBin cloud!", flush=True)
                return
        except Exception as e: print(f"⚠️ JSONBin load failed ({e}).", flush=True)
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f: global_data = json.load(f)
        except Exception: global_data = {}

def save_global_data():
    try:
        temp_file = DATA_FILE + ".tmp"
        with open(temp_file, 'w') as f:
            json.dump(global_data, f, indent=2)
        os.replace(temp_file, DATA_FILE)
    except Exception as e:
        print(f"⚠️ Error saving data locally: {e}", flush=True)
        
    if BIN_ID and JSONBIN_KEY:
        try:
            url = f"https://api.jsonbin.io/v3/b/{BIN_ID}"
            req = urllib.request.Request(url, data=json.dumps(global_data).encode('utf-8'), headers={"X-Master-Key": JSONBIN_KEY, "Content-Type": "application/json"}, method="PUT")
            urllib.request.urlopen(req, timeout=15)
        except: pass

def update_all_stats(cid, net_diff):
    cid_upper = cid.upper()
    is_win = net_diff > 0
    if is_win: global_data["global_stats"]["wins"] += 1
    else: global_data["global_stats"]["losses"] += 1
    global_data["global_stats"]["net_profit"] += net_diff
    for report_type in ["daily_stats", "weekly_stats", "monthly_stats"]:
        if "coins" not in global_data[report_type]: global_data[report_type]["coins"] = {}
        if cid_upper not in global_data[report_type]["coins"]: global_data[report_type]["coins"][cid_upper] = {"wins": 0, "losses": 0, "net_profit": 0.0}
        if is_win: global_data[report_type]["coins"][cid_upper]["wins"] += 1
        else: global_data[report_type]["coins"][cid_upper]["losses"] += 1
        global_data[report_type]["coins"][cid_upper]["net_profit"] += net_diff

def run_trading_bot():
    global global_data
    time.sleep(15)
    print(">>> ADVANCED V2.0 BOT LOOP STARTED <<<", flush=True)
    
    coin_mapping = {
        "BTCUSDT": "bitcoin", "ETHUSDT": "ethereum", "SOLUSDT": "solana",
        "LINKUSDT": "chainlink", "ADAUSDT": "cardano", "DOTUSDT": "polkadot",
        "NEARUSDT": "near", "ARBUSDT": "arbitrum", "OPUSDT": "optimism",
        "RENDERUSDT": "render", "BNBUSDT": "binancecoin", "AVAXUSDT": "avalanche", 
        "ALGOUSDT": "algorand", "ATOMUSDT": "cosmos", "FETUSDT": "fetch-ai", 
        "LTCUSDT": "litecoin"       
    }

    def send_telegram(text):
        if not TOKEN or TOKEN == 'YOUR_TELEGRAM_TOKEN_HERE': return
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            data = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
        except: pass

    with data_lock:
        if "global_stats" not in global_data: global_data["global_stats"] = {"wins": 0, "losses": 0, "net_profit": 0.0}
        if "monthly_stats" not in global_data: global_data["monthly_stats"] = {"month": datetime.now().strftime("%Y-%m"), "coins": {}}
        if "weekly_stats" not in global_data: global_data["weekly_stats"] = {"week": datetime.now().strftime("%Y-W%W"), "coins": {}}
        if "daily_stats" not in global_data: global_data["daily_stats"] = {"date": datetime.now().strftime("%Y-%m-%d"), "coins": {}}
        save_global_data()

    send_telegram("🔥 *تم تفعيل الإصدار 2.0 بنجاح!* 🌌\n1. نظام التعافي للعملات الكبرى مفعل.\n2. فلتر السيولة وشمعة التأكيد يعملان.\n3. محرك النقاط المطور جاهز للقنص.")

    is_first_loop = True  
    btc_alert_sent = False
    
    while True:
        try:
            current_date, current_week, current_month = datetime.now().strftime("%Y-%m-%d"), datetime.now().strftime("%Y-W%W"), datetime.now().strftime("%Y-%m")
            save_needed = False
            
            with data_lock:
                if global_data["daily_stats"].get("date") != current_date:
                    send_telegram(build_telegram_table(global_data["daily_stats"], "حصاد اليوم الشامل", "التاريخ المنتهي", global_data["daily_stats"].get("date")))
                    global_data["daily_stats"] = {"date": current_date, "coins": {}}
                    save_needed = True
                if global_data["weekly_stats"].get("week") != current_week:
                    send_telegram(build_telegram_table(global_data["weekly_stats"], "التقرير الأسبوعي الشامل", "الأسبوع المنتهي", global_data["weekly_stats"].get("week")))
                    global_data["weekly_stats"] = {"week": current_week, "coins": {}}
                    save_needed = True
                if global_data["monthly_stats"].get("month") != current_month:
                    send_telegram(build_telegram_table(global_data["monthly_stats"], "التقرير الشهري الشامل", "الشهر المنتهي", global_data["monthly_stats"].get("month")))
                    global_data["monthly_stats"] = {"month": current_month, "coins": {}}
                    save_needed = True
                if save_needed:
                    save_global_data()

            try:
                url = "https://api.binance.com/api/v3/ticker/price"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=15) as f: ticker_data = json.loads(f.read().decode())
                market_prices = {item['symbol']: float(item['price']) for item in ticker_data if item['symbol'] in coin_mapping}
            except Exception:
                time.sleep(30); continue
            
            current_time_seconds = time.time()
            btc_is_crashing = False
            
            btc_klines = get_klines_ohlc("BTCUSDT", "1h", 3)
            if len(btc_klines) >= 3:
                highest_recent = max([c['close'] for c in btc_klines])
                current_btc = btc_klines[-1]['close']
                drop_percent = (current_btc - highest_recent) / highest_recent
                if drop_percent <= RISK_CONFIG['btc_crash_threshold']:
                    btc_is_crashing = True
                    if not btc_alert_sent:
                        send_telegram(f"🚨 *حارس البيتكوين:* هبوط حاد بنسبة `{drop_percent*100:.2f}%`. تجميد الشراء الجديد.")
                        btc_alert_sent = True
                else:
                    if btc_alert_sent and drop_percent > -0.02: btc_alert_sent = False

            held_symbols = []
            monitoring_symbols = []
            
            with data_lock:
                current_open_trades = sum(1 for c_key in coin_mapping.values() if global_data.get(c_key, {}).get("is_holding", False))
                for symbol, cid in coin_mapping.items():
                    is_holding = global_data.get(cid, {}).get("is_holding", False)
                    last_cooldown = global_data.get(cid, {}).get("last_stop_loss_time", 0.0)
                    if is_holding:
                        held_symbols.append(symbol)
                    elif current_time_seconds - last_cooldown >= RISK_CONFIG['cooldown_hours'] * 3600:
                        if current_open_trades < RISK_CONFIG['max_open_trades']:
                            monitoring_symbols.append(symbol)

            fetched_exit_klines_5m = {}
            fetched_entry_klines_15m = {}
            fetched_entry_klines_5m = {} 
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                future_exits = {executor.submit(get_klines_ohlc, sym, '5m', 15): sym for sym in held_symbols}
                future_entries_15m = {executor.submit(get_klines_ohlc, sym, '15m', 150): sym for sym in monitoring_symbols}
                
                for future in concurrent.futures.as_completed(future_exits):
                    fetched_exit_klines_5m[future_exits[future]] = future.result()
                for future in concurrent.futures.as_completed(future_entries_15m):
                    fetched_entry_klines_15m[future_entries_15m[future]] = future.result()

            potential_entries = []
            scores_15m = {} 
            
            for sym, klines_15m in fetched_entry_klines_15m.items():
                if len(klines_15m) < 100: continue
                close_prices = [c['close'] for c in klines_15m]
                
                ema_100 = calculate_ema(close_prices, 100)
                atr = calculate_atr(klines_15m, 14)
                
                close_prices_20 = close_prices[-20:]
                sma_15m = sum(close_prices_20) / 20
                variance_15m = sum((x - sma_15m)**2 for x in close_prices_20) / 20
                std_15m = variance_15m ** 0.5 if variance_15m > 0 else 0.001
                lower_band_15m = sma_15m - std_15m
                
                volumes = [c['volume'] for c in klines_15m]
                avg_vol = sum(volumes[-20:]) / 20 if len(volumes) >= 20 else 1
                
                current_price = market_prices.get(sym, 0)
                score = 0
                reasons = []
                
                if current_price > ema_100:
                    score += 2
                    reasons.append("فوق EMA100")
                
                if current_price <= lower_band_15m:
                    score += 3
                    reasons.append("قاع بولنجر")
                    
                if klines_15m[-1]['volume'] > (avg_vol * 1.2):
                    score += 2
                    reasons.append("سيولة قوية (+2)")
                
                if score >= 2:
                    potential_entries.append(sym)
                    scores_15m[sym] = {'score': score, 'reasons': reasons, 'atr': atr}
                    
            if potential_entries and not btc_is_crashing:
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(potential_entries)) as executor:
                    future_entries_5m = {executor.submit(get_klines_ohlc, sym, '5m', 15): sym for sym in potential_entries}
                    for future in concurrent.futures.as_completed(future_entries_5m):
                        fetched_entry_klines_5m[future_entries_5m[future]] = future.result()


            save_needed = False
            with data_lock:
                for symbol, price in market_prices.items():
                    cid = coin_mapping[symbol]
                    if cid not in global_data: global_data[cid] = {}
                    for key in ["held", "buy_price", "is_holding", "trailing_active", "highest_price", "last_stop_loss_time", "atr_stop_loss", "is_recovering"]:
                        if key not in global_data[cid]: global_data[cid][key] = 0.0 if key not in ["is_holding", "trailing_active", "is_recovering"] else False

                    if global_data[cid]["is_holding"]:
                        buy_price = global_data[cid]['buy_price']
                        if buy_price == 0: continue
                        
                        current_return = (price - buy_price) / buy_price
                        
                        fixed_stop_price = buy_price * (1 - RISK_CONFIG['stop_loss'])
                        dynamic_atr_stop = global_data[cid].get('atr_stop_loss', 0.0)
                        stop_loss_price = max(fixed_stop_price, dynamic_atr_stop) if dynamic_atr_stop > 0 else fixed_stop_price

                        klines_5m_raw = fetched_exit_klines_5m.get(symbol, [])
                        closed_klines_exit = klines_5m_raw[:-1] if len(klines_5m_raw) > 1 else []
                        bearish_signal, bearish_pattern_name = analyze_bearish_patterns(closed_klines_exit)
                        
                        if global_data[cid].get("is_recovering"):
                            if current_time_seconds - global_data[cid].get("recovery_start_time", current_time_seconds) > 7 * 86400:
                                if current_time_seconds - global_data[cid].get("last_recovery_alert", 0) > 86400:
                                    send_telegram(f"⏳ *تنبيه تعافي:* {cid.upper()} مجمدة في وضع التعافي منذ أكثر من أسبوع.\n📉 الخسارة الحالية: `{current_return*100:.2f}%`\nيرجى المراجعة واتخاذ قرار يدوياً.")
                                    global_data[cid]["last_recovery_alert"] = current_time_seconds
                                    save_needed = True
                            if current_return >= 0:
                                global_data[cid]["is_recovering"] = False
                                send_telegram(f"🎉 *نجاح التعافي:* {cid.upper()} عادت لنقطة الدخول وتم إلغاء وضع التعافي للمراقبة الطبيعية.")
                                save_needed = True
                            continue 

                        if not global_data[cid]["trailing_active"] and current_return >= RISK_CONFIG['early_protect'] and current_return < RISK_CONFIG['trailing_activation']:
                            if bearish_signal == "BEARISH":
                                net_profit = ((price - buy_price) * global_data[cid]['held']) - ((buy_price + price) * global_data[cid]['held'] * RISK_CONFIG['binance_fee_rate'])
                                update_all_stats(cid, net_profit)
                                send_telegram(f"⚠️ *خروج مبكر ذكي لحماية الأرباح:* {cid.upper()}\n🎯 السبب: رصد `{bearish_pattern_name}` قبل تراجع السعر.\n💰 الصافي المحمي: `{net_profit:+.2f}$`")
                                global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0, 'is_recovering': False})
                                save_needed = True; continue

                        activation_price = buy_price * (1 + RISK_CONFIG['trailing_activation'])
                        if not global_data[cid]["trailing_active"] and price >= activation_price:
                            global_data[cid]["trailing_active"] = True
                            global_data[cid]["highest_price"] = max(price, global_data[cid].get("highest_price", price))
                            if not is_first_loop:
                                send_telegram(f"🔥 *{cid.upper()}* - دخلت منطقة التتبع الذكي الرابح! السعر الحالي: `{price}$`")
                            save_needed = True

                        if global_data[cid]["trailing_active"]:
                            if price > global_data[cid]["highest_price"]:
                                global_data[cid]["highest_price"] = price; save_needed = True
                            
                            trailing_stop_price = global_data[cid]["highest_price"] * (1 - RISK_CONFIG['trailing_stop'])
                            hard_backup_stop = global_data[cid]["highest_price"] * (1 - 0.009) 

                            if (price <= trailing_stop_price and bearish_signal == "BEARISH") or (price <= hard_backup_stop):
                                net_profit = ((price - buy_price) * global_data[cid]['held']) - ((buy_price + price) * global_data[cid]['held'] * RISK_CONFIG['binance_fee_rate'])
                                update_all_stats(cid, net_profit)
                                reason = bearish_pattern_name if price > hard_backup_stop else "كسر صمام الأمان التتبعي"
                                send_telegram(f"🚀 *بيع تتبعي مطور ناجح:* {cid.upper()}\n🛡️ خروج بناءً على: `{reason}`\n💰 الأرباح المقتنصة: `{net_profit:+.2f}$`")
                                global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0, 'is_recovering': False})
                                save_needed = True; continue

                        if price <= stop_loss_price and not global_data[cid]["trailing_active"]:
                            if is_first_loop:
                                global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'is_recovering': False})
                                save_needed = True; continue
                            
                            if symbol in RISK_CONFIG['top_coins']:
                                global_data[cid]["is_recovering"] = True
                                global_data[cid]["recovery_start_time"] = current_time_seconds
                                send_telegram(f"🛡️ *حماية المحفظة (وضع التعافي):* {cid.upper()} انخفضت للحد. بدلاً من البيع بخسارة، تم تجميدها للتعافي.")
                                save_needed = True; continue
                                
                            net_loss = ((price - buy_price) * global_data[cid]['held']) - ((buy_price + price) * global_data[cid]['held'] * RISK_CONFIG['binance_fee_rate'])
                            update_all_stats(cid, net_loss)
                            global_data[cid]["last_stop_loss_time"] = current_time_seconds
                            send_telegram(f"🛑 *{cid.upper()} - وقف خسارة قياسي*\n📉 الخسارة: `{net_loss:.2f}$`\n⏳ عزل العملة لمدّة {RISK_CONFIG['cooldown_hours']} ساعتين.")
                            global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0, 'is_recovering': False})
                            save_needed = True

                    else:
                        if current_open_trades >= RISK_CONFIG['max_open_trades']: continue
                        if current_time_seconds - global_data[cid].get("last_stop_loss_time", 0.0) < RISK_CONFIG['cooldown_hours'] * 3600: continue
                        if btc_is_crashing: continue
                        
                        recovery_count = sum(1 for v in global_data.values() if isinstance(v, dict) and v.get("is_recovering"))
                        max_allowed_recovery = int(len(coin_mapping) * RISK_CONFIG['max_recovery_percent'])
                        if recovery_count >= max_allowed_recovery:
                            continue 

                        if symbol in fetched_entry_klines_5m:
                            klines_5m_raw = fetched_entry_klines_5m[symbol]
                            closed_klines_entry = klines_5m_raw[:-1] if len(klines_5m_raw) > 1 else []
                            
                            if len(closed_klines_entry) >= 2:
                                pattern_signal, pattern_name = analyze_candlestick_patterns(closed_klines_entry[:-1])
                                if pattern_signal == "BULLISH":
                                    if closed_klines_entry[-1]['close'] > closed_klines_entry[-2]['high']:
                                        pattern_name += " (بشمعة تأكيد)"
                                    else:
                                        pattern_signal = "NEUTRAL"
                            else:
                                pattern_signal, pattern_name = "NEUTRAL", ""

                            sym_data = scores_15m.get(symbol, {'score': 0, 'reasons': [], 'atr': 0.0})
                            total_score = sym_data['score']
                            reasons = sym_data['reasons'].copy()

                            if pattern_signal == "BULLISH":
                                total_score += 5
                                reasons.append(pattern_name)

                            if total_score >= 8:
                                position_size = RISK_CONFIG['entry_amount_usd'] / price
                                atr_stop = price - (2 * sym_data['atr']) 
                                
                                global_data[cid].update({
                                    'held': position_size, 
                                    'buy_price': price, 
                                    'is_holding': True, 
                                    'trailing_active': False, 
                                    'highest_price': price,
                                    'atr_stop_loss': atr_stop,
                                    'is_recovering': False
                                })
                                
                                reasons_str = " | ".join(reasons)
                                send_telegram(f"🎯 *قنص بالنقاط (Score: {total_score}/10):* {cid.upper()}\n✨ المحفزات: `{reasons_str}`\n💵 سعر الدخول: `{price}$`")
                                current_open_trades += 1; save_needed = True

                if save_needed:
                    save_global_data()
                    
            is_first_loop = False; time.sleep(30)
        except Exception as e:
            print(f"⚠️ Error in Loop: {str(e)}", flush=True); time.sleep(30)

if __name__ == "__main__":
    with data_lock: load_global_data()
    threading.Thread(target=run_trading_bot, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False, use_reloader=False)
