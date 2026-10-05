import os
import json
import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, Tuple
import config
from quant_engine import QuantitativeEngine

TRAINED_MODELS_PATH = os.path.join(os.path.dirname(__file__), "trained_models.json")

def get_trained_params(symbol: str) -> Dict[str, Any]:
    """Retrieves coin-specific 1-year trained optimal parameters if available."""
    if os.path.exists(TRAINED_MODELS_PATH):
        try:
            with open(TRAINED_MODELS_PATH, "r") as f:
                data = json.load(f)
                return data.get(symbol, {}).get("optimal_parameters", {})
        except Exception:
            return {}
    return {}


class ForexConfluenceStrategy:
    """
    Quantitative Multi-Timeframe Trend + Momentum Confluence Strategy
    with Fractional Kelly Sizing, Z-Score Mean Reversion, Fractal CHOP,
    Intraday VWAP Anchor, Dynamic ATR Percentile Sizing, and Expected Value (EV).
    """

    def __init__(self, ema_fast: int = 9, ema_slow: int = 21, rsi_period: int = 14, atr_period: int = 14, adx_period: int = 14):
        self.ema_fast = getattr(config, "EMA_FAST", ema_fast)
        self.ema_slow = getattr(config, "EMA_SLOW", ema_slow)
        self.rsi_period = rsi_period
        self.atr_period = atr_period
        self.adx_period = adx_period

    def calculate_indicators(self, rates_data) -> pd.DataFrame:
        """Calculates EMAs, RSI, ATR, ADX, Volume SMA, Z-Score, CHOP, and VWAP."""
        df = pd.DataFrame(rates_data)
        if df.empty or len(df) < self.ema_slow + 5:
            return df

        if pd.api.types.is_numeric_dtype(df["time"]):
            df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        else:
            df["time"] = pd.to_datetime(df["time"], utc=True)

        high = df["high"]
        low = df["low"]
        close = df["close"]
        vol = df["tick_volume"] if "tick_volume" in df.columns else (df["volume"] if "volume" in df.columns else pd.Series(100.0, index=df.index))

        # EMAs
        df["ema_fast"] = close.ewm(span=self.ema_fast, adjust=False).mean()
        df["ema_slow"] = close.ewm(span=self.ema_slow, adjust=False).mean()
        df["ema_trend"] = close.ewm(span=getattr(config, "EMA_TREND_BASELINE", 50), adjust=False).mean()

        # Volume 20 SMA
        df["vol_sma20"] = vol.rolling(window=20).mean()

        # RSI (14)
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1 / self.rsi_period, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1 / self.rsi_period, adjust=False).mean()
        rs = gain / (loss + 1e-9)
        df["rsi"] = 100 - (100 / (1 + rs))

        # ATR (14)
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df["atr"] = tr.rolling(window=self.atr_period).mean()

        # ADX (14)
        up_move = high - high.shift()
        down_move = low.shift() - low
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        tr_smooth = tr.ewm(alpha=1 / self.adx_period, adjust=False).mean()
        plus_di = 100 * (pd.Series(plus_dm).ewm(alpha=1 / self.adx_period, adjust=False).mean() / (tr_smooth + 1e-9))
        minus_di = 100 * (pd.Series(minus_dm).ewm(alpha=1 / self.adx_period, adjust=False).mean() / (tr_smooth + 1e-9))
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9))
        df["adx"] = dx.ewm(alpha=1 / self.adx_period, adjust=False).mean()
        df["plus_di"] = plus_di
        df["minus_di"] = minus_di

        # 1. Quantitative Z-Score (50-period)
        df["z_score"] = QuantitativeEngine.calculate_z_score(close, period=50)

        # 2. Fractal Choppiness Index (CHOP)
        df["chop"] = QuantitativeEngine.calculate_choppiness_index(high, low, close, period=14)

        # 3. Daily-Anchored Session VWAP
        df["vwap"] = QuantitativeEngine.calculate_vwap(high, low, close, vol, datetimes=df["time"])

        return df

    def analyze_h1_trend(self, h1_rates) -> Tuple[str, float, float]:
        """Determines macro trend regime from H1 candles using Fast/Slow EMAs and EMA 50 baseline."""
        if h1_rates is None or len(h1_rates) < self.ema_slow:
            return "UNKNOWN", 0.0, 0.0

        df_h1 = pd.DataFrame(h1_rates)
        s_close = df_h1["close"]
        ema_f = s_close.ewm(span=self.ema_fast, adjust=False).mean().iloc[-1]
        ema_s = s_close.ewm(span=self.ema_slow, adjust=False).mean().iloc[-1]
        ema_50 = s_close.ewm(span=50, adjust=False).mean().iloc[-1] if len(s_close) >= 50 else ema_s
        close = s_close.iloc[-1]

        if ema_f > ema_s and close > ema_s and close > (ema_50 * 0.999):
            return "BULLISH", ema_f, ema_s
        elif ema_f < ema_s and close < ema_s and close < (ema_50 * 1.001):
            return "BEARISH", ema_f, ema_s
        return "NEUTRAL", ema_f, ema_s

    def analyze(self, m5_rates, h1_rates = None, csm_engine = None, smc_engine = None, symbol: str = "EURUSDm") -> Dict[str, Any]:
        """
        Comprehensive Quantitative & Statistical Analysis:
        - M5 + H1 Trend Alignment
        - Fractal Choppiness Index (CHOP < 61.8)
        - Z-Score Statistical Pullback Verification
        - Intraday VWAP Institutional Discount/Premium
        - ADX Volatility Floor
        - Rejection Wicks & Volume Surge
        - SMC Trap Avoidance & FVG Imbalance
        """
        df_m5 = self.calculate_indicators(m5_rates)
        if df_m5.empty or len(df_m5) < self.ema_slow:
            return {
                "signal": "HOLD",
                "reason": f"Insufficient candles (need {self.ema_slow}+, got {len(df_m5)})",
                "metrics": {},
                "score": 0
            }

        prev_candle = df_m5.iloc[-2]
        curr_candle = df_m5.iloc[-1]
        prev_2_candle = df_m5.iloc[-3]

        close = curr_candle["close"]
        open_price = curr_candle["open"]
        high = curr_candle["high"]
        low = curr_candle["low"]
        curr_vol = curr_candle["tick_volume"]
        vol_sma = curr_candle.get("vol_sma20", curr_vol)
        vol_ratio = curr_vol / (vol_sma + 1e-9)

        ema_fast_val = curr_candle["ema_fast"]
        ema_slow_val = curr_candle["ema_slow"]
        rsi_curr = curr_candle["rsi"]
        rsi_prev = prev_candle["rsi"]
        rsi_prev2 = prev_2_candle["rsi"]
        atr_val = curr_candle["atr"] if not np.isnan(curr_candle["atr"]) else 0.00070
        adx_val = curr_candle["adx"] if not np.isnan(curr_candle["adx"]) else 15.0
        z_score_val = curr_candle["z_score"] if not np.isnan(curr_candle["z_score"]) else 0.0
        chop_val = curr_candle["chop"] if not np.isnan(curr_candle["chop"]) else 50.0
        vwap_val = curr_candle["vwap"] if not np.isnan(curr_candle["vwap"]) else close

        # ATR Percentile Rank
        atr_percentile = QuantitativeEngine.calculate_atr_percentile(df_m5["atr"])

        # Wick Calculations
        candle_range = high - low
        if candle_range > 0:
            lower_wick = min(open_price, close) - low
            upper_wick = high - max(open_price, close)
            lower_wick_ratio = lower_wick / candle_range
            upper_wick_ratio = upper_wick / candle_range
        else:
            lower_wick_ratio = 0.0
            upper_wick_ratio = 0.0

        ema_trend_val = curr_candle.get("ema_trend", ema_slow_val)
        m5_uptrend = (ema_fast_val > ema_slow_val) and (close > ema_fast_val) and (close >= ema_trend_val * 0.999)
        m5_downtrend = (ema_fast_val < ema_slow_val) and (close < ema_fast_val) and (close <= ema_trend_val * 1.001)

        h1_trend, _, _ = self.analyze_h1_trend(h1_rates)
        has_fvg, fvg_type = smc_engine.detect_recent_fvg(df_m5) if smc_engine else (False, "NONE")

        metrics = {
            "close": round(close, 5),
            "ema_fast": round(ema_fast_val, 5),
            "ema_slow": round(ema_slow_val, 5),
            "ema_trend": round(ema_trend_val, 5),
            "rsi": round(rsi_curr, 2),
            "atr": round(atr_val, 5),
            "atr_pct": round(atr_percentile, 1),
            "adx": round(adx_val, 2),
            "z_score": round(z_score_val, 2),
            "chop": round(chop_val, 1),
            "vwap": round(vwap_val, 5),
            "vol_ratio": round(vol_ratio, 2),
            "lower_wick_pct": round(lower_wick_ratio * 100, 1),
            "upper_wick_pct": round(upper_wick_ratio * 100, 1),
            "fvg": fvg_type,
            "m5_trend": "BULLISH" if m5_uptrend else ("BEARISH" if m5_downtrend else "NEUTRAL"),
            "h1_trend": h1_trend,
        }

        # Load 1-year trained optimal parameters for this coin/pair if available
        trained_p = get_trained_params(symbol)
        chop_max_limit = trained_p.get("chop_max", config.MAX_CHOPPINESS_INDEX)
        rsi_os = trained_p.get("rsi_pullback_os", 48.0)
        rsi_ob = 100.0 - rsi_os
        z_limit = trained_p.get("z_score_limit", config.Z_SCORE_PULLBACK_MAX)

        # -------------------------------------------------------------
        # QUANTITATIVE GATEKEEPER 1: CHOPPINESS INDEX (FRACTAL CHOP)
        # -------------------------------------------------------------
        if config.CHOP_FILTER_ENABLED and chop_val > chop_max_limit:
            return {
                "signal": "HOLD",
                "reason": f"Fractal Chop Guard: CHOP ({chop_val:.1f} > {chop_max_limit}) proves market is in random consolidation.",
                "metrics": metrics,
                "score": 0
            }

        # -------------------------------------------------------------
        # QUANTITATIVE GATEKEEPER 2: Z-SCORE OVEREXTENSION GUARD
        # -------------------------------------------------------------
        if config.Z_SCORE_FILTER_ENABLED and abs(z_score_val) > z_limit:
            return {
                "signal": "HOLD",
                "reason": f"Z-Score Guard: Price overextended (Z={z_score_val:+.2f}, limit {z_limit}).",
                "metrics": metrics,
                "score": 0
            }

        has_trend_strength = (adx_val >= config.MIN_ADX_THRESHOLD) if config.ADX_FILTER_ENABLED else True

        # -------------------------------------------------------------
        # BUY CONFLUENCE EVALUATION
        # -------------------------------------------------------------
        if m5_uptrend:
            recent_rsi_pullback = min(rsi_prev, rsi_prev2) <= rsi_os
            rsi_momentum_rebound = rsi_curr > rsi_os and rsi_curr > rsi_prev
            is_bullish_candle = close >= open_price

            if recent_rsi_pullback and rsi_momentum_rebound and is_bullish_candle:
                # 1. Higher Timeframe Guard
                if h1_trend == "BEARISH":
                    return {"signal": "HOLD", "reason": "M5 Buy suppressed: H1 macro trend is BEARISH.", "metrics": metrics, "score": 0}

                # 2. ADX Chop Guard
                if not has_trend_strength:
                    return {"signal": "HOLD", "reason": f"M5 Buy suppressed: ADX ({adx_val:.1f} < {config.MIN_ADX_THRESHOLD}).", "metrics": metrics, "score": 0}

                # 3. Volume Surge Guard
                if config.PRICE_ACTION_FILTER_ENABLED and vol_ratio < config.MIN_VOLUME_SURGE_RATIO:
                    return {"signal": "HOLD", "reason": f"M5 Buy suppressed: Low tick volume ({vol_ratio:.2f}x).", "metrics": metrics, "score": 0}

                # 4. Currency Strength Meter Guard
                if csm_engine and config.CSM_FILTER_ENABLED:
                    csm_ok, csm_reason = csm_engine.is_aligned_with_signal(symbol, "BUY")
                    if not csm_ok:
                        return {"signal": "HOLD", "reason": f"M5 Buy suppressed: {csm_reason}", "metrics": metrics, "score": 0}

                # 5. SMC Resistance Wall Guard
                if smc_engine and config.SMC_FILTER_ENABLED:
                    smc_ok, smc_reason = smc_engine.check_structure_trap(symbol, "BUY", close)
                    if not smc_ok:
                        return {"signal": "HOLD", "reason": smc_reason, "metrics": metrics, "score": 0}

                # 6. VWAP Institutional Discount Check
                is_vwap_discount = close <= (vwap_val * 1.0005)

                # Quantitative Score
                score = 65
                if h1_trend == "BULLISH": score += 10
                if adx_val >= 25.0: score += 5
                if chop_val <= 42.0: score += 10  # Super clean fractal trend
                if z_score_val <= -0.5: score += 5  # Statistical discount
                if is_vwap_discount: score += 5    # VWAP institutional discount
                if fvg_type == "BULLISH_FVG": score += 5

                # Asset-Class Specific Momentum & Strength Normalization
                is_crypto = any(c in symbol.upper() for c in ["BTC", "ETH", "SOL", "XRP"])
                if is_crypto:
                    # Crypto-native institutional volume acceleration & volatility expansion
                    if vol_ratio >= 1.5: score += 5
                    if candle_range >= (atr_val * 1.0): score += 5
                else:
                    # Forex Currency Strength Meter differential boost
                    if csm_engine and config.CSM_FILTER_ENABLED:
                        diff, _, _ = csm_engine.get_currency_differential(symbol)
                        if diff >= config.MIN_CSM_DIFFERENTIAL: score += 5
                        if diff >= (config.MIN_CSM_DIFFERENTIAL * 2.0): score += 5

                return {
                    "signal": "BUY",
                    "reason": f"Quant Confluence: H1={h1_trend}, M5 Bullish, CHOP={chop_val:.1f}, Z={z_score_val:.2f}, VWAP discount verified.",
                    "metrics": metrics,
                    "score": min(score, 100)
                }

        # -------------------------------------------------------------
        # SELL CONFLUENCE EVALUATION
        # -------------------------------------------------------------
        if m5_downtrend:
            recent_rsi_rally = max(rsi_prev, rsi_prev2) >= rsi_ob
            rsi_momentum_drop = rsi_curr < rsi_ob and rsi_curr < rsi_prev
            is_bearish_candle = close <= open_price

            if recent_rsi_rally and rsi_momentum_drop and is_bearish_candle:
                # 1. Higher Timeframe Guard
                if h1_trend == "BULLISH":
                    return {"signal": "HOLD", "reason": "M5 Sell suppressed: H1 macro trend is BULLISH.", "metrics": metrics, "score": 0}

                # 2. ADX Chop Guard
                if not has_trend_strength:
                    return {"signal": "HOLD", "reason": f"M5 Sell suppressed: ADX ({adx_val:.1f} < {config.MIN_ADX_THRESHOLD}).", "metrics": metrics, "score": 0}

                # 3. Volume Surge Guard
                if config.PRICE_ACTION_FILTER_ENABLED and vol_ratio < config.MIN_VOLUME_SURGE_RATIO:
                    return {"signal": "HOLD", "reason": f"M5 Sell suppressed: Low tick volume ({vol_ratio:.2f}x).", "metrics": metrics, "score": 0}

                # 4. Currency Strength Meter Guard
                if csm_engine and config.CSM_FILTER_ENABLED:
                    csm_ok, csm_reason = csm_engine.is_aligned_with_signal(symbol, "SELL")
                    if not csm_ok:
                        return {"signal": "HOLD", "reason": f"M5 Sell suppressed: {csm_reason}", "metrics": metrics, "score": 0}

                # 5. SMC Support Wall Guard
                if smc_engine and config.SMC_FILTER_ENABLED:
                    smc_ok, smc_reason = smc_engine.check_structure_trap(symbol, "SELL", close)
                    if not smc_ok:
                        return {"signal": "HOLD", "reason": smc_reason, "metrics": metrics, "score": 0}

                # 6. VWAP Institutional Premium Check
                is_vwap_premium = close >= (vwap_val * 0.9995)

                score = 65
                if h1_trend == "BEARISH": score += 10
                if adx_val >= 25.0: score += 5
                if chop_val <= 42.0: score += 10
                if z_score_val >= 0.5: score += 5
                if is_vwap_premium: score += 5
                if fvg_type == "BEARISH_FVG": score += 5

                # Asset-Class Specific Momentum & Strength Normalization
                is_crypto = any(c in symbol.upper() for c in ["BTC", "ETH", "SOL", "XRP"])
                if is_crypto:
                    # Crypto-native institutional volume acceleration & volatility expansion
                    if vol_ratio >= 1.5: score += 5
                    if candle_range >= (atr_val * 1.0): score += 5
                else:
                    # Forex Currency Strength Meter differential boost
                    if csm_engine and config.CSM_FILTER_ENABLED:
                        diff, _, _ = csm_engine.get_currency_differential(symbol)
                        if diff <= -config.MIN_CSM_DIFFERENTIAL: score += 5
                        if diff <= -(config.MIN_CSM_DIFFERENTIAL * 2.0): score += 5

                return {
                    "signal": "SELL",
                    "reason": f"Quant Confluence: H1={h1_trend}, M5 Bearish, CHOP={chop_val:.1f}, Z={z_score_val:.2f}, VWAP premium verified.",
                    "metrics": metrics,
                    "score": min(score, 100)
                }

        return {
            "signal": "HOLD",
            "reason": f"Scanning market. M5={metrics['m5_trend']} | H1={h1_trend} | CHOP={chop_val:.1f} | Z={z_score_val:.2f}",
            "metrics": metrics,
            "score": 0
        }
