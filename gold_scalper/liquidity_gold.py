"""
Institutional Gold (XAUUSDm) Liquidity & Market Structure Engine
Calculates institutional reference levels and detects Smart Money Concepts (SMC):
- Asian Session Range (00:00 - 06:00 UTC)
- Previous Day High & Low (PDH / PDL)
- Fractal Swing Highs & Lows
- Liquidity Sweeps (Stop Hunts beyond session extremes & swing points)
- Market Structure Shifts (MSS / Change of Character) with displacement
- 3-Candle Fair Value Gaps (FVG) & mitigation tracking
"""

from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import pandas as pd


class GoldLiquidityEngine:
    """
    Precision SMC Liquidity and Market Structure Analyzer for Gold.
    """

    def __init__(self, sweep_min_usd: float = 0.20, min_rejection_wick: float = 0.20):
        self.sweep_min_usd = sweep_min_usd
        self.min_rejection_wick = min_rejection_wick

    def compute_session_levels(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Extracts key institutional liquidity pools:
        - Asian Range High & Low (00:00 to 06:00 UTC)
        - Previous Day High (PDH) & Previous Day Low (PDL)
        - Today's Open Price (00:00 UTC)
        """
        if df.empty or len(df) < 15:
            return {
                "asian_high": 0.0,
                "asian_low": 0.0,
                "pdh": 0.0,
                "pdl": 0.0,
                "today_open": 0.0
            }

        # Ensure datetime column
        if "dt" not in df.columns:
            df["dt"] = pd.to_datetime(df["time"], unit="s", utc=True)

        latest_dt = df["dt"].iloc[-1]
        today_date = latest_dt.date()

        # Today's bars
        today_mask = df["dt"].dt.date == today_date
        today_bars = df[today_mask]

        today_open = float(today_bars["open"].iloc[0]) if not today_bars.empty else float(df["open"].iloc[-1])

        # Asian Range: 00:00 UTC to 06:00 UTC
        asian_mask = (df["dt"].dt.date == today_date) & (df["dt"].dt.hour >= 0) & (df["dt"].dt.hour < 6)
        asian_bars = df[asian_mask]

        if not asian_bars.empty:
            asian_high = float(asian_bars["high"].max())
            asian_low = float(asian_bars["low"].min())
        else:
            # Fallback to earliest 12 bars today
            asian_high = float(today_bars["high"].head(12).max()) if not today_bars.empty else float(df["high"].iloc[-1])
            asian_low = float(today_bars["low"].head(12).min()) if not today_bars.empty else float(df["low"].iloc[-1])

        # Previous Day High / Low
        prev_day_mask = df["dt"].dt.date < today_date
        prev_bars = df[prev_day_mask]
        if not prev_bars.empty:
            prev_date = prev_bars["dt"].dt.date.iloc[-1]
            last_day_bars = df[df["dt"].dt.date == prev_date]
            pdh = float(last_day_bars["high"].max())
            pdl = float(last_day_bars["low"].min())
        else:
            # Fallback
            pdh = float(df["high"].iloc[:-20].max()) if len(df) > 30 else asian_high
            pdl = float(df["low"].iloc[:-20].min()) if len(df) > 30 else asian_low

        return {
            "asian_high": round(asian_high, 3),
            "asian_low": round(asian_low, 3),
            "pdh": round(pdh, 3),
            "pdl": round(pdl, 3),
            "today_open": round(today_open, 3)
        }

    def detect_swing_points(self, high: np.ndarray, low: np.ndarray, window: int = 2) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Detects fractal swing highs and swing lows using a rolling window.
        A swing high at bar i requires High[i] > High[i-window:i] and High[i] > High[i+1:i+window+1].
        """
        n = len(high)
        swing_highs = []
        swing_lows = []

        if n < (window * 2 + 1):
            return swing_highs, swing_lows

        for i in range(window, n - window):
            # Swing High: strictly higher than immediate neighbors and >= all bars in window
            if high[i] > high[i - 1] and high[i] > high[i + 1] and high[i] == np.max(high[i - window : i + window + 1]):
                swing_highs.append({"index": i, "price": float(high[i])})

            # Swing Low: strictly lower than immediate neighbors and <= all bars in window
            if low[i] < low[i - 1] and low[i] < low[i + 1] and low[i] == np.min(low[i - window : i + window + 1]):
                swing_lows.append({"index": i, "price": float(low[i])})

        return swing_highs, swing_lows

    def detect_liquidity_sweep(
        self,
        df: pd.DataFrame,
        levels: Dict[str, float],
        lookback: int = 5
    ) -> Dict[str, Any]:
        """
        Checks if a key liquidity pool (Asian High/Low, PDH/PDL, recent swing) was swept.
        A bullish sweep occurs when Low spikes below a key support level by >= sweep_min_usd,
        and price closes back above the level with an absorption lower wick.
        """
        if df.empty or len(df) < 1:
            return {"swept": False, "type": "NONE", "level_name": "", "level_price": 0.0, "reason": ""}

        recent = df.iloc[-lookback:]
        asian_high = levels.get("asian_high", 0.0)
        asian_low = levels.get("asian_low", 0.0)
        pdh = levels.get("pdh", 0.0)
        pdl = levels.get("pdl", 0.0)

        # Check latest completed / active candles for Bullish Sweep (Sell-side liquidity hunted)
        for idx in range(len(recent) - 1, -1, -1):
            bar = recent.iloc[idx]
            h = bar["high"]
            l = bar["low"]
            c = bar["close"]
            o = bar["open"]
            rng = h - l + 1e-9
            lower_wick = (min(o, c) - l) / rng

            # 1. Asian Low Sweep
            if asian_low > 0 and (asian_low - l) >= self.sweep_min_usd and c >= (asian_low - 0.10):
                if lower_wick >= self.min_rejection_wick or c > o:
                    return {
                        "swept": True,
                        "type": "BULLISH_SWEEP",
                        "level_name": "Asian Low",
                        "level_price": asian_low,
                        "sweep_depth": round(asian_low - l, 2),
                        "wick_ratio": round(lower_wick, 2),
                        "reason": f"Swept Asian Low (${asian_low:.2f}) by ${asian_low - l:.2f} and absorbed back inside."
                    }

            # 2. PDL (Previous Day Low) Sweep
            if pdl > 0 and (pdl - l) >= self.sweep_min_usd and c >= (pdl - 0.10):
                if lower_wick >= self.min_rejection_wick or c > o:
                    return {
                        "swept": True,
                        "type": "BULLISH_SWEEP",
                        "level_name": "PDL",
                        "level_price": pdl,
                        "sweep_depth": round(pdl - l, 2),
                        "wick_ratio": round(lower_wick, 2),
                        "reason": f"Swept PDL (${pdl:.2f}) by ${pdl - l:.2f} with strong buyer absorption."
                    }

            # Check for Bearish Sweep (Buy-side liquidity hunted above highs)
            upper_wick = (h - max(o, c)) / rng

            # 3. Asian High Sweep
            if asian_high > 0 and (h - asian_high) >= self.sweep_min_usd and c <= (asian_high + 0.10):
                if upper_wick >= self.min_rejection_wick or c < o:
                    return {
                        "swept": True,
                        "type": "BEARISH_SWEEP",
                        "level_name": "Asian High",
                        "level_price": asian_high,
                        "sweep_depth": round(h - asian_high, 2),
                        "wick_ratio": round(upper_wick, 2),
                        "reason": f"Swept Asian High (${asian_high:.2f}) by ${h - asian_high:.2f} and rejected back inside."
                    }

            # 4. PDH (Previous Day High) Sweep
            if pdh > 0 and (h - pdh) >= self.sweep_min_usd and c <= (pdh + 0.10):
                if upper_wick >= self.min_rejection_wick or c < o:
                    return {
                        "swept": True,
                        "type": "BEARISH_SWEEP",
                        "level_name": "PDH",
                        "level_price": pdh,
                        "sweep_depth": round(h - pdh, 2),
                        "wick_ratio": round(upper_wick, 2),
                        "reason": f"Swept PDH (${pdh:.2f}) by ${h - pdh:.2f} with institutional seller rejection."
                    }

        return {"swept": False, "type": "NONE", "level_name": "", "level_price": 0.0, "reason": "No major level swept."}

    def detect_market_structure_shift(
        self,
        df: pd.DataFrame,
        lookback: int = 15
    ) -> Dict[str, Any]:
        """
        Detects Market Structure Shift (MSS / Change of Character):
        - Bullish MSS: Price breaks and closes above the most recent lower-high with body displacement.
        - Bearish MSS: Price breaks and closes below the most recent higher-low with body displacement.
        """
        if df.empty or len(df) < lookback:
            return {"mss": False, "direction": "NONE", "pivot_price": 0.0, "reason": ""}

        high = df["high"].to_numpy()
        low = df["low"].to_numpy()
        close = df["close"].to_numpy()
        open_p = df["open"].to_numpy()

        swing_highs, swing_lows = self.detect_swing_points(high, low, window=2)

        curr_c = close[-1]
        curr_o = open_p[-1]
        body = abs(curr_c - curr_o)
        rng = high[-1] - low[-1] + 1e-9
        displacement = (body / rng) >= 0.50  # Strong body displacement candle

        # Check Bullish MSS: Close broke above recent swing high
        if swing_highs:
            recent_sh = swing_highs[-1]
            if curr_c > recent_sh["price"] and displacement and curr_c > curr_o:
                return {
                    "mss": True,
                    "direction": "BULLISH_MSS",
                    "pivot_price": recent_sh["price"],
                    "broken_at": curr_c,
                    "reason": f"Bullish MSS: Closed above swing high (${recent_sh['price']:.2f}) with {body/rng*100:.0f}% body displacement."
                }

        # Check Bearish MSS: Close broke below recent swing low
        if swing_lows:
            recent_sl = swing_lows[-1]
            if curr_c < recent_sl["price"] and displacement and curr_c < curr_o:
                return {
                    "mss": True,
                    "direction": "BEARISH_MSS",
                    "pivot_price": recent_sl["price"],
                    "broken_at": curr_c,
                    "reason": f"Bearish MSS: Closed below swing low (${recent_sl['price']:.2f}) with {body/rng*100:.0f}% body displacement."
                }

        return {"mss": False, "direction": "NONE", "pivot_price": 0.0, "reason": "No structural shift detected."}

    def detect_fair_value_gaps(
        self,
        df: pd.DataFrame,
        lookback: int = 15
    ) -> List[Dict[str, Any]]:
        """
        Detects 3-candle institutional liquidity imbalances (Fair Value Gaps):
        - Bullish FVG: Low of candle i > High of candle i-2. Gap zone = [High[i-2], Low[i]].
        - Bearish FVG: High of candle i < Low of candle i-2. Gap zone = [High[i], Low[i-2]].
        Also checks if the gap has already been mitigated by subsequent candles.
        """
        fvgs = []
        n = len(df)
        if n < 3:
            return fvgs

        start_idx = max(2, n - lookback)
        high = df["high"].to_numpy()
        low = df["low"].to_numpy()
        close = df["close"].to_numpy()

        for i in range(start_idx, n):
            # Bullish FVG
            c1_high = high[i - 2]
            c3_low = low[i]
            if c3_low > c1_high:
                gap_size = c3_low - c1_high
                if gap_size >= 0.25:  # Minimum $0.25 institutional imbalance on Gold
                    # Check mitigation by subsequent candles
                    mitigated = False
                    if i + 1 < n:
                        subsequent_lows = low[i + 1 :]
                        if np.min(subsequent_lows) <= c1_high:
                            mitigated = True
                    if not mitigated:
                        fvgs.append({
                            "type": "BULLISH_FVG",
                            "top": round(c3_low, 3),
                            "bottom": round(c1_high, 3),
                            "gap_usd": round(gap_size, 2),
                            "candle_idx": i
                        })

            # Bearish FVG
            c1_low = low[i - 2]
            c3_high = high[i]
            if c3_high < c1_low:
                gap_size = c1_low - c3_high
                if gap_size >= 0.25:
                    mitigated = False
                    if i + 1 < n:
                        subsequent_highs = high[i + 1 :]
                        if np.max(subsequent_highs) >= c1_low:
                            mitigated = True
                    if not mitigated:
                        fvgs.append({
                            "type": "BEARISH_FVG",
                            "top": round(c1_low, 3),
                            "bottom": round(c3_high, 3),
                            "gap_usd": round(gap_size, 2),
                            "candle_idx": i
                        })

        return fvgs
