import os
import time
import threading
import json
import urllib.request
import urllib.parse
import urllib.error
import concurrent.futures  # تفعيل جلب البيانات المتوازي الفائق
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

# --- الإعدادات الذهبية المحدثة لزيادة النشاط وحساب الرسوم ---
RISK_CONFIG = {
    'entry_amount_usd': 50.0,
    'stop_loss': 0.015,            # وقف خسارة حقيقي 1.5% من حركة السوق
    'trailing_activation': 0.013,  # تفعيل الأرباح عند 1.3% (هدف سريع ومرن يتجاوز رسوم المنصة بأريحية)
    'trailing_stop': 0.003,        # تتبع ذكي بفارق 0.3% لقنص القمم
    'initial_capital': 1000.0,
    'max_open_trades': 5,          # رفع المحفظة إلى 5 صفقات متزامنة لمنع جمود البوت عند الحركة العرضية
    'cooldown_hours': 1,           # تقليص مدة حظر العملة الخاسرة إلى ساعة واحدة فقط لسرعة اقتناص الارتداد
    'btc_crash_threshold': -0.03,  # درع حماية البيتكوين
    'binance_fee_rate': 0.001      # احتساب رسوم بينانس بدقة (0.1% للشراء و 0.1% للبيع)
}

def build_telegram_table(stats_dict, title, period_label, period_value):
    coins = stats_dict.get("coins", {})
    if not coins:
        return f"📊 *{title}*\n📅 {period_label}: `{period_value}`\n\n🚫 لا توجد صفقات مسجلة في هذه الفترة بعد."
        
    table = f"📊 *{title}*\n📅 {period_label}: `{period_value}`\n\n"
    table += "```\n"
    table += f"{'COIN':<8} | {'WIN':<3} | {'LOSS':<4} | {'NET (FEES)':<10}\n"
    table += "---------------------------------\n"
    
    total_w = 0
    total_l = 0
    total_p = 0.0
    
    for c, s in coins.items():
        w = s.get("wins", 0)
        l = s.get("losses", 0)
        p = s.get("net_profit", 0.0)
        total_w += w
        total_l += l
        total_p += p
        sign = "+" if p >= 0 else ""
        table += f"{c:<8} | {w:<3} | {l:<4} | {sign}{p:.2f}$\n"
    
    table += "---------------------------------\n"
    t_sign = "+" if total_p >= 0 else ""
    table += f"{'TOTAL':<8} | {total_w:<3} | {total_l:<4} | {t_sign}{total_p:.2f}$\n"
    table += "```"
    return table

@app.route('/')
def home():
    with data_lock:
        stats = global_data.get("global_stats", {})
        total_trades = stats.get('wins', 0) + stats.get('losses', 0)
        win_rate = (stats.get('wins', 0) / total_trades * 100) if total_trades > 0 else 0
        current_capital = RISK_CONFIG['initial_capital'] + stats.get('net_profit', 0.0)
        
        open_trades = []
        if "global_stats" in global_data:
            for k, v in global_data.items():
                if isinstance(v, dict) and v.get("is_holding", False):
                    open_trades.append(k.upper())

        return jsonify({
            "status": "🚀 Halal Trading Bot (High-Activity Edition) Running",
            "account_summary": {
                "initial_capital": f"${RISK_CONFIG['initial_capital']:.2f}",
                "current_capital": f"${current_capital:.2f}",
                "net_profit_after_fees": f"${stats.get('net_profit', 0.0):.2f}"
            },
            "protection_status": {
                "max_allowed_trades": RISK_CONFIG['max_open_trades'],
                "currently_open_trades": len(open_trades),
                "active_positions": open_trades
            },
            "performance": {
                "total_trades": total_trades,
                "win_rate": f"{win_rate:.1f}%"
            },
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }), 200

@app.route('/reset-my-stats')
def reset_my_stats():
    global global_data
    with data_lock:
        global_data["global_stats"] = {"wins": 0, "losses": 0, "net_profit": 0.0, "total_win_amount": 0.0, "total_loss_amount": 0.0}
        global_data["monthly_stats"] = {"month": datetime.now().strftime("%Y-%m"), "coins": {}}
        global_data["weekly_stats"] = {"week": datetime.now().strftime("%Y-W%W"), "coins": {}}
        global_data["daily_stats"] = {"date": datetime.now().strftime("%Y-%m-%d"), "coins": {}}
        
        for key in list(global_data.keys()):
            if key not in ["global_stats", "monthly_stats", "weekly_stats", "daily_stats"]:
                if isinstance(global_data[key], dict):
                    global_data[key].update({
                        'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 
                        'trailing_active': False, 'highest_price': 0.0, 'last_stop_loss_time': 0.0
                    })
        save_global_data()
    return "⚡ Done! All stats, active positions, and cooldown filters reset to zero.", 200

def load_global_data():
    global global_data
    if BIN_ID and JSONBIN_KEY:
        try:
            url = f"https://api.jsonbin.io/v3/b/{BIN_ID}/latest"
            req = urllib.request.Request(url, headers={"X-Master-Key": JSONBIN_KEY})
            with urllib.request.urlopen(req, timeout=15) as r:
                response = json.loads(r.read().decode())
                global_data = response.get('record', {})
                for k in list(global_data.keys()):
                    if isinstance(global_data[k], dict) and "history" in global_data[k]:
                        del global_data[k]["history"]
                print("✅ Data loaded from JSONBin cloud!", flush=True)
                return
        except Exception as e:
            print(f"⚠️ JSONBin load failed ({e}). Trying local...", flush=True)
    
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                global_data = json.load(f)
                print("✅ Data loaded from local file.", flush=True)
                return
        except Exception as e:
            print(f"⚠️ CRITICAL: Error parsing or reading local JSON file: {e}", flush=True)
            
    global_data = {}

def save_global_data():
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(global_data, f, indent=2)
    except Exception as e:
        print(f"⚠️ Local save error: {e}", flush=True)
    
    if BIN_ID and JSONBIN_KEY:
        try:
            url = f"https://api.jsonbin.io/v3/b/{BIN_ID}"
            req = urllib.request.Request(
                url, data=json.dumps(global_data).encode('utf-8'),
                headers={"X-Master-Key": JSONBIN_KEY, "Content-Type": "application/json"},
                method="PUT"
            )
            urllib.request.urlopen(req, timeout=15)
        except Exception as e:
            print(f"⚠️ Cloud backup failed: {e}", flush=True)

def update_all_stats(cid, net_diff):
    cid_upper = cid.upper()
    is_win = net_diff > 0

    if is_win:
        global_data["global_stats"]["wins"] += 1
        global_data["global_stats"]["total_win_amount"] += net_diff
    else:
        global_data["global_stats"]["losses"] += 1
        global_data["global_stats"]["total_loss_amount"] += abs(net_diff)
    global_data["global_stats"]["net_profit"] += net_diff

    for report_type in ["daily_stats", "weekly_stats", "monthly_stats"]:
        if "coins" not in global_data[report_type]: global_data[report_type]["coins"] = {}
        if cid_upper not in global_data[report_type]["coins"]: 
            global_data[report_type]["coins"][cid_upper] = {"wins": 0, "losses": 0, "net_profit": 0.0}
        
        if is_win: global_data[report_type]["coins"][cid_upper]["wins"] += 1
        else: global_data[report_type]["coins"][cid_upper]["losses"] += 1
        global_data[report_type]["coins"][cid_upper]["net_profit"] += net_diff

def get_klines_closing_prices(symbol, interval='15m', limit=40):
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as f:
            data = json.loads(f.read().decode())
            return [float(candle[4]) for candle in data]
    except Exception as e:
        print(f"⚠️ Binance K-lines API Error for {symbol}: {e}", flush=True)
        return []

def run_trading_bot():
    global global_data
    
    time.sleep(15)
    print(">>> PRO BOT WITH DYNAMIC FEE DEDUCTION & HIGH-ACTIVITY LOOP STARTED <<<", flush=True)
    
    coin_mapping = {
        "BTCUSDT": "bitcoin", "ETHUSDT": "ethereum", "SOLUSDT": "solana",
        "LINKUSDT": "chainlink", "ADAUSDT": "cardano", "DOTUSDT": "polkadot",
        "NEARUSDT": "near", "ARBUSDT": "arbitrum", "OPUSDT": "optimism",
        "RENDERUSDT": "render", "RNDRUSDT": "render", "BNBUSDT": "binancecoin",   
        "POLUSDT": "polygon", "AVAXUSDT": "avalanche", "ALGOUSDT": "algorand",     
        "ATOMUSDT": "cosmos", "FETUSDT": "fetch-ai", "GRTUSDT": "the-graph",     
        "STXUSDT": "stacks", "FTMUSDT": "fantom", "LTCUSDT": "litecoin"       
    }

    def send_telegram(text):
        if not TOKEN or TOKEN == 'YOUR_TELEGRAM_TOKEN_HERE':
            return
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            data = json.dumps({"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}).encode("utf-8")
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            print(f"⚠️ Telegram API Error: {e}", flush=True)

    with data_lock:
        if "global_stats" not in global_data:
            global_data["global_stats"] = {"wins": 0, "losses": 0, "net_profit": 0.0, "total_win_amount": 0.0, "total_loss_amount": 0.0}
        if "monthly_stats" not in global_data: global_data["monthly_stats"] = {"month": datetime.now().strftime("%Y-%m"), "coins": {}}
        if "weekly_stats" not in global_data: global_data["weekly_stats"] = {"week": datetime.now().strftime("%Y-W%W"), "coins": {}}
        if "daily_stats" not in global_data: global_data["daily_stats"] = {"date": datetime.now().strftime("%Y-%m-%d"), "coins": {}}
        save_global_data()

    send_telegram("⚡ *تم إطلاق إصدار المضاربة المرنة المطور!*\n🎯 سعة المحفظة: 5 صفقات متزامنة.\n📊 نظام الخصم التلقائي لرسوم بينانس (0.2%) مفعّل لحساب صافي الأرباح الحقيقي الحرج.")

    is_first_loop = True  
    btc_alert_sent = False
    
    while True:
        try:
            current_date = datetime.now().strftime("%Y-%m-%d")
            current_week = datetime.now().strftime("%Y-W%W")
            current_month = datetime.now().strftime("%Y-%m")
            save_needed = False

            with data_lock:
                if global_data["monthly_stats"].get("month") != current_month:
                    send_telegram(build_telegram_table(global_data["monthly_stats"], "التقرير الشهري الشامل", "الشهر المنتهي", global_data["monthly_stats"].get("month")))
                    global_data["monthly_stats"] = {"month": current_month, "coins": {}}
                    save_needed = True

                if global_data["weekly_stats"].get("week") != current_week:
                    send_telegram(build_telegram_table(global_data["weekly_stats"], "التقرير الأسبوعي الشامل", "الأسبوع المنتهي", global_data["weekly_stats"].get("week")))
                    global_data["weekly_stats"] = {"week": current_week, "coins": {}}
                    save_needed = True

                if global_data["daily_stats"].get("date") != current_date:
                    send_telegram(build_telegram_table(global_data["daily_stats"], "حصاد اليوم الشامل", "التاريخ المنتهي", global_data["daily_stats"].get("date")))
                    global_data["daily_stats"] = {"date": current_date, "coins": {}}
                    save_needed = True

            try:
                url = "https://api.binance.com/api/v3/ticker/price"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=15) as f:
                    ticker_data = json.loads(f.read().decode())
                
                market_prices = {}
                for item in ticker_data:
                    if item['symbol'] in coin_mapping:
                        market_prices[item['symbol']] = float(item['price'])
            except Exception as e:
                print(f"⚠️ Binance Ticker API Error: {e}", flush=True)
                time.sleep(30)
                continue
            
            current_time_seconds = time.time()

            # --- فحص حارس البيتكوين ---
            btc_is_crashing = False
            btc_prices = get_klines_closing_prices("BTCUSDT", "1h", 6)
            if len(btc_prices) >= 6:
                highest_recent = max(btc_prices)
                current_btc = btc_prices[-1]
                drop_percent = (current_btc - highest_recent) / highest_recent
                
                if drop_percent <= RISK_CONFIG['btc_crash_threshold']:
                    btc_is_crashing = True
                    if not btc_alert_sent:
                        send_telegram(f"🚨 *حارس البيتكوين: هبوط حاد!*\nتم رصد تراجع بنسبة `{drop_percent*100:.2f}%`.\nتجميد صفقات الشراء الجديدة مؤقتاً.")
                        btc_alert_sent = True
                else:
                    if btc_alert_sent:
                        send_telegram("✅ *استقرار البيتكوين:* عودة محرك البحث للعمل بشكل طبيعي.")
                        btc_alert_sent = False

            # تجميع العملات الجاهزة للفحص بشكل متوازٍ
            symbols_to_fetch_klines = []
            with data_lock:
                current_open_trades = sum(1 for c_key in coin_mapping.values() if global_data.get(c_key, {}).get("is_holding", False))
                
            if current_open_trades < RISK_CONFIG['max_open_trades'] and not btc_is_crashing:
                for symbol in coin_mapping.keys():
                    cid = coin_mapping[symbol]
                    with data_lock:
                        is_holding = global_data.get(cid, {}).get("is_holding", False)
                        last_cooldown = global_data.get(cid, {}).get("last_stop_loss_time", 0.0)
                    cooldown_seconds = RISK_CONFIG['cooldown_hours'] * 3600
                    if not is_holding and (current_time_seconds - last_cooldown >= cooldown_seconds):
                        symbols_to_fetch_klines.append(symbol)

            all_fetched_klines = {}
            if symbols_to_fetch_klines:
                with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(symbols_to_fetch_klines), 15)) as executor:
                    future_to_symbol = {executor.submit(get_klines_closing_prices, sym, '15m', 40): sym for sym in symbols_to_fetch_klines}
                    for future in concurrent.futures.as_completed(future_to_symbol):
                        sym = future_to_symbol[future]
                        try:
                            all_fetched_klines[sym] = future.result()
                        except Exception as e:
                            all_fetched_klines[sym] = []

            # --- المعالجة واتخاذ القرارات ---
            with data_lock:
                for symbol, price in market_prices.items():
                    cid = coin_mapping[symbol]
                    if cid not in global_data:
                        global_data[cid] = {}
                    
                    for key in ["held", "buy_price", "is_holding", "trailing_active", "highest_price", "last_stop_loss_time"]:
                        if key not in global_data[cid]:
                            if key in ["held", "buy_price", "highest_price", "last_stop_loss_time"]: global_data[cid][key] = 0.0
                            elif key in ["is_holding", "trailing_active"]: global_data[cid][key] = False

                    # --- إدارة الصفقات المفتوحة ---
                    if global_data[cid]["is_holding"]:
                        buy_price = global_data[cid]['buy_price']
                        if buy_price == 0: continue
                        
                        stop_loss_price = buy_price * (1 - RISK_CONFIG['stop_loss'])
                        
                        if is_first_loop and price <= stop_loss_price:
                            global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0})
                            save_needed = True
                            continue

                        activation_price = buy_price * (1 + RISK_CONFIG['trailing_activation'])
                        
                        if not global_data[cid]["trailing_active"] and price >= activation_price:
                            global_data[cid]["trailing_active"] = True
                            global_data[cid]["highest_price"] = price
                            send_telegram(f"🔥 *{cid.upper()}* - دخلت منطقة التتبع الذكي! السعر الحالي: `{price}$`")
                            save_needed = True

                        if global_data[cid]["trailing_active"]:
                            if price > global_data[cid]["highest_price"]:
                                global_data[cid]["highest_price"] = price
                                save_needed = True
                            
                            trailing_stop_price = global_data[cid]["highest_price"] * (1 - RISK_CONFIG['trailing_stop'])
                            if price <= trailing_stop_price:
                                # احتساب الأرباح الإجمالية والخصم الدقيق للرسوم لتفادي الاختلافات
                                total_volume = (buy_price * global_data[cid]['held']) + (price * global_data[cid]['held'])
                                roundtrip_fees = total_volume * RISK_CONFIG['binance_fee_rate']
                                gross_profit = (price - buy_price) * global_data[cid]['held']
                                net_profit = gross_profit - roundtrip_fees
                                
                                update_all_stats(cid, net_profit)
                                actual_win_percent = (net_profit / (buy_price * global_data[cid]['held'])) * 100
                                
                                send_telegram(f"🚀 *بيع تتبعي ناجح:* {cid.upper()}\n💰 الصافي (بعد العمولات): `+{net_profit:.2f}$` (`+{actual_win_percent:.2f}%`)\n💼 الرسوم المستقطعة للمنصة: `{roundtrip_fees:.4f}$`")
                                global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0})
                                save_needed = True
                                continue

                        if price <= stop_loss_price and not global_data[cid]["trailing_active"]:
                            total_volume = (buy_price * global_data[cid]['held']) + (price * global_data[cid]['held'])
                            roundtrip_fees = total_volume * RISK_CONFIG['binance_fee_rate']
                            gross_loss = (price - buy_price) * global_data[cid]['held']
                            net_loss = gross_loss - roundtrip_fees # ستكون قيمة سالبة أعمق تشمل الرسوم
                            
                            update_all_stats(cid, net_loss)
                            global_data[cid]["last_stop_loss_time"] = current_time_seconds
                            
                            send_telegram(f"🛑 *{cid.upper()} - حماية المحفظة (إغلاق سلبي)*\n📉 الخسارة الصافية بـالع عمولات: `{net_loss:.2f}$`\n⏳ حظر العملة مؤقتاً لمدة {RISK_CONFIG['cooldown_hours']} ساعة للراحة.")
                            global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0})
                            save_needed = True

                    # --- فلتر الدخول المرن السريع ---
                    else:
                        if btc_is_crashing: continue 
                        if current_open_trades >= RISK_CONFIG['max_open_trades']: continue
                            
                        cooldown_seconds = RISK_CONFIG['cooldown_hours'] * 3600
                        if current_time_seconds - global_data[cid].get("last_stop_loss_time", 0.0) < cooldown_seconds: continue

                        klines = all_fetched_klines.get(symbol, [])
                        if len(klines) < 40: continue

                        # التعديل الاستراتيجي: تقليص النطاق لـ 15 شمعة لجعل البوت فائق المرونة والنشاط
                        flexible_klines = klines[-15:]
                        trend_ma = sum(flexible_klines) / len(flexible_klines)
                        if price < trend_ma: continue 

                        local_klines = klines[-20:]
                        sma = sum(local_klines) / len(local_klines)
                        variance = sum((x - sma)**2 for x in local_klines) / len(local_klines)
                        std = variance ** 0.5 if variance > 0 else 0.001
                        lower_band = sma - std

                        if price <= lower_band and price > 0:
                            position_size = RISK_CONFIG['entry_amount_usd'] / price
                            global_data[cid].update({
                                'held': position_size, 'buy_price': price, 'is_holding': True, 'trailing_active': False, 'highest_price': 0.0
                            })
                            send_telegram(f"🎯 *قنص سريع (مرونة 15 شمعة):* {cid.upper()} بسعر `{price}$` [صفقة {current_open_trades + 1}/{RISK_CONFIG['max_open_trades']}]")
                            current_open_trades += 1
                            save_needed = True

            if save_needed:
                with data_lock: save_global_data()
            
            is_first_loop = False  
            time.sleep(30) # فحص متكرر سريع كل 30 ثانية
            
        except Exception as e:
            print(f"⚠️ Error in Loop: {str(e)}", flush=True)
            time.sleep(30)

# --- نقطة التشغيل الاحترافية ---
if __name__ == "__main__":
    with data_lock:
        load_global_data()

    t = threading.Thread(target=run_trading_bot, daemon=True)
    t.start()
    
    port = int(os.environ.get('PORT', 8080))
    print(f"⚡ Launching Flask server on port {port}...", flush=True)
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
