"""
==========================================================
Shadow Trading System V3
Global Configuration
==========================================================
"""

import os

# ==========================================================
# PROJECT
# ==========================================================
PROJECT_NAME = "Shadow Trading System V3"
VERSION = "3.0.0"
DEBUG = False

# ==========================================================
# BINANCE
# ==========================================================
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")
USE_TESTNET = False

# ==========================================================
# TELEGRAM
# Render production names are TOKEN and TELEGRAMID.
# Legacy names remain supported as fallbacks.
# ==========================================================
TELEGRAM_TOKEN = os.getenv("TOKEN") or os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAMID") or os.getenv("TELEGRAM_CHAT_ID", "")
ENABLE_TELEGRAM = os.getenv("ENABLE_TELEGRAM", "true").lower() not in {"0", "false", "no"}

# ==========================================================
# ACCOUNT
# ==========================================================
INITIAL_BALANCE = 10000.0
TRADING_FEE = 0.001
SLIPPAGE = 0.0005
MIN_ORDER_SIZE = 10.0

# ==========================================================
# TRADING MODES
# ==========================================================
ENABLE_SCALPING = True
ENABLE_SWING = True
AUTO_SELECT_MODE = True

# ==========================================================
# RISK MANAGEMENT
# ==========================================================
MAX_PORTFOLIO_EXPOSURE = 0.70
MAX_POSITION_SIZE = 0.10
MIN_POSITION_SIZE = 0.02
MAX_OPEN_TRADES = 8
MAX_SCALPING_TRADES = 5
MAX_SWING_TRADES = 3

# ==========================================================
# SCALPING
# ==========================================================
SCALPING_TIMEFRAME = "5m"
SCALPING_TAKE_PROFIT = 0.020
SCALPING_STOP_LOSS_ATR = 1.8

# ==========================================================
# SWING
# ==========================================================
SWING_TIMEFRAME = "1h"
SWING_TAKE_PROFIT = 0.12
SWING_STOP_LOSS_ATR = 2.5

# ==========================================================
# TRAILING STOP
# ==========================================================
ENABLE_TRAILING = True
TRAILING_START = 0.015
TRAILING_DISTANCE = 0.007

# ==========================================================
# BREAK EVEN
# ==========================================================
ENABLE_BREAK_EVEN = True
BREAK_EVEN_TRIGGER = 0.015
BREAK_EVEN_OFFSET = 0.002

# ==========================================================
# RECOVERY
# ==========================================================
ENABLE_RECOVERY = True
MAX_RECOVERY_DAYS = 7
EMERGENCY_STOP_LOSS = 0.08
RECOVERY_ALLOWED = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "LINKUSDT"}

# ==========================================================
# WATCHLIST
# ==========================================================
WATCHLIST_SIZE = 20
MIN_24H_VOLUME_USD = 50_000_000
MIN_DAILY_VOLATILITY = 0.015

# ==========================================================
# CONFIDENCE
# ==========================================================
BUY_SCORE = 80
STRONG_BUY_SCORE = 90
SELL_SCORE = -50

# ==========================================================
# ALLOWED COINS
# ==========================================================
ALLOWED_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "LINKUSDT", "AVAXUSDT",
    "ADAUSDT", "ATOMUSDT", "NEARUSDT", "SUIUSDT", "INJUSDT", "RENDERUSDT",
]

# ==========================================================
# MARKET FILTER
# ==========================================================
USE_BTC_FILTER = True
BTC_SYMBOL = "BTCUSDT"
BTC_BEAR_THRESHOLD = -0.03

# ==========================================================
# INDICATORS
# ==========================================================
EMA_FAST = 20
EMA_SLOW = 50
EMA_TREND = 200
RSI_PERIOD = 14
ATR_PERIOD = 14
VOLUME_PERIOD = 20
ADX_PERIOD = 14

# ==========================================================
# REPORTS
# ==========================================================
SAVE_TRADES = True
SAVE_REPORTS = True
REPORT_FOLDER = "reports"
LOG_FOLDER = "logs"
ANALYTICS_FOLDER = "analytics"

# ==========================================================
# LOGGING / HEARTBEAT
# ==========================================================
LOG_LEVEL = "INFO"
HEARTBEAT_SECONDS = 30
RECONNECT_DELAY = 5
PING_INTERVAL = 20
