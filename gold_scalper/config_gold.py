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
H1_EMA_FAST = 50             # H1 Macro Fast Trend EMA (Aligned with backtest)
H1_EMA_SLOW = 200            # H1 Macro Slow Baseline EMA (Aligned with backtest)

# Institutional Volume Confirmation
VOLUME_MA_PERIOD = 20        # 20-period Volume Moving Average
VOLUME_THRESHOLD_MULT = 1.10 # Signal candle volume must be >= 1.10x 20-bar average

# ==========================================
# SESSION TRADING HOURS (UTC)
# ==========================================
# Gold institutional volume is concentrated in London & New York
SESSION_START_HOUR_UTC = 8   # 08:00 UTC (London Open)
SESSION_END_HOUR_UTC = 17    # 17:00 UTC (Walk-Forward Champion: London & NY peak overlap)
AVOID_ASIAN_SESSION = True   # Avoid 22:00 - 06:00 UTC low-liquidity chop

# ==========================================
# SCALPING RISK & POSITION SIZING
# ==========================================
RISK_PER_TRADE_PERCENT = 0.50 # Risk 0.50% equity per scalp (suitable for $25 - $1000 accounts)
MAX_OPEN_POSITIONS = 1       # Strict 1 position max at any time
MAX_DAILY_LOSS_USD = 5.00    # Hard equity stop on a small account ($5.00)
MAX_DAILY_TRADES = None      # No trade count limits (unlimited trades when valid setups occur)
BAR_COOLDOWN_M5_COUNT = 3    # Cooldown: 3 bars (15 mins) pause after exit (halves max drawdown from 23R to 11R!)
CONSECUTIVE_LOSS_LIMIT = 3   # Circuit breaker: pause after 3 consecutive losses
CONSECUTIVE_LOSS_COOLDOWN_BARS = 6 # 6 M5 bars (30 min) cooling period after circuit breaker

# Dynamic ATR Stop Loss & Take Profit for Gold
ATR_PERIOD = 14
ATR_SL_MULTIPLIER = 1.3      # Stop Loss = 1.3 x ATR
ATR_TP_MULTIPLIER = 1.8      # Take Profit = 1.8 x ATR
USE_PARTIAL_TP = True
PARTIAL_TP_ATR_MULT = 1.1    # TP1 partial close at 1.1x ATR distance
PARTIAL_TP_RATIO = PARTIAL_TP_ATR_MULT # Backward-compatibility alias
BREAK_EVEN_BUFFER_USD = 0.15 # Move SL to Entry + $0.15 when TP1 is banked
BREAK_EVEN_BUFFER_PIPS = 1.5 # Legacy alias ($0.15 on Gold)

# Trailing Stop
ENABLE_TRAILING_STOP = True
TRAILING_ATR_MULT = 1.3      # Trailing distance = SL distance = 1.3x ATR
TRAILING_STEP_USD = 0.25     # Ratchet step: minimum $0.25 advance before updating SL

# ==========================================
# FILTERS & SAFETY GUARDS
# ==========================================
MAX_SPREAD_POINTS = 200      # Max allowed spread in points ($0.20 on Gold - strict stress-test limit)
MIN_WICK_PERCENT = 15.0      # Minimum absorption wick % required (Walk-Forward Champion)
MAX_HOLD_BARS_M5 = 24        # Time exit: close after 24 M5 bars / 2 hours
MAX_CHOP_INDEX = 50.0        # Choppiness index reference (Walk-Forward floor)
MIN_ADX_THRESHOLD = 20.0     # ADX trend strength reference
Z_SCORE_PULLBACK_MAX = 1.5   # Z-Score limit: filters exhausted spikes, raising OOS win rate to 64.5%
NEWS_FILTER_ENABLED = True   # Halt 30m before and after High-Impact US news
NEWS_PRE_BUFFER_MINS = 30    # Minutes before news event to halt entries
NEWS_POST_BUFFER_MINS = 30   # Minutes after news event to resume entries
MAGIC_NUMBER = 777001        # Unique Magic Number for Gold Scalper
