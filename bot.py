import os
import time
import threading
import json
import urllib.request
import urllib.parse
import urllib.error
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

# --- إعدادات إدارة المخاطر المحسنة والمثبتة ---
RISK_CONFIG = {
    'entry_amount_usd': 50.0,      # مبلغ الدخول الثابت لكل صفقة
    'stop_loss': 0.025,            # 2.5% وقف خسارة مستهدف
    'trailing_activation': 0.015,  # 1.5% تفعيل التتبع الحركي
    'trailing_stop': 0.005,        # 0.5% حماية الأرباح
    'initial_capital': 1000.0      # رأس المال الافتراضي الأولي
}

def build_telegram_table(stats_dict, title, period_label, period_value):
    coins = stats_dict.get("coins", {})
    if not coins:
        return f"📊 *{title}*\n📅 {period_label}: `{period_value}`\n\n🚫 لا توجد صفقات مسجلة في هذه الفترة بعد."
        
    table = f"📊 *{title}*\n📅 {period_label}: `{period_value}`\n\n"
    table += "```\n"
    table += f"{'COIN':<8} | {'WIN':<3} | {'LOSS':<4} | {'NET PROFIT':<10}\n"
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
        
        return jsonify({
            "status": "🚀 Halal Trading Bot Running Smoothly",
            "account_summary": {
                "initial_capital": f"${RISK_CONFIG['initial_capital']:.2f}",
                "current_capital": f"${current_capital:.2f}",
                "net_profit": f"${stats.get('net_profit', 0.0):.2f}"
            },
            "performance": {
                "total_trades": total_trades,
                "win_rate": f"{win_rate:.1f}%"
            },
            "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }), 200

def load_global_data():
    global global_data
    if BIN_ID and JSONBIN_KEY:
        try:
            url = f"https://api.jsonbin.io/v3/b/{BIN_ID}/latest"
            req = urllib.request.Request(url, headers={"X-Master-Key": JSONBIN_KEY})
            with urllib.request.urlopen(req, timeout=15) as r:
                response = json.loads(r.read().decode())
                global_data = response.get('record', {})
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
        except:
            pass
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
                url,
                data=json.dumps(global_data).encode('utf-8'),
                headers={"X-Master-Key": JSONBIN_KEY, "Content-Type": "application/json"},
                method="PUT"
            )
            urllib.request.urlopen(req, timeout=15)
            print("💾 Cloud backup synchronized!", flush=True)
        except Exception as e:
            print(f"⚠️ Cloud backup failed: {e}", flush=True)

def update_all_stats(cid, diff):
    cid_upper = cid.upper()
    is_win = diff > 0

    if is_win:
        global_data["global_stats"]["wins"] += 1
        global_data["global_stats"]["total_win_amount"] += diff
    else:
        global_data["global_stats"]["losses"] += 1
        global_data["global_stats"]["total_loss_amount"] += abs(diff)
    global_data["global_stats"]["net_profit"] += diff

    for report_type in ["daily_stats", "weekly_stats", "monthly_stats"]:
        if "coins" not in global_data[report_type]: global_data[report_type]["coins"] = {}
        if cid_upper not in global_data[report_type]["coins"]: 
            global_data[report_type]["coins"][cid_upper] = {"wins": 0, "losses": 0, "net_profit": 0.0}
        
        if is_win: global_data[report_type]["coins"][cid_upper]["wins"] += 1
        else: global_data[report_type]["coins"][cid_upper]["losses"] += 1
        global_data[report_type]["coins"][cid_upper]["net_profit"] += diff

def run_trading_bot():
    global global_data
    print(">>> TRADING BOT WITH REPORT TABLES STARTED <<<", flush=True)
    
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
            print(f"Telegram error: {e}", flush=True)

    with data_lock:
        load_global_data()
        if "global_stats" not in global_data:
            global_data["global_stats"] = {"wins": 0, "losses": 0, "net_profit": 0.0, "total_win_amount": 0.0, "total_loss_amount": 0.0}
        if "monthly_stats" not in global_data: global_data["monthly_stats"] = {"month": datetime.now().strftime("%Y-%m"), "coins": {}}
        if "weekly_stats" not in global_data: global_data["weekly_stats"] = {"week": datetime.now().strftime("%Y-W%W"), "coins": {}}
        if "daily_stats" not in global_data: global_data["daily_stats"] = {"date": datetime.now().strftime("%Y-%m-%d"), "coins": {}}
        save_global_data()

    send_telegram("🚀 تم تشغيل البوت بنجاح وحقن فلاتر حماية الإحصائيات عند الإقلاع.")

    is_first_loop = True  # تفعيل راية الدورة الأولى البرمجية
    
    while True:
        try:
            current_date = datetime.now().strftime("%Y-%m-%d")
            current_week = datetime.now().strftime("%Y-W%W")
            current_month = datetime.now().strftime("%Y-%m")
            save_needed = False

            with data_lock:
                if global_data["monthly_stats"].get("month") != current_month:
                    send_telegram(build_telegram_table(global_data["monthly_stats"], "التقرير الشهري الختامي للنتائج", "الشهر المنتهي", global_data["monthly_stats"].get("month")))
                    global_data["monthly_stats"] = {"month": current_month, "coins": {}}
                    save_needed = True

                if global_data["weekly_stats"].get("week") != current_week:
                    send_telegram(build_telegram_table(global_data["weekly_stats"], "التقرير الأسبوعي الختامي للنتائج", "الأسبوع المنتهي", global_data["weekly_stats"].get("week")))
                    global_data["weekly_stats"] = {"week": current_week, "coins": {}}
                    save_needed = True

                if global_data["daily_stats"].get("date") != current_date:
                    send_telegram(build_telegram_table(global_data["daily_stats"], "التقرير اليومي للحصاد (كل 24 ساعة)", "التاريخ المنتهي", global_data["daily_stats"].get("date")))
                    global_data["daily_stats"] = {"date": current_date, "coins": {}}
                    save_needed = True

            try:
                url = "https://api.binance.com/api/v3/ticker/price"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=15) as f:
                    ticker_data = json.loads(f.read().decode())
            except Exception as e:
                time.sleep(60)
                continue
            
            market_prices = {}
            for item in ticker_data:
                if item['symbol'] in coin_mapping:
                    market_prices[coin_mapping[item['symbol']]] = float(item['price'])
            
            current_time_seconds = time.time()

            with data_lock:
                for cid, price in market_prices.items():
                    if cid not in global_data:
                        global_data[cid] = {}
                    
                    for key in ["history", "held", "buy_price", "is_holding", "trailing_active", "highest_price", "last_history_time"]:
                        if key not in global_data[cid]:
                            if key == "history": global_data[cid][key] = []
                            elif key in ["held", "buy_price", "highest_price"]: global_data[cid][key] = 0.0
                            elif key in ["is_holding", "trailing_active"]: global_data[cid][key] = False
                            elif key == "last_history_time": global_data[cid][key] = 0.0

                    if current_time_seconds - global_data[cid]["last_history_time"] >= 300:
                        global_data[cid]["history"].append(price)
                        if len(global_data[cid]["history"]) > 20: global_data[cid]["history"].pop(0)
                        global_data[cid]["last_history_time"] = current_time_seconds
                        save_needed = True

                    # --- إدارة وتدقيق الصفقات المفتوحة ---
                    if global_data[cid]["is_holding"]:
                        buy_price = global_data[cid]['buy_price']
                        if buy_price == 0: continue
                        
                        actual_change_percent = ((price - buy_price) / buy_price) * 100
                        stop_loss_price = buy_price * (1 - RISK_CONFIG['stop_loss'])
                        
                        # [فلتر أمان متطور]: إذا أشرق البوت على هبوط تجاوز الوقف بسبب فترة التحديث صيانة الخدمة
                        # يتم تصفير تعقب العملة فوراً بشكل نظيف ودون تلويث سجل الأرباح الفعلي
                        if is_first_loop and price <= stop_loss_price:
                            print(f"🛡️ Safety Guard: Dropped stale position for {cid.upper()} to avoid update slippage.", flush=True)
                            send_telegram(f"🛡️ *تنبيه أمان التحديث:* تم تصفير تعقب صفقة {cid.upper()} القديمة تلقائياً دون احتساب خسارة، نظراً لأن الهبوط تم أثناء إغلاق البوت للتحديث.")
                            global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0})
                            save_needed = True
                            continue

                        activation_price = buy_price * (1 + RISK_CONFIG['trailing_activation'])
                        
                        if not global_data[cid]["trailing_active"] and price >= activation_price:
                            global_data[cid]["trailing_active"] = True
                            global_data[cid]["highest_price"] = price
                            send_telegram(f"🔥 *{cid.upper()}* - تجاوزت الـ +{RISK_CONFIG['trailing_activation']*100}% وبدأ التتبع الحركي السعر: {price}$")
                            save_needed = True

                        if global_data[cid]["trailing_active"]:
                            if price > global_data[cid]["highest_price"]:
                                global_data[cid]["highest_price"] = price
                                save_needed = True
                            
                            trailing_stop_price = global_data[cid]["highest_price"] * (1 - RISK_CONFIG['trailing_stop'])
                            if price <= trailing_stop_price:
                                diff = (price - buy_price) * global_data[cid]['held']
                                update_all_stats(cid, diff)
                                actual_win_percent = ((price - buy_price) / buy_price) * 100
                                send_telegram(f"🚀 *بيع ذكي بمطاردة الأرباح:* {cid.upper()}\n💰 صافي الربح: `+{diff:.2f}$` (`+{actual_win_percent:.2f}%`) ")
                                global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0})
                                save_needed = True
                                continue

                        # الخروج العادي بوقف خسارة حي مستقر أثناء عمل البوت
                        if price <= stop_loss_price and not global_data[cid]["trailing_active"]:
                            diff = (price - buy_price) * global_data[cid]['held']
                            update_all_stats(cid, diff)
                            send_telegram(f"🛑 *{cid.upper()} - ضرب وقف الخسارة الثابت*\n📉 الخسارة الحقيقية: `{diff:.2f}$` (`{actual_change_percent:.2f}%`) ")
                            global_data[cid].update({'held': 0.0, 'buy_price': 0.0, 'is_holding': False, 'trailing_active': False, 'highest_price': 0.0})
                            save_needed = True

                    # --- منطق الشراء المستقر بقيمة 50$ ---
                    else:
                        h = global_data[cid]["history"]
                        if len(h) < 5: continue
                        
                        sma = sum(h) / len(h)
                        variance = sum((x - sma)**2 for x in h) / len(h)
                        std = variance ** 0.5 if variance > 0 else 0.001
                        lower_band = sma - std
                        
                        if price <= lower_band and price > 0:
                            position_size = RISK_CONFIG['entry_amount_usd'] / price
                            global_data[cid].update({
                                'held': position_size, 'buy_price': price, 'is_holding': True, 'trailing_active': False, 'highest_price': 0.0
                            })
                            send_telegram(f"🎯 *قناص الشراء:* اقتناص {cid.upper()} بسعر `{price:.4f}$` بإجمالي استثمار 50$")
                            save_needed = True

            if save_needed:
                with data_lock: save_global_data()
            
            is_first_loop = False  # إغلاق نمط الإقلاع ليعود الرصد حياً ومباشراً ومحكماً
            time.sleep(30)
            
        except Exception as e:
            print(f"⚠️ Error in Loop: {str(e)}", flush=True)
            time.sleep(60)

if __name__ == "__main__":
    t = threading.Thread(target=run_trading_bot, daemon=True)
    t.start()
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
