"""
Gold (XAUUSDm) Institutional Scalper Strategy
Specialized high-probability scalping engine built specifically for Gold.
Incorporates:
- Session Liquidity Windows (London 07:00 UTC to NY 18:00 UTC)
- Fast EMA 9/21 Dynamic Value Pullbacks
- Institutional Wick Absorption (Buyer/Seller Defence)
- Fractal Choppiness Guard (CHOP < 58.0)
- Statistical Z-Score Overextension Floor
- Session Anchored VWAP (Volume-Weighted Average Price)
"""

from datetime import datetime, timezone
from typing import Dict, Any, Tuple, List, Optional
import numpy as np
import pandas as pd
from gold_scalper import config_gold


class GoldScalperStrategy:
    """
    High-Precision Scalper Strategy for Gold (XAUUSDm).
    """

    def __init__(self):
        self.ema_fast = config_gold.EMA_FAST
        self.ema_slow = config_gold.EMA_SLOW
        self.ema_trend = config_gold.EMA_TREND
        self.atr_period = config_gold.ATR_PERIOD
        self.chop_max = config_gold.MAX_CHOP_INDEX
        self.adx_min = config_gold.MIN_ADX_THRESHOLD
        self.z_max = config_gold.Z_SCORE_PULLBACK_MAX

    def calculate_indicators(self, rates_data) -> pd.DataFrame:
        """Calculates moving averages, RSI, ATR, ADX, CHOP, Z-score, and VWAP."""
        if rates_data is None or len(rates_data) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(rates_data)
        if df.empty or len(df) < self.ema_trend + 5:
            return df

        df["time_dt"] = pd.to_datetime(df["time"], unit="s", utc=True)
        high = df["high"]
        low = df["low"]
        close = df["close"]
        vol = df["tick_volume"] if "tick_volume" in df else pd.Series(100.0, index=df.index)

        # EMAs
        df["ema_fast"] = close.ewm(span=self.ema_fast, adjust=False).mean()
        df["ema_slow"] = close.ewm(span=self.ema_slow, adjust=False).mean()
        df["ema_trend"] = close.ewm(span=self.ema_trend, adjust=False).mean()

        # ATR (14)
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=self.atr_period).mean()

        # RSI (14)
        delta = close.diff()
        gain = delta.where(delta > 0, 0).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1 / 14, adjust=False).mean()
        rs = gain / (loss + 1e-9)
        df["rsi"] = 100 - (100 / (1 + rs))

        # ADX (14)
        up_move = high - high.shift()
        down_move = low.shift() - low
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        tr_smooth = tr.ewm(alpha=1 / 14, adjust=False).mean()
        plus_di = 100 * (pd.Series(plus_dm).ewm(alpha=1 / 14, adjust=False).mean() / (tr_smooth + 1e-9))
        minus_di = 100 * (pd.Series(minus_dm).ewm(alpha=1 / 14, adjust=False).mean() / (tr_smooth + 1e-9))
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9))
        df["adx"] = dx.ewm(alpha=1 / 14, adjust=False).mean()

        # Fractal Choppiness Index (14)
        atr_sum = tr.rolling(14).sum()
        high_max = high.rolling(14).max()
        low_min = low.rolling(14).min()
        price_range = (high_max - low_min) + 1e-9
        safe_ratio = np.where(atr_sum > 1e-9, atr_sum / price_range, 14.0 ** 0.5)
        safe_ratio = np.maximum(safe_ratio, 1e-9)
        df["chop"] = pd.Series(100.0 * np.log10(safe_ratio) / np.log10(14), index=df.index).fillna(50.0)

        # Z-Score (50-period)
        mean_50 = close.rolling(50).mean()
        std_50 = close.rolling(50).std()
        df["z_score"] = (close - mean_50) / (std_50 + 1e-9)

        # Intraday VWAP (anchored daily)
        typical_price = (high + low + close) / 3.0
        pv = typical_price * vol
        dates = df["time_dt"].dt.date
        df["vwap"] = pv.groupby(dates).cumsum() / (vol.groupby(dates).cumsum() + 1e-9)

        return df

    def analyze_h1_macro(self, h1_rates: Optional[Any] = None) -> str:
        """Determines macro trend regime on Gold H1 candles."""
        if h1_rates is None or len(h1_rates) < 21:
            return "NEUTRAL"
        df_h1 = pd.DataFrame(h1_rates)
        close = df_h1["close"]
        ema9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
        ema21 = close.ewm(span=21, adjust=False).mean().iloc[-1]
        c = close.iloc[-1]
        if ema9 > ema21 and c > ema21:
            return "BULLISH"
        elif ema9 < ema21 and c < ema21:
            return "BEARISH"
        return "NEUTRAL"

    def analyze_m1_microstructure(self, m1_rates: Optional[Any] = None) -> Dict[str, Any]:
        """
        Analyzes the latest M1 micro-candles to confirm reversal execution timing.
        Ensures the bot does not sell into an active green candle surge or buy into a falling knife.
        """
        if m1_rates is None or len(m1_rates) < 2:
            return {"bullish_confirmed": True, "bearish_confirmed": True, "reason": "M1 data omitted (default pass)"}

        df_m1 = pd.DataFrame(m1_rates)
        curr = df_m1.iloc[-1]

        c = curr["close"]
        o = curr["open"]
        h = curr["high"]
        l = curr["low"]
        rng = h - l + 1e-9

        lower_wick = (min(o, c) - l) / rng
        upper_wick = (h - max(o, c)) / rng

        # Bullish M1 Reversal Confirmation:
        # Candle is green (close > open) OR has significant lower wick absorption (>= 25%)
        bullish = bool((c > o) or (lower_wick >= 0.25))

        # Bearish M1 Reversal Confirmation:
        # Candle is red (close < open) OR has significant upper wick rejection (>= 25%)
        bearish = bool((c < o) or (upper_wick >= 0.25))

        return {
            "bullish_confirmed": bullish,
            "bearish_confirmed": bearish,
            "reason": f"M1: Bull={bullish} (c={c:.2f}, o={o:.2f}, low_wick={lower_wick*100:.0f}%), Bear={bearish} (upper_wick={upper_wick*100:.0f}%)"
        }

    def analyze(self, m5_rates: List[Dict[str, Any]], h1_rates: Optional[List[Dict[str, Any]]] = None, m1_rates: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """
        Executes institutional scalping analysis on Gold with M1 microstructure confirmation.
        """
        df = self.calculate_indicators(m5_rates)
        if df.empty or len(df) < self.ema_trend + 5:
            return {
                "signal": "HOLD",
                "confidence": 0.0,
                "reason": "Insufficient candles to compute indicators",
                "metrics": {}
            }

        curr = df.iloc[-1]
        prev = df.iloc[-2]
        now_utc = datetime.now(timezone.utc)

        close = curr["close"]
        open_price = curr["open"]
        high = curr["high"]
        low = curr["low"]
        ema_f = curr["ema_fast"]
        ema_s = curr["ema_slow"]
        ema_t = curr["ema_trend"]
        rsi_val = curr["rsi"]
        atr_val = curr["atr"] if not np.isnan(curr["atr"]) else 2.50
        adx_val = curr["adx"] if not np.isnan(curr["adx"]) else 20.0
        chop_val = curr["chop"] if not np.isnan(curr["chop"]) else 50.0
        z_score = curr["z_score"] if not np.isnan(curr["z_score"]) else 0.0
        vwap_val = curr["vwap"] if not np.isnan(curr["vwap"]) else close

        # Rejection wicks
        c_range = high - low
        if c_range > 0:
            lower_wick = min(open_price, close) - low
            upper_wick = high - max(open_price, close)
            lower_wick_ratio = lower_wick / c_range
            upper_wick_ratio = upper_wick / c_range
        else:
            lower_wick_ratio = 0.0
            upper_wick_ratio = 0.0

        h1_trend = self.analyze_h1_macro(h1_rates)

        metrics = {
            "symbol": "XAUUSDm",
            "close": round(close, 3),
            "ema_fast": round(ema_f, 3),
            "ema_slow": round(ema_s, 3),
            "ema_trend": round(ema_t, 3),
            "rsi": round(rsi_val, 1),
            "atr": round(atr_val, 3),
            "adx": round(adx_val, 1),
            "chop": round(chop_val, 1),
            "z_score": round(z_score, 2),
            "vwap": round(vwap_val, 3),
            "lower_wick_pct": round(lower_wick_ratio * 100, 1),
            "upper_wick_pct": round(upper_wick_ratio * 100, 1),
            "h1_trend": h1_trend,
            "utc_hour": now_utc.hour
        }

        # -------------------------------------------------------------
        # 1. SESSION FILTER: Gold should trade during active hours (07:00 - 18:00 UTC)
        # -------------------------------------------------------------
        if config_gold.AVOID_ASIAN_SESSION:
            hour = now_utc.hour
            if hour < config_gold.SESSION_START_HOUR_UTC or hour >= config_gold.SESSION_END_HOUR_UTC:
                return {
                    "signal": "HOLD",
                    "confidence": 0.0,
                    "reason": f"Session Guard: Outside active Gold trading hours ({config_gold.SESSION_START_HOUR_UTC:02d}:00 - {config_gold.SESSION_END_HOUR_UTC:02d}:00 UTC). Current: {hour:02d}:{now_utc.minute:02d} UTC.",
                    "metrics": metrics
                }

        # -------------------------------------------------------------
        # 2. CHOPPINESS GUARD: Block random consolidation (CHOP > 58.0)
        # -------------------------------------------------------------
        if chop_val > self.chop_max:
            return {
                "signal": "HOLD",
                "confidence": 0.0,
                "reason": f"Chop Guard: Gold in flat consolidation (CHOP {chop_val:.1f} > {self.chop_max}).",
                "metrics": metrics
            }

        # -------------------------------------------------------------
        # 3. Z-SCORE OVEREXTENSION GUARD: Don't buy the absolute peak / sell the floor
        # -------------------------------------------------------------
        if abs(z_score) > self.z_max:
            return {
                "signal": "HOLD",
                "confidence": 0.0,
                "reason": f"Z-Score Guard: Price overextended from mean (Z = {z_score:+.2f}).",
                "metrics": metrics
            }

        # -------------------------------------------------------------
        # 4. ADX TREND STRENGTH FLOOR
        # -------------------------------------------------------------
        if adx_val < self.adx_min:
            return {
                "signal": "HOLD",
                "confidence": 0.0,
                "reason": f"ADX Guard: Trend momentum too weak ({adx_val:.1f} < {self.adx_min}).",
                "metrics": metrics
            }

        # -------------------------------------------------------------
        # BUY SCALP CONFLUENCE EVALUATION
        # -------------------------------------------------------------
        m5_bullish = (ema_f > ema_s) and (close >= ema_t * 0.9995)
        # Pullback into value: price touched or approached EMA slow, now bouncing
        pullback_touched_value = (low <= ema_f * 1.0005) or (low <= ema_s * 1.0008)
        rsi_rebound = (rsi_val >= 48.0) and (rsi_val > prev["rsi"])
        buyer_absorption_wick = (lower_wick_ratio >= 0.20) or (close >= open_price)

        if m5_bullish and pullback_touched_value and rsi_rebound and buyer_absorption_wick:
            if h1_trend == "BEARISH":
                return {
                    "signal": "HOLD",
                    "confidence": 0.0,
                    "reason": "Gold Buy suppressed: H1 Macro trend is BEARISH.",
                    "metrics": metrics
                }

            # M1 Microstructure Reversal Timing Guard
            m1_state = self.analyze_m1_microstructure(m1_rates)
            if not m1_state.get("bullish_confirmed", True):
                return {
                    "signal": "HOLD",
                    "confidence": 0.0,
                    "reason": f"M1 Micro Guard: Waiting for M1 bullish reversal candle ({m1_state.get('reason', '')}).",
                    "metrics": metrics
                }

            # Score confluence
            score = 70
            if h1_trend == "BULLISH": score += 10
            if chop_val <= 45.0: score += 10
            if lower_wick_ratio >= 0.25: score += 5
            if close <= (vwap_val * 1.0008): score += 5  # Buying near/below institutional VWAP

            return {
                "signal": "BUY",
                "confidence": round(min(score, 100) / 100.0, 4),
                "reason": f"Gold Scalp BUY: H1={h1_trend}, M5 Bullish, EMA 9/21 pullback bounced, M1 Confirmed, CHOP={chop_val:.1f}.",
                "metrics": metrics
            }

        # -------------------------------------------------------------
        # SELL SCALP CONFLUENCE EVALUATION
        # -------------------------------------------------------------
        m5_bearish = (ema_f < ema_s) and (close <= ema_t * 1.0005)
        pullback_rally_value = (high >= ema_f * 0.9995) or (high >= ema_s * 0.9992)
        rsi_drop = (rsi_val <= 52.0) and (rsi_val < prev["rsi"])
        seller_absorption_wick = (upper_wick_ratio >= 0.20) or (close <= open_price)

        if m5_bearish and pullback_rally_value and rsi_drop and seller_absorption_wick:
            if h1_trend == "BULLISH":
                return {
                    "signal": "HOLD",
                    "confidence": 0.0,
                    "reason": "Gold Sell suppressed: H1 Macro trend is BULLISH.",
                    "metrics": metrics
                }

            # M1 Microstructure Reversal Timing Guard
            m1_state = self.analyze_m1_microstructure(m1_rates)
            if not m1_state.get("bearish_confirmed", True):
                return {
                    "signal": "HOLD",
                    "confidence": 0.0,
                    "reason": f"M1 Micro Guard: Waiting for M1 bearish reversal candle ({m1_state.get('reason', '')}).",
                    "metrics": metrics
                }

            score = 70
            if h1_trend == "BEARISH": score += 10
            if chop_val <= 45.0: score += 10
            if upper_wick_ratio >= 0.25: score += 5
            if close >= (vwap_val * 0.9992): score += 5  # Selling near/above institutional VWAP

            return {
                "signal": "SELL",
                "confidence": round(min(score, 100) / 100.0, 4),
                "reason": f"Gold Scalp SELL: H1={h1_trend}, M5 Bearish, EMA 9/21 rally rejected, M1 Confirmed, CHOP={chop_val:.1f}.",
                "metrics": metrics
            }

        return {
            "signal": "HOLD",
            "confidence": 0.0,
            "reason": f"Gold scanning. M5={'BULLISH' if m5_bullish else ('BEARISH' if m5_bearish else 'NEUTRAL')} | H1={h1_trend} | CHOP={chop_val:.1f} | Waiting for dynamic EMA 9/21 pullback.",
            "metrics": metrics
        }
