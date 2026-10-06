"""
Gold (XAUUSDm) Institutional Multi-Strategy AI Engine
Executes an institutional, regime-switching multi-strategy stack for Gold:
1. Market Regime Classifier: TRENDING, RANGING, or BREAKOUT
2. Specialized Strategy Engines:
   - 🥇 Setup 1: Liquidity Sweep + Market Structure Shift (MSS) (Reversals)
   - 🥈 Setup 2: Trend Pullback + Continuation (EMA 9/21/50, ADX >= 20)
   - 🥉 Setup 3: Breakout + Retest (Session Range / Key Levels)
   - 🔥 Setup 4: Fair Value Gap (FVG) + Structure Alignment
   - ⚡ Setup 5: VWAP Range Mean Reversion (Ranging markets only)
3. 100-Point Confluence Scoring Engine (A+ >= 80 pts, A >= 75 pts, < 75 NO TRADE)
4. Strict "DO NOT TRADE" Gating System
"""

from datetime import datetime, timezone
from typing import Dict, Any, Tuple, List, Optional
import numpy as np
import pandas as pd
from gold_scalper import config_gold
from gold_scalper.liquidity_gold import GoldLiquidityEngine
from gold_scalper.ml_gold import GoldMLProbabilityEngine


class GoldScalperStrategy:
    """
    Institutional Multi-Strategy AI Scalper Engine for Gold (XAUUSDm).
    """

    def __init__(self):
        self.ema_fast = config_gold.EMA_FAST
        self.ema_slow = config_gold.EMA_SLOW
        self.ema_trend = config_gold.EMA_TREND
        self.atr_period = config_gold.ATR_PERIOD
        self.chop_max = config_gold.MAX_CHOP_INDEX
        self.adx_min = config_gold.MIN_ADX_THRESHOLD
        self.z_max = config_gold.Z_SCORE_PULLBACK_MAX
        self.min_wick_ratio = getattr(config_gold, "MIN_WICK_PERCENT", 15.0) / 100.0
        self.liquidity_engine = GoldLiquidityEngine(sweep_min_usd=0.20, min_rejection_wick=self.min_wick_ratio)
        self.min_confluence_threshold = 65  # Confluence threshold aligned with ML validation (Grade B+ baseline)
        self.ml_engine = GoldMLProbabilityEngine(
            min_p_win=0.55,
            min_ev_r=0.15,
            sl_mult=config_gold.ATR_SL_MULTIPLIER,
            tp_mult=config_gold.ATR_TP_MULTIPLIER
        )

    def calculate_indicators(self, rates_data: Any) -> pd.DataFrame:
        """Calculates moving averages, RSI, ATR, ADX, CHOP, Z-score, VWAP, and Bollinger Bands."""
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
        df["atr"] = tr.rolling(window=self.atr_period).mean().bfill()

        # RSI (14)
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).ewm(alpha=1 / 14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / 14, adjust=False).mean()
        rs = gain / (loss + 1e-9)
        df["rsi"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)

        # ADX (14)
        up_move = high - high.shift()
        down_move = low.shift() - low
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        tr_smooth = tr.ewm(alpha=1 / 14, adjust=False).mean()
        plus_di = 100.0 * (pd.Series(plus_dm, index=df.index).ewm(alpha=1 / 14, adjust=False).mean() / (tr_smooth + 1e-9))
        minus_di = 100.0 * (pd.Series(minus_dm, index=df.index).ewm(alpha=1 / 14, adjust=False).mean() / (tr_smooth + 1e-9))
        dx = 100.0 * ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9))
        df["adx"] = dx.ewm(alpha=1 / 14, adjust=False).mean().fillna(20.0)

        # Fractal Choppiness Index (14)
        atr_sum = tr.rolling(14).sum()
        high_max = high.rolling(14).max()
        low_min = low.rolling(14).min()
        price_range = (high_max - low_min) + 1e-9
        safe_ratio = np.maximum(np.where(atr_sum > 1e-9, atr_sum / price_range, 14.0 ** 0.5), 1e-9)
        df["chop"] = pd.Series(100.0 * np.log10(safe_ratio) / np.log10(14), index=df.index).fillna(50.0)

        # Z-Score (50-period)
        mean_50 = close.rolling(50).mean()
        std_50 = close.rolling(50).std()
        df["z_score"] = ((close - mean_50) / (std_50 + 1e-9)).fillna(0.0)

        # Volume Moving Average (20-period)
        vol_period = getattr(config_gold, "VOLUME_MA_PERIOD", 20)
        df["vol_sma"] = vol.rolling(window=vol_period).mean().fillna(vol)
        df["vol_ratio"] = (vol / (df["vol_sma"] + 1e-9)).fillna(1.0)

        # Intraday VWAP (Anchored to 00:00 UTC)
        typical_price = (high + low + close) / 3.0
        pv = typical_price * vol
        dates = df["time_dt"].dt.date
        df["cum_pv"] = pv.groupby(dates).cumsum()
        df["cum_vol"] = vol.groupby(dates).cumsum() + 1e-9
        df["vwap"] = df["cum_pv"] / df["cum_vol"]

        # Bollinger Bands (20, 2.0 std) for Range Boundaries
        bb_mean = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        df["bb_upper"] = bb_mean + (bb_std * 2.0)
        df["bb_lower"] = bb_mean - (bb_std * 2.0)
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / (bb_mean + 1e-9)

        return df

    def classify_market_regime(self, curr: pd.Series, prev: pd.Series) -> str:
        """
        Classifies market regime into:
        - TRENDING_BULLISH / TRENDING_BEARISH
        - RANGING_CONSOLIDATION
        - BREAKOUT_EXPANSION
        """
        adx = float(curr.get("adx", 20.0))
        chop = float(curr.get("chop", 50.0))
        close = float(curr.get("close", 0.0))
        ema_f = float(curr.get("ema_fast", 0.0))
        ema_s = float(curr.get("ema_slow", 0.0))
        ema_t = float(curr.get("ema_trend", 0.0))
        vol_ratio = float(curr.get("vol_ratio", 1.0))
        atr = float(curr.get("atr", 2.0))
        body = abs(float(curr.get("close", 0.0)) - float(curr.get("open", 0.0)))

        # Breakout check: high volume expansion and wide body candle
        if vol_ratio >= 1.8 and body >= (atr * 1.2):
            return "BREAKOUT_EXPANSION"

        # Trending check: ADX >= 21, CHOP <= 50, EMAs in stacked alignment
        if adx >= 21.0 and chop <= 50.0:
            if close > ema_t and ema_f > ema_s:
                return "TRENDING_BULLISH"
            elif close < ema_t and ema_f < ema_s:
                return "TRENDING_BEARISH"

        # Ranging check: ADX < 20 or CHOP >= 52
        if adx < 20.0 or chop >= 52.0:
            return "RANGING_CONSOLIDATION"

        # Default fallback to trending or ranging based on EMA trend
        if close > ema_t:
            return "TRENDING_BULLISH"
        elif close < ema_t:
            return "TRENDING_BEARISH"
        return "RANGING_CONSOLIDATION"

    def analyze_h1_macro(self, h1_rates: Optional[List[Dict[str, Any]]]) -> str:
        """Determines macro H1 trend baseline (EMA 50 / 200)."""
        if h1_rates is None or len(h1_rates) < 55:
            return "UNKNOWN"
        df_h1 = pd.DataFrame(h1_rates)
        close = df_h1["close"]
        ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
        ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1] if len(close) >= 200 else ema50
        c = close.iloc[-1]
        if c > ema50 and c > ema200:
            return "BULLISH"
        elif c < ema50 and c < ema200:
            return "BEARISH"
        return "NEUTRAL"

    def analyze_m1_microstructure(self, m1_rates: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
        """
        Analyzes M1 candles for institutional Micro-Displacement and 5-Bar Micro-BOS.
        1. Micro-Displacement: Range >= 1.25x rolling M1 ATR(10) with body ratio >= 45%.
        2. Micro-BOS: Close breaks above prior 5 M1 bars' highest high (Bullish) or below lowest low (Bearish).
        """
        if m1_rates is None or len(m1_rates) < 8:
            return {
                "bullish_confirmed": True,
                "bearish_confirmed": True,
                "is_displaced": True,
                "micro_bos_bull": False,
                "micro_bos_bear": False,
                "disp_ratio": 1.0,
                "reason": "M1 omitted (default pass)"
            }

        df_m1 = pd.DataFrame(m1_rates)
        h = df_m1["high"].to_numpy()
        l = df_m1["low"].to_numpy()
        c = df_m1["close"].to_numpy()
        o = df_m1["open"].to_numpy()

        # True Range on M1
        tr1 = h[1:] - l[1:]
        tr2 = np.abs(h[1:] - c[:-1])
        tr3 = np.abs(l[1:] - c[:-1])
        tr = np.maximum(tr1, np.maximum(tr2, tr3))
        m1_atr = float(np.mean(tr[-10:])) if len(tr) >= 10 else float(np.mean(tr))
        m1_atr = max(m1_atr, 0.10)

        curr_c = c[-1]
        curr_o = o[-1]
        curr_h = h[-1]
        curr_l = l[-1]
        rng = curr_h - curr_l + 1e-9
        body = abs(curr_c - curr_o)
        body_ratio = body / rng
        lower_wick = (min(curr_o, curr_c) - curr_l) / rng
        upper_wick = (curr_h - max(curr_o, curr_c)) / rng

        # Prior 5 M1 bars
        lookback_bars = min(5, len(h) - 1)
        prior_5_high = float(np.max(h[-lookback_bars - 1 : -1]))
        prior_5_low = float(np.min(l[-lookback_bars - 1 : -1]))

        disp_ratio = round(rng / m1_atr, 2)
        is_displaced = bool((rng >= 1.25 * m1_atr) and (body_ratio >= 0.45))

        # Micro Break of Structure (BOS)
        micro_bos_bull = bool(curr_c > prior_5_high)
        micro_bos_bear = bool(curr_c < prior_5_low)

        # Bullish Confirmation: (Displacement + BOS + Green) OR (Absorption lower wick >= 25% + Green)
        bullish_confirmed = bool(
            (micro_bos_bull and curr_c > curr_o and body_ratio >= 0.40) or
            (is_displaced and curr_c > curr_o and lower_wick >= 0.20) or
            (curr_c > prior_5_high and lower_wick >= 0.25)
        )

        # Bearish Confirmation: (Displacement + BOS + Red) OR (Absorption upper wick >= 25% + Red)
        bearish_confirmed = bool(
            (micro_bos_bear and curr_c < curr_o and body_ratio >= 0.40) or
            (is_displaced and curr_c < curr_o and upper_wick >= 0.20) or
            (curr_c < prior_5_low and upper_wick >= 0.25)
        )

        return {
            "bullish_confirmed": bullish_confirmed,
            "bearish_confirmed": bearish_confirmed,
            "is_displaced": is_displaced,
            "micro_bos_bull": micro_bos_bull,
            "micro_bos_bear": micro_bos_bear,
            "disp_ratio": disp_ratio,
            "reason": f"M1: Disp={disp_ratio:.1f}x, BOS_Bull={micro_bos_bull}, BOS_Bear={micro_bos_bear}"
        }

    def analyze(
        self,
        m5_rates: List[Dict[str, Any]],
        h1_rates: Optional[List[Dict[str, Any]]] = None,
        m1_rates: Optional[List[Dict[str, Any]]] = None,
        spread_usd: float = 0.24
    ) -> Dict[str, Any]:
        """
        Executes Institutional Multi-Strategy Evaluation on Gold with 100-Point Confluence Scoring and ML Expectancy.
        """
        df = self.calculate_indicators(m5_rates)
        if df.empty or len(df) < self.ema_trend + 5:
            return {
                "signal": "HOLD",
                "confidence": 0.0,
                "setup": "NONE",
                "grade": "NONE",
                "regime": "UNKNOWN",
                "confluence_score": 0,
                "reason": "Insufficient candles to compute indicators",
                "metrics": {}
            }

        curr = df.iloc[-1]
        prev = df.iloc[-2]
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour

        # Base price metrics
        close = float(curr["close"])
        open_price = float(curr["open"])
        high = float(curr["high"])
        low = float(curr["low"])
        ema_f = float(curr["ema_fast"])
        ema_s = float(curr["ema_slow"])
        ema_t = float(curr["ema_trend"])
        rsi_val = float(curr["rsi"])
        atr_val = float(curr["atr"])
        adx_val = float(curr["adx"])
        chop_val = float(curr["chop"])
        z_score = float(curr["z_score"])
        vwap_val = float(curr["vwap"])
        vol_ratio = float(curr["vol_ratio"])
        bb_upper = float(curr["bb_upper"])
        bb_lower = float(curr["bb_lower"])

        c_range = high - low + 1e-9
        lower_wick_ratio = (min(open_price, close) - low) / c_range
        upper_wick_ratio = (high - max(open_price, close)) / c_range

        # Classify Market Regime
        regime = self.classify_market_regime(curr, prev)
        h1_trend = self.analyze_h1_macro(h1_rates)

        # Compute SMC Session Levels
        session_levels = self.liquidity_engine.compute_session_levels(df)
        sweep_data = self.liquidity_engine.detect_liquidity_sweep(df, session_levels, lookback=5)
        mss_data = self.liquidity_engine.detect_market_structure_shift(df, lookback=15)
        fvgs = self.liquidity_engine.detect_fair_value_gaps(df, lookback=10)
        m1_timing = self.analyze_m1_microstructure(m1_rates)

        metrics = {
            "symbol": "XAUUSDm",
            "close": round(close, 3),
            "regime": regime,
            "ema_fast": round(ema_f, 3),
            "ema_slow": round(ema_s, 3),
            "ema_trend": round(ema_t, 3),
            "rsi": round(rsi_val, 1),
            "atr": round(atr_val, 3),
            "adx": round(adx_val, 1),
            "chop": round(chop_val, 1),
            "z_score": round(z_score, 2),
            "vwap": round(vwap_val, 3),
            "vol_ratio": round(vol_ratio, 2),
            "lower_wick_pct": round(lower_wick_ratio * 100, 1),
            "upper_wick_pct": round(upper_wick_ratio * 100, 1),
            "h1_trend": h1_trend,
            "levels": session_levels,
            "sweep": sweep_data,
            "mss": mss_data
        }

        # -------------------------------------------------------------
        # STRICT "DO NOT TRADE" SAFETY GATES
        # -------------------------------------------------------------
        # Gate 1: Dual-Wave Institutional Liquidity Session Gate
        if config_gold.AVOID_ASIAN_SESSION:
            dec_hour = hour + (now_utc.minute / 60.0)
            w1_start = getattr(config_gold, "WAVE_1_START_HOUR_UTC", 8.0)
            w1_end = getattr(config_gold, "WAVE_1_END_HOUR_UTC", 11.5)
            w2_start = getattr(config_gold, "WAVE_2_START_HOUR_UTC", 13.0)
            w2_end = getattr(config_gold, "WAVE_2_END_HOUR_UTC", 17.0)
            avoid_lull = getattr(config_gold, "AVOID_MIDDAY_LULL", True)

            if avoid_lull and (w1_end <= dec_hour < w2_start):
                return {
                    "signal": "HOLD",
                    "confidence": 0.0,
                    "setup": "DO_NOT_TRADE_MIDDAY_LULL",
                    "grade": "NONE",
                    "regime": regime,
                    "confluence_score": 0,
                    "reason": f"Midday Lull Gate: Bank lunch pause ({w1_end:04.1f} - {w2_start:04.1f} UTC) avoids dead chop.",
                    "metrics": metrics
                }
            elif not ((w1_start <= dec_hour < w1_end) or (w2_start <= dec_hour < w2_end)):
                return {
                    "signal": "HOLD",
                    "confidence": 0.0,
                    "setup": "DO_NOT_TRADE_SESSION",
                    "grade": "NONE",
                    "regime": regime,
                    "confluence_score": 0,
                    "reason": f"Session Gate: Outside active London/NY waves (08:00-11:30 or 13:00-17:00 UTC).",
                    "metrics": metrics
                }

        # Gate 2: Extreme Choppiness Gate (CHOP > 62.0)
        if chop_val > 62.0:
            return {
                "signal": "HOLD",
                "confidence": 0.0,
                "setup": "DO_NOT_TRADE_CHOP",
                "grade": "NONE",
                "regime": regime,
                "confluence_score": 0,
                "reason": f"Chop Gate: Gold in extreme flat compression (CHOP {chop_val:.1f} > 62.0).",
                "metrics": metrics
            }

        # -------------------------------------------------------------
        # 100-POINT CONFLUENCE SCORING ENGINE
        # -------------------------------------------------------------
        buy_score = 0
        sell_score = 0
        score_breakdown: Dict[str, Any] = {}
        detected_setup = "NONE"

        # --- 1. LIQUIDITY SWEEP EVALUATION (Max 35 pts) ---
        sweep_pts_buy = 0
        sweep_pts_sell = 0
        if sweep_data.get("swept"):
            if sweep_data.get("type") == "BULLISH_SWEEP":
                sweep_pts_buy = 35
                detected_setup = "SETUP_1_SWEEP_MSS"
            elif sweep_data.get("type") == "BEARISH_SWEEP":
                sweep_pts_sell = 35
                detected_setup = "SETUP_1_SWEEP_MSS"

        # --- 2. MARKET STRUCTURE SHIFT (MSS) (Max 20 pts) ---
        mss_pts_buy = 0
        mss_pts_sell = 0
        if mss_data.get("mss"):
            if mss_data.get("direction") == "BULLISH_MSS":
                mss_pts_buy = 20
                if detected_setup == "NONE":
                    detected_setup = "SETUP_1_SWEEP_MSS"
            elif mss_data.get("direction") == "BEARISH_MSS":
                mss_pts_sell = 20
                if detected_setup == "NONE":
                    detected_setup = "SETUP_1_SWEEP_MSS"

        # --- 3. TREND PULLBACK (Setup 2) (Max 35 pts) ---
        pullback_buy = 0
        pullback_sell = 0
        if "TRENDING" in regime:
            # Bullish EMA pullback
            if ema_f > ema_s and close >= ema_t * 0.9995:
                if (low <= ema_f * 1.0005 or low <= ema_s * 1.0008) and (lower_wick_ratio >= self.min_wick_ratio or close >= open_price):
                    pullback_buy = 35
                    if detected_setup == "NONE":
                        detected_setup = "SETUP_2_TREND_PULLBACK"

            # Bearish EMA pullback
            if ema_f < ema_s and close <= ema_t * 1.0005:
                if (high >= ema_f * 0.9995 or high >= ema_s * 0.9992) and (upper_wick_ratio >= self.min_wick_ratio or close <= open_price):
                    pullback_sell = 35
                    if detected_setup == "NONE":
                        detected_setup = "SETUP_2_TREND_PULLBACK"

        # --- 4. BREAKOUT + RETEST (Setup 3) (Max 30 pts) ---
        retest_buy = 0
        retest_sell = 0
        asian_high = session_levels.get("asian_high", 0.0)
        asian_low = session_levels.get("asian_low", 0.0)
        if asian_high > 0 and close > asian_high and abs(low - asian_high) <= (atr_val * 0.40):
            if lower_wick_ratio >= 0.15:
                retest_buy = 30
                if detected_setup == "NONE":
                    detected_setup = "SETUP_3_BREAKOUT_RETEST"
        if asian_low > 0 and close < asian_low and abs(high - asian_low) <= (atr_val * 0.40):
            if upper_wick_ratio >= 0.15:
                retest_sell = 30
                if detected_setup == "NONE":
                    detected_setup = "SETUP_3_BREAKOUT_RETEST"

        # --- 5. VWAP RANGE MEAN REVERSION (Setup 5) (Max 35 pts) ---
        vwap_mr_buy = 0
        vwap_mr_sell = 0
        if regime == "RANGING_CONSOLIDATION":
            # Oversold at lower boundary -> Mean revert to VWAP
            if close <= bb_lower or z_score <= -1.4:
                if lower_wick_ratio >= 0.20 and close < vwap_val:
                    vwap_mr_buy = 35
                    detected_setup = "SETUP_5_VWAP_MEAN_REVERSION"
            # Overbought at upper boundary -> Mean revert to VWAP
            elif close >= bb_upper or z_score >= 1.4:
                if upper_wick_ratio >= 0.20 and close > vwap_val:
                    vwap_mr_sell = 35
                    detected_setup = "SETUP_5_VWAP_MEAN_REVERSION"

        # --- 6. FAIR VALUE GAP (FVG) CONFLUENCE (Max 15 pts) ---
        fvg_buy = 0
        fvg_sell = 0
        if fvgs:
            latest_fvg = fvgs[-1]
            if latest_fvg["type"] == "BULLISH_FVG" and close >= latest_fvg["bottom"] and close <= (latest_fvg["top"] + 0.30):
                fvg_buy = 15
                if detected_setup == "NONE":
                    detected_setup = "SETUP_4_FVG_CONFLUENCE"
            elif latest_fvg["type"] == "BEARISH_FVG" and close <= latest_fvg["top"] and close >= (latest_fvg["bottom"] - 0.30):
                fvg_sell = 15
                if detected_setup == "NONE":
                    detected_setup = "SETUP_4_FVG_CONFLUENCE"

        # --- 7. MACRO H1 TREND ALIGNMENT (Max 15 pts) ---
        macro_buy = 15 if h1_trend == "BULLISH" else (0 if h1_trend == "BEARISH" else 5)
        macro_sell = 15 if h1_trend == "BEARISH" else (0 if h1_trend == "BULLISH" else 5)

        # --- 8. VOLUME CONFIRMATION (Max 10 pts) ---
        vol_confirmed = 10 if vol_ratio >= 1.10 else (5 if vol_ratio >= 0.90 else 0)

        # --- 9. M1 MICRO TIMING CONFIRMATION (Max 15 pts) ---
        m1_buy = 15 if m1_timing.get("bullish_confirmed") else (5 if m1_timing.get("is_displaced") else 0)
        m1_sell = 15 if m1_timing.get("bearish_confirmed") else (5 if m1_timing.get("is_displaced") else 0)

        # Calculate Pure Alpha Confluence Scores (No synthetic spread bonus points)
        buy_score = max(sweep_pts_buy, pullback_buy, retest_buy, vwap_mr_buy) + mss_pts_buy + fvg_buy + macro_buy + vol_confirmed + m1_buy
        sell_score = max(sweep_pts_sell, pullback_sell, retest_sell, vwap_mr_sell) + mss_pts_sell + fvg_sell + macro_sell + vol_confirmed + m1_sell

        # Bound scores to 100
        buy_score = min(100, buy_score)
        sell_score = min(100, sell_score)

        # Overextension check: suppress buy if Z-Score >= 1.5; suppress sell if Z-Score <= -1.5
        if z_score >= self.z_max:
            buy_score = 0
        if z_score <= -self.z_max:
            sell_score = 0

        # --- ML PROBABILISTIC & EXPECTED VALUE EVALUATION ---
        buy_features = {
            "core_setup_pts": max(sweep_pts_buy, pullback_buy, retest_buy, vwap_mr_buy),
            "mss_pts": mss_pts_buy,
            "fvg_pts": fvg_buy,
            "h1_macro_pts": macro_buy,
            "vol_ratio": vol_ratio,
            "m1_disp": m1_timing.get("is_displaced", False),
            "m1_bos": m1_timing.get("micro_bos_bull", False),
            "chop": chop_val,
            "adx": adx_val,
            "z_score": z_score,
            "wick_ratio": lower_wick_ratio
        }
        sell_features = {
            "core_setup_pts": max(sweep_pts_sell, pullback_sell, retest_sell, vwap_mr_sell),
            "mss_pts": mss_pts_sell,
            "fvg_pts": fvg_sell,
            "h1_macro_pts": macro_sell,
            "vol_ratio": vol_ratio,
            "m1_disp": m1_timing.get("is_displaced", False),
            "m1_bos": m1_timing.get("micro_bos_bear", False),
            "chop": chop_val,
            "adx": adx_val,
            "z_score": z_score,
            "wick_ratio": upper_wick_ratio
        }

        ml_buy = self.ml_engine.evaluate_expectancy(buy_features, spread_usd=spread_usd, atr_usd=atr_val)
        ml_sell = self.ml_engine.evaluate_expectancy(sell_features, spread_usd=spread_usd, atr_usd=atr_val)

        # Decision Threshold Logic: Confluence Score >= threshold AND ML Positive Expected Value
        final_signal = "HOLD"
        final_score = 0
        final_grade = "NONE"

        if buy_score >= self.min_confluence_threshold and ml_buy["trade_valid"] and buy_score > sell_score:
            final_signal = "BUY"
            final_score = buy_score
            final_grade = ml_buy["grade"]
            score_breakdown = {
                "core_setup": max(sweep_pts_buy, pullback_buy, retest_buy, vwap_mr_buy),
                "mss": mss_pts_buy,
                "fvg": fvg_buy,
                "h1_macro": macro_buy,
                "volume": vol_confirmed,
                "m1_timing": m1_buy,
                "ml_probability": ml_buy["win_probability_pct"],
                "expected_value_r": ml_buy["expected_value_r"]
            }
        elif sell_score >= self.min_confluence_threshold and ml_sell["trade_valid"] and sell_score > buy_score:
            final_signal = "SELL"
            final_score = sell_score
            final_grade = ml_sell["grade"]
            score_breakdown = {
                "core_setup": max(sweep_pts_sell, pullback_sell, retest_sell, vwap_mr_sell),
                "mss": mss_pts_sell,
                "fvg": fvg_sell,
                "h1_macro": macro_sell,
                "volume": vol_confirmed,
                "m1_timing": m1_sell,
                "ml_probability": ml_sell["win_probability_pct"],
                "expected_value_r": ml_sell["expected_value_r"]
            }
        else:
            final_score = max(buy_score, sell_score)
            active_ml = ml_buy if buy_score >= sell_score else ml_sell
            final_grade = active_ml["grade"]

        active_ml = ml_buy if buy_score >= sell_score else ml_sell
        metrics["ml"] = active_ml

        reason_str = (
            f"Gold {final_signal} [{final_grade} | Score: {final_score}/100 | {detected_setup} | "
            f"ML: {active_ml['win_probability_pct']}% EV={active_ml['expected_value_r']:+.2f}R]: "
            f"Regime={regime}, H1={h1_trend}, Vol={vol_ratio:.1f}x, CHOP={chop_val:.1f}, Z={z_score:+.2f}."
        )

        return {
            "signal": final_signal,
            "confidence": round(active_ml["p_win"], 4),
            "setup": detected_setup,
            "grade": final_grade,
            "regime": regime,
            "confluence_score": final_score,
            "ml_expectancy": active_ml,
            "score_breakdown": score_breakdown,
            "reason": reason_str,
            "metrics": metrics
        }
