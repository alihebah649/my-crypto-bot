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

# --- إعدادات إدارة المخاطر الاستراتيجية ---
RISK_CONFIG = {
    'entry_amount_usd': 50.0,
    'stop_loss': 0.012,            # وقف خسارة محكم 1.2% لحماية رأس المال
    'trailing_activation': 0.026,  # تفعيل تتبع الأرباح عند 2.6%
    'trailing_stop': 0.004,        # تتبع ذكي بفارق 0.4% لقنص القمم
    'initial_capital': 1000.0,
    'max_open_trades': 5,          
    'cooldown_hours': 2,           # حظر العملة الخاسرة لمدة ساعتين منعاً للعناد مع السوق
    'btc_crash_threshold': -0.03,  # حارس البيتكوين في حال الانهيار بنسبة -3%
    'binance_fee_rate': 0.001      
}

def get_klines_ohlc(symbol, interval, limit=40):
    """جلب بيانات الشموع الكاملة وتشريحها برمجياً (OHLC) حسب الفريم المطلوب"""
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as f:
            data = json.loads(f.read().decode())
            return [{
                'open': float(candle[1]),
                'high': float(candle[2]),
                'low': float(candle[3]),
                'close': float(candle[4])
            } for candle in data]
    except Exception as e:
        print(f"⚠️ Binance K-lines API Error for {symbol} ({interval}): {e}", flush=True)
        return []

def analyze_candlestick_patterns(ohlc_data):
    """محرك السلوك السعري الذكي: تحليل سلاسل الشموع اليابانية الانعكاسية المكتملة"""
    if len(ohlc_data) < 5:
        return "NEUTRAL", "بيانات غير كافية"

    # عزل آخر 3 شموع تم إغلاقها بالكامل في الشارت
    c1 = ohlc_data[-1]  # الشمعة الأخيرة المغلقة حديثاً
    c2 = ohlc_data[-2]  # الشمعة قبل الأخيرة
    c3 = ohlc_data[-3]  # الشمعة الثالثة للخلف

    # حساب الحجم المطلق لأجسام الشموع (الفرق بين الفتح والإغلاق)
    body1 = abs(c1['close'] - c1['open'])
    body2 = abs(c2['close'] - c2['open'])
    body3 = abs(c3['close'] - c3['open'])

    # تحديد اتجاه كل شمعة (خضراء صاعدة أم حمراء هابطة)
    is_c1_bullish = c1['close'] > c1['open']
    is_c1_bearish = c1['close'] < c1['open']
    is_c2_bullish = c2['close'] > c2['open']
    is_c2_bearish = c2['close'] < c2['open']
    is_c3_bearish = c3['close'] < c3['open']

    # --- 1. فحص نمط سلسلة نجمة الصباح (Morning Star) ---
    if is_c3_bearish and body2 < (body3 * 0.3) and is_c1_bullish and c1['close'] > (c3['open'] + c3['close']) / 2:
        if c2['low'] < c3['low'] and c2['low'] < c1['low']:
            return "BULLISH", "🌌 نمط نجمة الصباح (سلسلة انعكاسية ثلاثية)"

    # --- 2. فحص نمط سلسلة قاع الملقط (Tweezer Bottom) ---
    if abs(c1['low'] - c2['low']) / (c1['low'] or 1) < 0.0005:
        if is_c2_bearish and is_c1_bullish:
            return "BULLISH", "⚖️ نمط قاع الملقط (دعم ثنائي حديدي)"

    # --- 3. فحص نمط الابتلاع الشرائي (Bullish Engulfing) ---
    if is_c2_bearish and is_c1_bullish and c1['close'] >= c2['open'] and c1['open'] <= c2['close']:
        if body1 > body2:
            return "BULLISH", "🐋 نمط الابتلاع الشرائي (سيطرة المشترين الحالية)"

    # --- 4. فحص شمعة المطرقة الانفجارية (Hammer) ---
    lower_shadow1 = min(c1['close'], c1['open']) - c1['low']
    upper_shadow1 = c1['high'] - max(c1['close'], c1['open'])
    if lower_shadow1 >= (2 * body1) and upper_shadow1 < (0.4 * body1) and body1 > 0:
        return "BULLISH", "🔨 شمعة المطرقة الانعكاسية (رفض هبوط وضغط شراء فوري)"

    # --- 5. فحص الفلاتر السلبية في القمم للخروج المبكر وحماية الأرباح ---
    is_tweezer_top = abs(c1['high'] - c2['high']) / (c1['high'] or 1) < 0.0005
    is_bearish_engulfing = is_c2_bullish and is_c1_bearish and c1['close'] <= c2['open'] and c1['open'] >= c2['close'] and body1 > body2
    
    if is_tweezer_top or is_bearish_engulfing:
        return "BEARISH", "🚨 إشارة قمة سلبية (ضعف الزخم الشرائي)"

    return "NEUTRAL", "حركة عرضية طبيعية"

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
        return jsonify({
            "status": "🚀 Halal Trading Bot (Multi-Timeframe Strategy) Running",
            "account_summary": {"initial_capital": f"${RISK_CONFIG['initial_capital']:.2f}", "current_capital": f"${current_capital:.2f}", "net_profit": f"${stats.get('net_profit', 0.0):.2f}"},
            "protection_status": {"max_allowed_trades": RISK_CONFIG['max_open_trades'], "currently_open_trades": len(open_trades), "active_positions": open_trades},
            "performance": {"total_trades": total_trades, "win_rate": f"{win_rate:.1f}%"},
            "strategy": "Macro Support (15m Bollinger) -> Micro Execution (5m Candlestick)",
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
                global_data[key].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0, 'last_stop_loss_time': 0.0})
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
        with open(DATA_FILE, 'w') as f: json.dump(global_data, f, indent=2)
    except: pass
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
    print(">>> DUAL-TIMEFRAME PRICE ACTION BOT LOOP STARTED <<<", flush=True)
    
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

    send_telegram("🔥 *تم تفعيل نظام الزناد المزدوج (Dual-Timeframe)!* 🌌\n1. رصد الدعم والقيعان بناءً على فريم *15 دقيقة*.\n2. اقتناص الدخول فور ظهور تأكيد الشموع على فريم *5 دقائق* لضمان أفضل سعر دخول ممكن.")

    is_first_loop = True  
    btc_alert_sent = False
    
    while True:
        try:
            current_date, current_week, current_month = datetime.now().strftime("%Y-%m-%d"), datetime.now().strftime("%Y-W%W"), datetime.now().strftime("%Y-%m")
            save_needed = False

            with data_lock:
                if global_data["monthly_stats"].get("month") != current_month:
                    send_telegram(build_telegram_table(global_data["monthly_stats"], "التقرير الشهري الشامل", "الشهر المنتهي", global_data["monthly_stats"].get("month")))
                    global_data["monthly_stats"] = {"month": current_month, "coins": {}}
                    save_needed = True

            try:
                url = "https://api.binance.com/api/v3/ticker/price"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=15) as f: ticker_data = json.loads(f.read().decode())
                market_prices = {item['symbol']: float(item['price']) for item in ticker_data if item['symbol'] in coin_mapping}
            except Exception:
                time.sleep(30); continue
            
            current_time_seconds = time.time()
            btc_is_crashing = False
            
            # حارس البيتكوين على فريم الساعة لمنع الشراء أثناء الانهيارات الكبرى
            btc_klines = get_klines_ohlc("BTCUSDT", "1h", 3)
            if len(btc_klines) >= 3:
                highest_recent = max([c['close'] for c in btc_klines])
                current_btc = btc_klines[-1]['close']
                drop_percent = (current_btc - highest_recent) / highest_recent
                if drop_percent <= RISK_CONFIG['btc_crash_threshold']:
                    btc_is_crashing = True
                    if not btc_alert_sent:
                        send_telegram(f"🚨 *حارس البيتكوين:* هبوط حاد بنسبة `{drop_percent*100:.2f}%`. تجميد طلبات الشراء الجديدة حماية للمحفظة.")
                        btc_alert_sent = True
                else:
                    if btc_alert_sent and drop_percent > -0.02: btc_alert_sent = False

            symbols_to_fetch_klines = []
            with data_lock:
                current_open_trades = sum(1 for c_key in coin_mapping.values() if global_data.get(c_key, {}).get("is_holding", False))
                
            if current_open_trades < RISK_CONFIG['max_open_trades']:
                for symbol in coin_mapping.keys():
                    cid = coin_mapping[symbol]
                    with data_lock:
                        is_holding = global_data.get(cid, {}).get("is_holding", False)
                        last_cooldown = global_data.get(cid, {}).get("last_stop_loss_time", 0.0)
                    if not is_holding and (current_time_seconds - last_cooldown >= RISK_CONFIG['cooldown_hours'] * 3600):
                        symbols_to_fetch_klines.append(symbol)

            all_fetched_klines_15m = {}
            if symbols_to_fetch_klines:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(symbols_to_fetch_klines), 15)) as executor:
                    # جلب فريم الـ 15 دقيقة بالتوازي لرصد مؤشر البولنجر لجميع العملات
                    future_to_symbol = {executor.submit(get_klines_ohlc, sym, '15m', 30): sym for sym in symbols_to_fetch_klines}
                    for future in concurrent.futures.as_completed(future_to_symbol):
                        sym = future_to_symbol[future]
                        try: all_fetched_klines_15m[sym] = future.result()
                        except: all_fetched_klines_15m[sym] = []

            # --- المعالجة واتخاذ القرارات الاستراتيجية ---
            with data_lock:
                for symbol, price in market_prices.items():
                    cid = coin_mapping[symbol]
                    if cid not in global_data: global_data[cid] = {}
                    for key in ["held", "buy_price", "is_holding", "trailing_active", "highest_price", "last_stop_loss_time"]:
                        if key not in global_data[cid]: global_data[cid][key] = 0.0 if key != "is_holding" and key != "trailing_active" else False

                    # [1] إدارة الصفقات المفتوحة (تتبع الأرباح وتطبيق الـ Stop Loss المحكم 1.2%)
                    if global_data[cid]["is_holding"]:
                        buy_price = global_data[cid]['buy_price']
                        if buy_price == 0: continue
                        stop_loss_price = buy_price * (1 - RISK_CONFIG['stop_loss'])
                        
                        if is_first_loop and price <= stop_loss_price:
                            global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False})
                            save_needed = True; continue

                        activation_price = buy_price * (1 + RISK_CONFIG['trailing_activation'])
                        if not global_data[cid]["trailing_active"] and price >= activation_price:
                            global_data[cid]["trailing_active"] = True
                            global_data[cid]["highest_price"] = price
                            send_telegram(f"🔥 *{cid.upper()}* - دخلت منطقة التتبع الذكي! السعر الحالي: `{price}$`")
                            save_needed = True

                        if global_data[cid]["trailing_active"]:
                            if price > global_data[cid]["highest_price"]:
                                global_data[cid]["highest_price"] = price; save_needed = True
                            trailing_stop_price = global_data[cid]["highest_price"] * (1 - RISK_CONFIG['trailing_stop'])
                            if price <= trailing_stop_price:
                                net_profit = ((price - buy_price) * global_data[cid]['held']) - ((buy_price + price) * global_data[cid]['held'] * RISK_CONFIG['binance_fee_rate'])
                                update_all_stats(cid, net_profit)
                                send_telegram(f"🚀 *بيع تتبعي ناجح:* {cid.upper()}\n💰 الصافي: `{net_profit:+.2f}$` (`{((net_profit/(buy_price*global_data[cid]['held']))*100):+.2f}%`) ")
                                global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0})
                                save_needed = True; continue

                        if price <= stop_loss_price and not global_data[cid]["trailing_active"]:
                            net_loss = ((price - buy_price) * global_data[cid]['held']) - ((buy_price + price) * global_data[cid]['held'] * RISK_CONFIG['binance_fee_rate'])
                            update_all_stats(cid, net_loss)
                            global_data[cid]["last_stop_loss_time"] = current_time_seconds
                            send_telegram(f"🛑 *{cid.upper()} - حماية المحفظة (وقف خسارة)*\n📉 الخسارة: `{net_loss:.2f}$`\n⏳ عزل العملة لمدة {RISK_CONFIG['cooldown_hours']} ساعتين تفادياً للارتداد العكسي السلبي.")
                            global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0})
                            save_needed = True

                    # [2] منطق الدخول المزدوج (فريم 15 دقيقة للبولنجر -> فريم 5 دقائق لتأكيد الشموع)
                    else:
                        if current_open_trades >= RISK_CONFIG['max_open_trades']: continue
                        if current_time_seconds - global_data[cid].get("last_stop_loss_time", 0.0) < RISK_CONFIG['cooldown_hours'] * 3600: continue

                        klines_15m = all_fetched_klines_15m.get(symbol, [])
                        if len(klines_15m) < 25: continue

                        # حساب حدود البولنجر على فريم الـ 15 دقيقة (لتحديد منطقة القاع الماكرو)
                        close_prices_15m = [c['close'] for c in klines_15m[-20:]]
                        sma_15m = sum(close_prices_15m) / 20
                        variance_15m = sum((x - sma_15m)**2 for x in close_prices_15m) / 20
                        std_15m = variance_15m ** 0.5 if variance_15m > 0 else 0.001
                        lower_band_15m = sma_15m - std_15m

                        # إذا كان السعر الحالي للعملة في منطقة دعم البولنجر لـ 15 دقيقة، ننتقل للزناد الميكرو (5m)
                        if price <= lower_band_15m:
                            # جلب شموع فريم الـ 5 دقائق فوراً لهذه العملة تحديداً لتوفير معدل طلبات الـ API
                            klines_5m = get_klines_ohlc(symbol, interval='5m', limit=10)
                            
                            # تحليل السلوك السعري والشموع على فريم الـ 5 دقائق
                            pattern_signal, pattern_name = analyze_candlestick_patterns(klines_5m)

                            # تنفيذ أمر الشراء فور تأكيد فريم الـ 5 دقائق للاتجاه الصاعد
                            if not btc_is_crashing and pattern_signal == "BULLISH":
                                position_size = RISK_CONFIG['entry_amount_usd'] / price
                                global_data[cid].update({'held': position_size, 'buy_price': price, 'is_holding': True, 'trailing_active': False, 'highest_price': price})
                                send_telegram(f"🎯 *قنص مزدوج ناجح (Dual-TF Trigger):* {cid.upper()}\n⚠️ الدعم المرصود: `قاع بولنجر 15m`\n✨ تأكيد الحركة: `{pattern_name} على فريم 5m`\n💵 سعر الدخول: `{price}$` [صفقة {current_open_trades + 1}/{RISK_CONFIG['max_open_trades']}]")
                                current_open_trades += 1; save_needed = True

            if save_needed:
                with data_lock: save_global_data()
            is_first_loop = False; time.sleep(30)
        except Exception as e:
            print(f"⚠️ Error in Loop: {str(e)}", flush=True); time.sleep(30)

if __name__ == "__main__":
    with data_lock: load_global_data()
    threading.Thread(target=run_trading_bot, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=False, use_reloader=False)
