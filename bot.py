import os
import time
import threading
import json
import urllib.request
import urllib.parse
import urllib.error
import concurrent.futures  # تم إضافة المكتبة للتوازي المتقدم
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

# --- إعدادات إدارة المخاطر والدروع ---
RISK_CONFIG = {
    'entry_amount_usd': 50.0,
    'stop_loss': 0.015,            # 1.5% وقف خسارة
    'trailing_activation': 0.015,
    'trailing_stop': 0.005,
    'initial_capital': 1000.0,
    'max_open_trades': 3,          
    'cooldown_hours': 2,
    'btc_crash_threshold': -0.03   
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
        
        open_trades = []
        if "global_stats" in global_data:
            for k, v in global_data.items():
                if isinstance(v, dict) and v.get("is_holding", False):
                    open_trades.append(k.upper())

        return jsonify({
            "status": "🚀 Halal Trading Bot (Pro Async-like Performance) Running",
            "account_summary": {
                "initial_capital": f"${RISK_CONFIG['initial_capital']:.2f}",
                "current_capital": f"${current_capital:.2f}",
                "net_profit": f"${stats.get('net_profit', 0.0):.2f}"
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
            # تم حل المشكلة 4: طباعة الخطأ بوضوح لمعرفة سبب المشكلة عند تلف الملف
            print(f"❌ Error loading local JSON file: {e}", flush=True)
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

def update_all_stats(cid, diff):
    cid_upper = cid.upper()
    is_win = diff > 0

    if is_win:
        global_data["global_stats"]["wins"] += 1
