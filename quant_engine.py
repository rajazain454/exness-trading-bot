import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple
import logging
import config

logger = logging.getLogger("QuantEngine")

class QuantitativeEngine:
    """
    Mathematical & Statistical Edge Engine:
    1. Fractional Kelly Criterion Position Sizing
    2. Statistical Z-Score Mean-Reversion Pullback
    3. Fractal Choppiness Index (CHOP)
    4. Intraday Volume-Weighted Average Price (VWAP)
    5. Volatility Regime ATR Percentile Engine
    6. Mathematical Expected Value (EV) Gatekeeper
    """

    @staticmethod
    def calculate_kelly_fraction(win_rate: float, avg_win_usd: float, avg_loss_usd: float, fraction: float = 0.25) -> float:
        """
        Calculates Fractional Kelly capital allocation.
        f* = (p * b - (1 - p)) / b
        Returns safe fraction of capital to risk (default Quarter-Kelly = 0.25).
        """
        if avg_loss_usd <= 0 or win_rate <= 0:
            return 0.01  # Minimum 1% risk floor

        p = min(0.95, max(0.05, win_rate / 100.0))
        b = avg_win_usd / (avg_loss_usd + 1e-9)

        full_kelly = (p * b - (1.0 - p)) / (b + 1e-9)
        if full_kelly <= 0:
            return 0.01  # Minimum 1% risk floor

        safe_kelly = full_kelly * fraction
        # Cap between 1% and 5% maximum risk
        return round(min(0.05, max(0.01, safe_kelly)), 4)

    @staticmethod
    def calculate_z_score(close: pd.Series, period: int = 50) -> pd.Series:
        """
        Z-Score measures how many standard deviations price has stretched from the mean.
        Z = (Price - Mean) / StdDev
        """
        mean = close.rolling(period).mean()
        std = close.rolling(period).std()
        z = (close - mean) / (std + 1e-9)
        return z

    @staticmethod
    def calculate_choppiness_index(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """
        Fractal Choppiness Index (CHOP).
        CHOP > 61.8 = Statistically random / choppy range.
        CHOP < 38.2 = Statistically confirmed directional trend.
        """
        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr_sum = tr.rolling(period).sum()
        high_max = high.rolling(period).max()
        low_min = low.rolling(period).min()
        price_range = (high_max - low_min) + 1e-9

        chop = 100.0 * np.log10(atr_sum / price_range) / np.log10(period)
        return chop

    @staticmethod
    def calculate_vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, datetimes: pd.Series = None) -> pd.Series:
        """
        Calculates Daily Anchored Volume-Weighted Average Price (VWAP).
        Resets at 00:00 UTC each day to represent true intraday institutional fair value.
        If datetimes is None, calculates cumulative VWAP over the provided series.
        """
        typical_price = (high + low + close) / 3.0
        pv = typical_price * volume

        if datetimes is not None:
            dates = pd.to_datetime(datetimes).dt.date
            cum_pv = pv.groupby(dates).cumsum()
            cum_vol = volume.groupby(dates).cumsum() + 1e-9
            return cum_pv / cum_vol

        cum_vol_price = pv.cumsum()
        cum_vol = volume.cumsum() + 1e-9
        return cum_vol_price / cum_vol

    @staticmethod
    def calculate_atr_percentile(atr_series: pd.Series, window: int = 100) -> float:
        """
        Calculates the percentile rank of the current ATR over the last 100 periods.
        Returns a score from 0.0% (lowest volatility compression) to 100.0% (highest volatility expansion).
        """
        if len(atr_series) < window:
            return 50.0

        current_atr = atr_series.iloc[-1]
        rolling_window = atr_series.tail(window)
        min_atr = rolling_window.min()
        max_atr = rolling_window.max()

        if max_atr == min_atr:
            return 50.0

        percentile = ((current_atr - min_atr) / (max_atr - min_atr)) * 100.0
        return round(float(percentile), 1)

    @staticmethod
    def calculate_atr_percentile_series(atr_series: pd.Series, window: int = 100) -> pd.Series:
        """
        Vectorized percentile rank of ATR for backtesting and historical analysis.
        """
        rolling_min = atr_series.rolling(window).min()
        rolling_max = atr_series.rolling(window).max()
        pct = ((atr_series - rolling_min) / (rolling_max - rolling_min + 1e-9)) * 100.0
        return pct.fillna(50.0)

    @staticmethod
    def calculate_expected_value(win_prob: float, tp_usd: float, sl_usd: float) -> Tuple[float, float]:
        """
        Expected Value (EV) = (P_win * TP) - (P_loss * SL)
        Returns (ev_usd, ev_to_risk_ratio).
        """
        p_win = min(0.95, max(0.05, win_prob))
        p_loss = 1.0 - p_win

        ev_usd = (p_win * tp_usd) - (p_loss * sl_usd)
        ev_ratio = ev_usd / (sl_usd + 1e-9)
        return round(ev_usd, 2), round(ev_ratio, 2)
