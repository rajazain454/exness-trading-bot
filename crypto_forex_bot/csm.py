import time
import logging
import pandas as pd
import numpy as np
from typing import Dict, Any, Tuple, Optional
import config

logger = logging.getLogger("CSM")

class CurrencyStrengthMeter:
    """
    Real-time Currency Strength Meter (CSM).
    Measures the relative strength of major currencies (EUR, USD, GBP, JPY, AUD)
    based on multi-pair momentum across M15/H1 timeframes.
    
    Scores range from -10.0 (Extremely Weak) to +10.0 (Extremely Strong).
    """

    CORE_PAIRS = ["EURUSDm", "GBPUSDm", "USDJPYm", "AUDUSDm", "EURGBPm", "EURJPYm", "GBPJPYm"]

    def __init__(self, connector):
        self.connector = connector
        self.cached_scores: Dict[str, float] = {}
        self.last_update: Optional[float] = None
        self.cache_ttl_seconds: float = 60.0

    def calculate_strengths(self) -> Dict[str, float]:
        """
        Calculates relative strength ratings for USD, EUR, GBP, JPY, and AUD.
        Uses 14-period multi-pair momentum across liquid majors and crosses
        to triangulate true isolated currency strength.
        Cached with 60-second TTL to eliminate redundant MT5 IPC calls.
        """
        now = time.time()
        if self.cached_scores and self.last_update is not None and (now - self.last_update) < self.cache_ttl_seconds:
            return self.cached_scores

        raw_strengths = {"USD": 0.0, "EUR": 0.0, "GBP": 0.0, "JPY": 0.0, "AUD": 0.0}

        for pair in self.CORE_PAIRS:
            valid_sym = self.connector.verify_symbol(pair)
            if not valid_sym:
                continue

            rates = self.connector.get_rates(valid_sym, "M15", count=30)
            if rates is None or len(rates) < 20:
                continue

            df = pd.DataFrame(rates)
            # 14-period momentum %
            close_now = df["close"].iloc[-1]
            close_14 = df["close"].iloc[-14]
            pct_move = ((close_now - close_14) / close_14) * 100.0

            # Attribute momentum to base and quote
            clean = valid_sym.upper().replace("M", "")
            base = clean[:3]
            quote = clean[3:6]

            impact = pct_move * 3.5

            if base in raw_strengths:
                raw_strengths[base] += impact
            if quote in raw_strengths:
                raw_strengths[quote] -= impact

        # Normalize scores to -10.0 to +10.0 range
        scores = {}
        for ccy, val in raw_strengths.items():
            scores[ccy] = round(max(-10.0, min(10.0, val)), 1)

        self.cached_scores = scores
        self.last_update = now
        return scores

    def get_currency_differential(self, symbol: str) -> Tuple[float, str, str]:
        """
        Returns (differential, base_ccy, quote_ccy).
        Positive differential means base currency is stronger than quote currency.
        Negative differential means base currency is weaker than quote currency.
        """
        scores = self.calculate_strengths()
        clean = symbol.upper().replace("M", "").replace("C", "")
        base = clean[:3] if len(clean) >= 6 else "EUR"
        quote = clean[3:6] if len(clean) >= 6 else "USD"

        base_score = scores.get(base, 0.0)
        quote_score = scores.get(quote, 0.0)
        differential = round(base_score - quote_score, 1)

        return differential, base, quote

    def is_aligned_with_signal(self, symbol: str, signal: str) -> Tuple[bool, str]:
        """
        Validates if currency strength differential supports the proposed trade.
        BUY: Base currency must be stronger than quote currency.
        SELL: Base currency must be weaker than quote currency.
        """
        if not config.CSM_FILTER_ENABLED:
            return True, "CSM filter disabled"

        # Crypto assets (BTC, ETH, etc.) are independent of fiat currency strength baskets
        if any(c in symbol.upper() for c in ["BTC", "ETH", "SOL", "XRP"]):
            return True, "Crypto exempt from fiat Currency Strength Meter"

        diff, base, quote = self.get_currency_differential(symbol)
        min_diff = config.MIN_CSM_DIFFERENTIAL

        if signal == "BUY":
            if diff >= min_diff:
                return True, f"CSM Confirmed: {base} (+{self.cached_scores.get(base, 0)}) > {quote} ({self.cached_scores.get(quote, 0)}), Diff: +{diff}"
            else:
                return False, f"CSM Mismatch: {base} strength ({self.cached_scores.get(base, 0)}) is insufficient vs {quote} ({self.cached_scores.get(quote, 0)}). Diff: {diff} < +{min_diff}"

        elif signal == "SELL":
            if diff <= -min_diff:
                return True, f"CSM Confirmed: {base} ({self.cached_scores.get(base, 0)}) < {quote} (+{self.cached_scores.get(quote, 0)}), Diff: {diff}"
            else:
                return False, f"CSM Mismatch: {base} weakness ({self.cached_scores.get(base, 0)}) is insufficient vs {quote} ({self.cached_scores.get(quote, 0)}). Diff: {diff} > -{min_diff}"

        return True, "Neutral signal"
