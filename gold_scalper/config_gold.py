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
SESSION_START_HOUR_UTC = 8   # 08:00 UTC (London Open)
SESSION_END_HOUR_UTC = 16    # 16:00 UTC (London Close - avoid low-liquidity late whipsaws)
AVOID_ASIAN_SESSION = True   # Avoid 22:00 - 06:00 UTC low-liquidity chop

# ==========================================
# SCALPING RISK & POSITION SIZING
# ==========================================
RISK_PER_TRADE_PERCENT = 0.50 # Risk 0.50% equity per scalp (suitable for $25 - $1000 accounts)
MAX_OPEN_POSITIONS = 1       # Strict 1 position max at any time
MAX_DAILY_LOSS_USD = 5.00    # Hard equity stop on a small account ($5.00)
MAX_DAILY_TRADES = 6         # Cap daily scalps to prevent overtrading
BAR_COOLDOWN_M5_COUNT = 1    # Cooldown: Require at least 1 full new completed M5 candle after any trade exit

# Dynamic ATR Stop Loss & Take Profit for Gold
ATR_PERIOD = 14
ATR_SL_MULTIPLIER = 1.3      # Stop Loss = 1.3 x ATR (~$3.80 - $5.20 breathing room on Gold)
ATR_TP_MULTIPLIER = 1.1      # Take Profit baseline multiplier (~1.1x ATR)
TARGET_TP_MIN_USD = 3.50     # Floor: Minimum Take Profit $3.50 on 0.01 lot ($3.50 target)
TARGET_TP_MAX_USD = 5.00     # Cap: Maximum Take Profit $5.00 on 0.01 lot ($5.00 target)

# Smart Partial Take-Profit & Break-Even
USE_PARTIAL_TP = True
PARTIAL_TP_RATIO = 0.6       # Bank partial / trigger BE at ~$1.80 - $2.20 move
BREAK_EVEN_BUFFER_PIPS = 2.0 # Move SL to Entry + $0.20 when TP1 is banked

# Trailing Stop
ENABLE_TRAILING_STOP = True
TRAILING_ATR_MULT = 1.2      # Trailing distance = 1.2x ATR once in profit
TRAILING_STEP_USD = 0.25     # Ratchet step: minimum $0.25 advance before updating SL

# ==========================================
# FILTERS & SAFETY GUARDS
# ==========================================
MAX_SPREAD_POINTS = 350      # Max allowed spread in points ($0.35 on Gold)
MAX_CHOP_INDEX = 58.0        # Choppiness index filter (CHOP > 58 = block trades)
MIN_ADX_THRESHOLD = 22.0     # Trend strength floor (ADX > 22 required)
Z_SCORE_PULLBACK_MAX = 2.2   # Reject overextended price spikes
NEWS_FILTER_ENABLED = True   # Halt 30m before and after High-Impact US news
MAGIC_NUMBER = 777001        # Unique Magic Number for Gold Scalper
