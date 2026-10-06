import os
from dotenv import load_dotenv

# Load environment variables from .env (root or local)
root_env = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(root_env):
    load_dotenv(root_env)
else:
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
SYMBOL = os.getenv("TRADING_SYMBOL", "BTCUSDm")
USE_MULTI_PAIR_BASKET = True  # Scans major pairs and picks the best setup
# Curated High-Expectancy Liquid Pairs with Proven Positive Edge (BTC, ETH, SOL, XRP, USDJPY, GBPUSD)
# Negative-edge symbols (EURUSDm PF:0.84, AUDUSDm PF:0.52) are strictly excluded.
SYMBOLS_BASKET = ["BTCUSDm", "ETHUSDm", "SOLUSDm", "XRPUSDm", "USDJPYm", "GBPUSDm"]
NEGATIVE_EDGE_SYMBOLS = ["EURUSDm", "AUDUSDm"]

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
Z_SCORE_PULLBACK_MAX = 2.8        # Blow-off top shield (protects against 3-sigma extremes)

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
MIN_VOLUME_SURGE_RATIO = 0.70

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
PARTIAL_TP_PIPS = 8.0
PARTIAL_CLOSE_RATIO = 0.50

# ==========================================
# POST-EXIT COOLDOWN (2 CANDLES = 10 MINS)
# ==========================================
SAME_SYMBOL_COOLDOWN_MINUTES = 10     # 2 completed M5 candles before re-entering same symbol
MIDDAY_LULL_FILTER_ENABLED = True      # Pause Forex between 11:30 and 13:00 UTC (Bank Lunch)

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
INTRADAY_PROFIT_LOCK_PCT = 0.10        # Trailing profit lock triggers at +10% of starting balance
INTRADAY_PROFIT_GIVEBACK_RATIO = 0.50  # Halt if 50% of peak profit is given back

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

BREAKEVEN_TRIGGER_PIPS = 5.0
BREAKEVEN_OFFSET_PIPS = 1.0
TRAILING_STOP_ENABLED = True
TRAILING_DISTANCE_PIPS = 10.0
TRAILING_STEP_PIPS = 2.5

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

def validate_config():
    """Validates runtime configuration constraints on startup."""
    assert 0 < KELLY_FRACTION <= 1.0, f"KELLY_FRACTION must be in (0, 1.0], got {KELLY_FRACTION}"
    assert MAX_OPEN_POSITIONS >= 1, f"MAX_OPEN_POSITIONS must be >= 1, got {MAX_OPEN_POSITIONS}"
    assert MAX_DAILY_LOSS_USD > 0, f"MAX_DAILY_LOSS_USD must be > 0, got {MAX_DAILY_LOSS_USD}"
    assert BASE_LOT_SIZE > 0, f"BASE_LOT_SIZE must be > 0, got {BASE_LOT_SIZE}"
    assert len(SYMBOLS_BASKET) > 0, "SYMBOLS_BASKET cannot be empty"
    overlap = set(SYMBOLS_BASKET).intersection(set(NEGATIVE_EDGE_SYMBOLS))
    assert not overlap, f"SYMBOLS_BASKET contains blacklisted negative-edge symbols: {overlap}"

validate_config()
