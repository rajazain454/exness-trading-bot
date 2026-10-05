"""
Gold (XAUUSDm) Institutional Scalper Configuration
Completely independent from the multi-asset swing bot.
Tailored specifically for Gold liquidity sweeps, fast EMA pullbacks, and session momentum.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# EXNESS ACCOUNT SETTINGS
# ==========================================
MT5_LOGIN = os.getenv("MT5_LOGIN", "")
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")
MT5_PATH = os.getenv("MT5_PATH", "")

# ==========================================
# DISCORD NOTIFICATIONS
# ==========================================
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# ==========================================
# INSTRUMENT & TIMEFRAME
# ==========================================
SYMBOL = "XAUUSDm"
TIMEFRAME = "M5"             # Primary execution timeframe (M5 for clean institutional noise reduction)
SCALP_TIMEFRAME = "M1"       # Ultra-fast micro-structure confirmation (M1)
HIGHER_TIMEFRAME = "H1"      # Macro trend filter (H1)

# Moving Averages
EMA_FAST = 9                 # 9-period EMA
EMA_SLOW = 21                # 21-period EMA
EMA_TREND = 50               # 50-period Trend Baseline

# ==========================================
# SESSION TRADING HOURS (UTC)
# ==========================================
# Gold institutional volume is concentrated in London & New York
SESSION_START_HOUR_UTC = 7   # 07:00 UTC (London Open)
SESSION_END_HOUR_UTC = 18    # 18:00 UTC (London Close / NY Afternoon)
AVOID_ASIAN_SESSION = True   # Avoid 22:00 - 06:00 UTC low-liquidity chop

# ==========================================
# SCALPING RISK & POSITION SIZING
# ==========================================
RISK_PER_TRADE_PERCENT = 0.50 # Risk 0.50% equity per scalp (suitable for $25 - $1000 accounts)
MAX_OPEN_POSITIONS = 1       # Strict 1 position max at any time
MAX_DAILY_LOSS_USD = 5.00    # Hard equity stop on a small account ($5.00)
MAX_DAILY_TRADES = 6         # Cap daily scalps to prevent overtrading

# Dynamic ATR Stop Loss & Take Profit for Gold
ATR_PERIOD = 14
ATR_SL_MULTIPLIER = 1.3      # Stop Loss = 1.3 x ATR (~$2.00 - $3.50 on Gold)
ATR_TP_MULTIPLIER = 2.0      # Take Profit = 2.0 x SL (~$4.00 - $7.00 on Gold, 1:2 RR)

# Smart Partial Take-Profit & Break-Even
USE_PARTIAL_TP = True
PARTIAL_TP_RATIO = 1.0       # Bank 50% profit at 1.0x ATR move
BREAK_EVEN_BUFFER_PIPS = 2.0 # Move SL to Entry + $0.20 when TP1 is banked

# Trailing Stop
ENABLE_TRAILING_STOP = True
TRAILING_ATR_MULT = 1.2      # Trailing distance = 1.2x ATR once in profit

# ==========================================
# FILTERS & SAFETY GUARDS
# ==========================================
MAX_SPREAD_POINTS = 350      # Max allowed spread in points ($0.35 on Gold)
MAX_CHOP_INDEX = 58.0        # Choppiness index filter (CHOP > 58 = block trades)
MIN_ADX_THRESHOLD = 22.0     # Trend strength floor (ADX > 22 required)
Z_SCORE_PULLBACK_MAX = 2.2   # Reject overextended price spikes
NEWS_FILTER_ENABLED = True   # Halt 30m before and after High-Impact US news
MAGIC_NUMBER = 777001        # Unique Magic Number for Gold Scalper
