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
REQUIRE_CLOSED_CANDLE_CONFIRMATION = True # Require fully closed M5 candle confirmation (No mid-candle jumping)

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
# DUAL-WAVE INSTITUTIONAL SESSION TRADING HOURS (UTC)
# ==========================================
# Gold institutional volume is concentrated in London Open & New York Overlap.
# Wave 1 (London Open Drive): 08:00 to 11:30 UTC (Asian sweeps & morning momentum)
# Midday Lull (Bank Lunch Chop): 11:30 to 13:00 UTC (Auto-Paused to avoid dead chop)
# Wave 2 (New York Open & Overlap): 13:00 to 17:00 UTC (Massive US macro volume)
WAVE_1_START_HOUR_UTC = 8.0    # 08:00 UTC
WAVE_1_END_HOUR_UTC = 11.5      # 11:30 UTC
WAVE_2_START_HOUR_UTC = 13.0   # 13:00 UTC
WAVE_2_END_HOUR_UTC = 17.0     # 17:00 UTC
AVOID_MIDDAY_LULL = True       # Pause during 11:30 - 13:00 UTC bank lunch lull
AVOID_ASIAN_SESSION = True     # Avoid 17:00 - 08:00 UTC low-liquidity chop

# Legacy backward-compatibility aliases
SESSION_START_HOUR_UTC = 8
SESSION_END_HOUR_UTC = 17

# ==========================================
# SCALPING RISK & POSITION SIZING
# ==========================================
RISK_PER_TRADE_PERCENT = 0.50 # Risk 0.50% equity per scalp (suitable for $25 - $1000 accounts)
ENABLE_TWO_TIER_SCALING = True # Automatically scale lot size once equity milestone is reached
TWO_TIER_EQUITY_THRESHOLD = 150.0 # Gold stays at 0.01 lot until $150 equity (protects against high Gold pip value)
BASE_LOT_SIZE = 0.01          # Minimum lot size for micro accounts under $150 (max loss ~$2.50)
SCALED_LOT_SIZE = 0.02        # 0.02 lot enables 50% TP1 partial close on $150+ accounts
MAX_OPEN_POSITIONS = 1       # Strict 1 position max at any time
MAX_DAILY_LOSS_USD = 8.00    # Hard daily equity stop (scaled to $8.00 on $80 account)
MAX_DAILY_TRADES = None      # No trade count limits (unlimited trades when valid setups occur)
BAR_COOLDOWN_M5_COUNT = 1    # Default cooldown (1 completed M5 candle)
COOLDOWN_BARS_AFTER_WIN = 1   # 1 M5 candle (5 mins) cooldown after TP / profitable exit
COOLDOWN_BARS_AFTER_LOSS = 2  # 2 M5 candles (10 mins) cooldown after SL / loss
CONSECUTIVE_LOSS_LIMIT = 3   # Circuit breaker: pause after 3 consecutive losses
CONSECUTIVE_LOSS_COOLDOWN_BARS = 6 # 6 M5 bars (30 min) cooling period after circuit breaker

# Dynamic ATR Stop Loss & Take Profit for Gold
ATR_PERIOD = 14
ATR_SL_MULTIPLIER = 1.15     # Tightened Stop Loss = 1.15 x ATR
MAX_SL_DOLLARS = 2.50        # Hard ceiling on Stop Loss: Max loss on 0.01 lot is strictly -$2.50
MAX_ALLOWED_ATR_USD = 3.50   # Volatility Shield: Disallow Gold scalping if M5 ATR exceeds $3.50 (e.g. news/NY open)
ATR_TP_MULTIPLIER = 1.8      # Baseline dynamic Take Profit multiplier (1.8x ATR -> $3.00 - $3.50 target)
MAX_TP_DOLLARS = 3.50        # Hard cap on Take Profit: max $3.00 - $3.50 profit on 0.01 lot ($3.50 price distance)
MIN_TP_DOLLARS = 2.50        # Minimum TP floor ($2.50 price distance -> ensures positive R:R)
USE_PARTIAL_TP = True
PARTIAL_TP_ATR_MULT = 1.20   # TP1 partial close at 1.2x ATR distance (~$2.20 - $2.50 profit)
PARTIAL_TP_RATIO = PARTIAL_TP_ATR_MULT # Backward-compatibility alias
BREAK_EVEN_BUFFER_USD = 0.50 # Move SL to Entry + $0.50 when TP1 is banked (locks +$0.50 profit)
BREAK_EVEN_BUFFER_PIPS = 5.0 # Legacy alias ($0.50 on Gold)

# Trailing Stop
ENABLE_TRAILING_STOP = True
TRAILING_ATR_MULT = 1.25     # Trailing distance = 1.25x ATR ($2.50 buffer)
TRAILING_STEP_USD = 0.30     # Ratchet step: minimum $0.30 advance before updating SL

# ==========================================
# FILTERS & SAFETY GUARDS
# ==========================================
MAX_SPREAD_POINTS = 300      # Max allowed spread in points ($0.30 on Gold - accommodates Exness standard spread)
MIN_WICK_PERCENT = 15.0      # Minimum absorption wick % required (Walk-Forward Champion)
MAX_HOLD_BARS_M5 = 24        # Time exit: close after 24 M5 bars / 2 hours
MAX_CHOP_INDEX = 61.8        # Choppiness index ceiling (> 61.8 is extreme sideways consolidation)
MIN_ADX_THRESHOLD = 20.0     # ADX trend strength reference
Z_SCORE_PULLBACK_MAX = 1.5   # Z-Score limit: filters exhausted spikes
MIN_CONFLUENCE_THRESHOLD = 75 # Strict Grade A threshold: Minimum 75/100 points required (No low-conviction trades)
ENFORCE_STRICT_H1_ALIGNMENT = True # Zero counter-trend trades: 100% ban trades conflicting with H1 macro trend
NEWS_FILTER_ENABLED = True   # Halt 30m before and after High-Impact US news
NEWS_PRE_BUFFER_MINS = 30    # Minutes before news event to halt entries
NEWS_POST_BUFFER_MINS = 30   # Minutes after news event to resume entries
MAGIC_NUMBER = 777001        # Unique Magic Number for Gold Scalper
DAILY_REPORT_HOUR_UTC = 0    # 00:00 UTC End-of-Day Digest

