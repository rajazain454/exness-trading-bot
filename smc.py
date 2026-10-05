import logging
import pandas as pd
from typing import Dict, Any, Tuple, Optional
import MetaTrader5 as mt5
import config

logger = logging.getLogger("SMCEngine")

class SmartMoneyConcepts:
    """
    Market Structure & Smart Money Concepts (SMC) Engine:
    - Previous Day High (PDH) & Previous Day Low (PDL)
    - Daily Pivot Points (PP, R1, S1)
    - Resistance & Support Trap Avoidance
    - Fair Value Gap (FVG) / Imbalance Detection
    """

    def __init__(self, connector):
        self.connector = connector
        self.daily_levels_cache: Dict[str, Dict[str, float]] = {}

    def get_daily_levels(self, symbol: str) -> Dict[str, float]:
        """Calculates Previous Day High, Low, Pivot, R1, and S1."""
        d1_rates = self.connector.get_rates(symbol, "D1", count=4)
        if d1_rates is None or len(d1_rates) < 2:
            return {}

        df_d1 = pd.DataFrame(d1_rates)
        # Completed previous day is index -2
        prev_day = df_d1.iloc[-2]
        high_d = prev_day["high"]
        low_d = prev_day["low"]
        close_d = prev_day["close"]

        pivot = (high_d + low_d + close_d) / 3.0
        r1 = (2 * pivot) - low_d
        s1 = (2 * pivot) - high_d

        levels = {
            "pdh": round(high_d, 5),
            "pdl": round(low_d, 5),
            "pivot": round(pivot, 5),
            "r1": round(r1, 5),
            "s1": round(s1, 5)
        }
        self.daily_levels_cache[symbol] = levels
        return levels

    def check_structure_trap(self, symbol: str, signal: str, current_price: float) -> Tuple[bool, str]:
        """
        Validates that trade is not entering directly into a major resistance or support wall.
        BUY: Avoid buying within proximity pips of PDH or R1.
        SELL: Avoid selling within proximity pips of PDL or S1.
        """
        if not config.SMC_FILTER_ENABLED:
            return True, "SMC filter disabled"

        levels = self.get_daily_levels(symbol)
        if not levels:
            return True, "Daily levels unavailable"

        is_crypto = any(c in symbol.upper() for c in ["BTC", "ETH", "SOL", "XRP"])
        pip_size = self.connector.get_pip_size(symbol)
        proximity_dist = (current_price * 0.0005) if is_crypto else (config.KEY_LEVEL_PROXIMITY_PIPS * pip_size)

        if signal == "BUY":
            # Check proximity to PDH or R1
            for level_name, level_price in [("Previous Day High (PDH)", levels["pdh"]), ("Daily R1", levels["r1"])]:
                if 0 <= (level_price - current_price) <= proximity_dist:
                    dist_units = (level_price - current_price) / (1.0 if is_crypto else pip_size)
                    unit_label = "$" if is_crypto else "pips"
                    return False, f"SMC Trap: BUY suppressed directly below {level_name} ({dist_units:.1f} {unit_label} away). Resistance ceiling risk."

        elif signal == "SELL":
            # Check proximity to PDL or S1
            for level_name, level_price in [("Previous Day Low (PDL)", levels["pdl"]), ("Daily S1", levels["s1"])]:
                if 0 <= (current_price - level_price) <= proximity_dist:
                    dist_units = (current_price - level_price) / (1.0 if is_crypto else pip_size)
                    unit_label = "$" if is_crypto else "pips"
                    return False, f"SMC Trap: SELL suppressed directly above {level_name} ({dist_units:.1f} {unit_label} away). Support floor bounce risk."

        return True, "Structure clear"

    def detect_recent_fvg(self, m5_df: pd.DataFrame) -> Tuple[bool, str]:
        """
        Detects recent Fair Value Gaps (FVG) / Imbalances in the last 15 M5 candles.
        Bullish FVG: Candle[i-2] High < Candle[i] Low
        Bearish FVG: Candle[i-2] Low > Candle[i] High
        """
        if not config.FAIR_VALUE_GAP_ENABLED or m5_df.empty or len(m5_df) < 5:
            return False, "NONE"

        # Inspect last 10 candles for active imbalance
        for i in range(len(m5_df) - 1, max(len(m5_df) - 10, 2), -1):
            c_current = m5_df.iloc[i]
            c_two_back = m5_df.iloc[i - 2]

            # Bullish FVG
            if c_current["low"] > c_two_back["high"]:
                gap_size = c_current["low"] - c_two_back["high"]
                if gap_size > 0:
                    return True, "BULLISH_FVG"

            # Bearish FVG
            if c_two_back["low"] > c_current["high"]:
                gap_size = c_two_back["low"] - c_current["high"]
                if gap_size > 0:
                    return True, "BEARISH_FVG"

        return False, "NONE"
