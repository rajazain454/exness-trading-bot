import os
from dotenv import load_dotenv

# Load environment variables from .env if present
load_dotenv()

# ==========================================
# EXNESS ACCOUNT SETTINGS
# ==========================================
MT5_LOGIN = os.getenv("MT5_LOGIN", "")
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")  # e.g., 'Exness-MT5Trial16' or 'Exness-MT5Real'
MT5_PATH = os.getenv("MT5_PATH", "")

# ==========================================
# DISCORD REAL-TIME NOTIFICATIONS
# ==========================================
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# ==========================================
# TRADING INSTRUMENT & BASKET SCANNER
# ==========================================
SYMBOL = os.getenv("TRADING_SYMBOL", "EURUSDm")
USE_MULTI_PAIR_BASKET = True  # Scans major pairs and picks the best setup
# Curated 1-Year Historical Winners with Active Broker Ticks (EURUSDm, GBPUSDm, BTCUSDm)
SYMBOLS_BASKET = ["EURUSDm", "GBPUSDm", "BTCUSDm"]

TIMEFRAME = "M5"              # Primary execution timeframe
HIGHER_TIMEFRAME = "H1"       # Macro trend alignment timeframe
EMA_FAST = 9                  # Fast Trend Exponential Moving Average
EMA_SLOW = 21                 # Slow Trend Exponential Moving Average
EMA_TREND_BASELINE = 50       # Macro Trend Baseline EMA Filter

# ==========================================
# QUANTITATIVE & STATISTICAL PARAMETERS
# ==========================================
# 1. Fractional Kelly Criterion Position Sizing
USE_KELLY_SIZING = True
KELLY_FRACTION = 0.25         # Quarter-Kelly for maximum safety on $30 capital

# 2. Z-Score Statistical Pullback Filter
Z_SCORE_FILTER_ENABLED = True
Z_SCORE_PULLBACK_THRESHOLD = 0.8  # Must be >= 0.8 std dev stretched for discount entry
Z_SCORE_PULLBACK_MAX = 2.0        # Cap maximum overextension

# 3. Fractal Choppiness Index (CHOP)
CHOP_FILTER_ENABLED = True
MAX_CHOPPINESS_INDEX = 61.8   # Block entries when CHOP > 61.8 (random walk consolidation)
CHOP_MAX_THRESHOLD = 61.8

# 4. Intraday VWAP Anchor
VWAP_FILTER_ENABLED = True

# 5. Volatility Regime ATR Percentile Adaptive Payoff
ADAPTIVE_ATR_PERCENTILE_ENABLED = True

# 6. Mathematical Expected Value (EV) Gatekeeper
EXPECTED_VALUE_FILTER_ENABLED = True
MIN_EV_RATIO = 0.25           # Require EV >= +0.25x the risk before executing
MIN_EXPECTED_VALUE_USD = 0.30 # Require EV >= +$0.30 per trade

# ==========================================
# EXECUTION PRECISION & SLIPPAGE MONITOR
# ==========================================
ENTRY_ORDER_TYPE = os.getenv("ENTRY_ORDER_TYPE", "MARKET")
LIMIT_PULLBACK_OFFSET_PIPS = 0.8
PENDING_ORDER_EXPIRY_MINS = 15
MAX_SPREAD_PIPS = 3.5             # Max spread allowed for Forex majors
MAX_SPREAD_PIPS_CRYPTO = 2500.0   # Max spread allowed for crypto points/pips
MAX_SLIPPAGE_WARNING_PIPS = 0.5

# ==========================================
# SMART MONEY CONCEPTS (SMC) & MARKET STRUCTURE
# ==========================================
SMC_FILTER_ENABLED = True
KEY_LEVEL_PROXIMITY_PIPS = 5.0
FAIR_VALUE_GAP_ENABLED = True

# ==========================================
# TREND STRENGTH & ADX CHOP FILTER
# ==========================================
ADX_FILTER_ENABLED = True
MIN_ADX_THRESHOLD = 20.0
ADX_PERIOD = 14

# ==========================================
# CURRENCY STRENGTH METER (CSM)
# ==========================================
CSM_FILTER_ENABLED = True
MIN_CSM_DIFFERENTIAL = 1.0

# ==========================================
# PRICE ACTION WICKS & VOLUME SURGE FILTER
# ==========================================
PRICE_ACTION_FILTER_ENABLED = True
MIN_REJECTION_WICK_RATIO = 0.15
MIN_VOLUME_SURGE_RATIO = 1.0

# ==========================================
# FLASH CRASH & SPREAD ANOMALY SHIELD
# ==========================================
SPREAD_ANOMALY_ENABLED = True
SPREAD_SPIKE_MULTIPLIER = 2.5
ROLLING_SPREAD_WINDOW = 30

# ==========================================
# SMART PARTIAL PROFIT TAKING (SCALE-OUT)
# ==========================================
ENABLE_PARTIAL_TP = True
PARTIAL_TP_PIPS = 15.0
PARTIAL_CLOSE_RATIO = 0.50

# ==========================================
# RISK MANAGEMENT & AUTO-COMPOUNDING
# ==========================================
BASE_LOT_SIZE = 0.01
MAX_OPEN_POSITIONS = 1        # Strictly 1 position across account for $30 capital

ENABLE_COMPOUNDING = True
CAPITAL_PER_001_LOT = 30.0
MAX_LOT_SIZE = 0.10

MAX_CONSECUTIVE_LOSSES = 2
COOLDOWN_HOURS = 3
MAX_DAILY_LOSS_USD = 5.0

# ==========================================
# DYNAMIC ATR-BASED STOP LOSS & TAKE PROFIT
# ==========================================
USE_DYNAMIC_ATR_SLTP = True
ATR_SL_MULTIPLIER = 1.5
ATR_TP_MULTIPLIER = 2.5
MIN_SL_PIPS = 10.0
MAX_SL_PIPS = 20.0

STATIC_STOP_LOSS_PIPS = 15.0
STATIC_TAKE_PROFIT_PIPS = 25.0

BREAKEVEN_TRIGGER_PIPS = 10.0
BREAKEVEN_OFFSET_PIPS = 1.0
TRAILING_STOP_ENABLED = True
TRAILING_DISTANCE_PIPS = 12.0
TRAILING_STEP_PIPS = 3.0

# ==========================================
# SESSION & ROLLOVER FILTER (UTC)
# ==========================================
SESSION_FILTER_ENABLED = True
ACTIVE_SESSIONS = [
    {"name": "London/NY Overlap", "start_hour": 7, "end_hour": 20}
]
ROLLOVER_BLACKOUT_START = "21:45"
ROLLOVER_BLACKOUT_END = "22:30"

# ==========================================
# HIGH-IMPACT NEWS FILTER
# ==========================================
NEWS_FILTER_ENABLED = True
NEWS_PRE_BUFFER_MINS = 30
NEWS_POST_BUFFER_MINS = 30

# ==========================================
# WEEKEND GAP PROTECTION (FRIDAY CLOSE)
# ==========================================
FRIDAY_AUTO_CLOSE_ENABLED = True
FRIDAY_CUTOFF_HOUR_UTC = 20

# ==========================================
# HEARTBEAT & DAILY REPORT
# ==========================================
HEARTBEAT_INTERVAL_MINUTES = 60
DAILY_REPORT_HOUR_UTC = 20

# ==========================================
# ENGINE INTERNALS
# ==========================================
MAGIC_NUMBER = 112233
DEVIATION_POINTS = 20
SLEEP_INTERVAL_SECONDS = 5
