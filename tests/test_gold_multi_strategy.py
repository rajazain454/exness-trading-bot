"""
Unit tests for Institutional Gold (XAUUSDm) Multi-Strategy AI Engine:
1. Liquidity Engine (Asian Range, PDH/PDL, Sweeps, MSS, FVGs)
2. Regime Classifier (TRENDING vs RANGING vs BREAKOUT)
3. 100-Point Confluence Scoring Matrix (A+ >= 80, A >= 75, B/C < 75 NO TRADE)
4. DO NOT TRADE Safety Gating
"""

import unittest
import numpy as np
import pandas as pd
from datetime import datetime, timezone

from gold_scalper.liquidity_gold import GoldLiquidityEngine
from gold_scalper.strategy_gold import GoldScalperStrategy


class TestGoldMultiStrategy(unittest.TestCase):

    def setUp(self):
        self.liquidity_engine = GoldLiquidityEngine(sweep_min_usd=0.20, min_rejection_wick=0.15)
        self.strategy = GoldScalperStrategy()

    def test_session_levels_extraction(self):
        """Verifies Asian Range (00:00 - 06:00 UTC) and PDH/PDL extraction."""
        times = []
        highs = []
        lows = []
        opens = []
        closes = []

        base_dt = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
        for i in range(100):
            t = int(base_dt.timestamp()) + (i * 300)
            times.append(t)
            h = 2650.0 + (i * 0.1)
            l = 2640.0 + (i * 0.1)
            o = 2645.0 + (i * 0.1)
            c = 2647.0 + (i * 0.1)
            highs.append(h)
            lows.append(l)
            opens.append(o)
            closes.append(c)

        df = pd.DataFrame({
            "time": times,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "tick_volume": [100] * 100
        })

        levels = self.liquidity_engine.compute_session_levels(df)
        self.assertIn("asian_high", levels)
        self.assertIn("asian_low", levels)
        self.assertGreater(levels["asian_high"], 0.0)
        self.assertGreater(levels["asian_low"], 0.0)

    def test_liquidity_sweep_detection(self):
        """Verifies detection of Asian Low liquidity sweep with rejection wick."""
        levels = {"asian_high": 2650.0, "asian_low": 2640.0, "pdh": 2655.0, "pdl": 2638.0}
        
        # Candle that swept Asian Low (2640.0) by going to 2638.50, but closed at 2641.0 with a big lower wick
        df = pd.DataFrame({
            "open": [2642.0, 2641.5],
            "high": [2643.0, 2642.0],
            "low": [2639.0, 2638.5], # Swept Asian Low (2640.0) by $1.50
            "close": [2641.0, 2641.2], # Closed back above 2640.0
            "time": [1000, 1300]
        })

        sweep = self.liquidity_engine.detect_liquidity_sweep(df, levels, lookback=2)
        self.assertTrue(sweep["swept"])
        self.assertEqual(sweep["type"], "BULLISH_SWEEP")
        self.assertEqual(sweep["level_name"], "Asian Low")
        self.assertGreaterEqual(sweep["sweep_depth"], 0.20)

    def test_market_structure_shift(self):
        """Verifies detection of Bullish MSS when a candle closes above prior swing high with displacement."""
        # Create a series with a clear swing high followed by a displacement breakout
        n = 20
        highs = [2640.0] * n
        lows = [2630.0] * n
        opens = [2632.0] * n
        closes = [2635.0] * n

        # Set swing high at index 10
        highs[10] = 2645.0
        # Breakout candle at latest index
        highs[-1] = 2650.0
        opens[-1] = 2642.0
        closes[-1] = 2648.0 # Closes above 2645.0 with 75% body displacement
        lows[-1] = 2641.0

        df = pd.DataFrame({
            "high": highs,
            "low": lows,
            "open": opens,
            "close": closes,
            "time": [i * 300 for i in range(n)]
        })

        mss = self.liquidity_engine.detect_market_structure_shift(df, lookback=15)
        self.assertTrue(mss["mss"])
        self.assertEqual(mss["direction"], "BULLISH_MSS")
        self.assertEqual(mss["pivot_price"], 2645.0)

    def test_fair_value_gap_detection(self):
        """Verifies detection of 3-candle Fair Value Gap."""
        df = pd.DataFrame({
            "open": [2600.0, 2603.0, 2608.0],
            "high": [2602.0, 2609.0, 2611.0],  # Candle 0 High = 2602.0
            "low": [2599.0, 2602.5, 2605.0],   # Candle 2 Low = 2605.0 -> Gap = 2602.0 to 2605.0 ($3.00)
            "close": [2601.0, 2608.0, 2610.0],
            "time": [0, 300, 600]
        })

        fvgs = self.liquidity_engine.detect_fair_value_gaps(df, lookback=3)
        self.assertTrue(len(fvgs) > 0)
        self.assertEqual(fvgs[0]["type"], "BULLISH_FVG")
        self.assertEqual(fvgs[0]["bottom"], 2602.0)
        self.assertEqual(fvgs[0]["top"], 2605.0)

    def test_regime_classification(self):
        """Verifies Market Regime Classifier distinguishes Trending vs Ranging."""
        curr_trending = pd.Series({
            "adx": 26.0,
            "chop": 42.0,
            "close": 2650.0,
            "open": 2645.0,
            "ema_fast": 2648.0,
            "ema_slow": 2645.0,
            "ema_trend": 2640.0,
            "vol_ratio": 1.1,
            "atr": 2.0
        })
        prev = curr_trending.copy()
        regime = self.strategy.classify_market_regime(curr_trending, prev)
        self.assertEqual(regime, "TRENDING_BULLISH")

        curr_ranging = pd.Series({
            "adx": 16.0,
            "chop": 56.0,
            "close": 2650.0,
            "open": 2649.0,
            "ema_fast": 2650.0,
            "ema_slow": 2650.0,
            "ema_trend": 2650.0,
            "vol_ratio": 0.8,
            "atr": 1.5
        })
        regime_range = self.strategy.classify_market_regime(curr_ranging, prev)
        self.assertEqual(regime_range, "RANGING_CONSOLIDATION")

    def test_confluence_scoring_threshold(self):
        """Verifies that setups scoring < 75 are rejected as NO TRADE (HOLD)."""
        # Minimal rates
        n = 60
        rates = []
        for i in range(n):
            rates.append({
                "time": 1700000000 + (i * 300),
                "open": 2650.0,
                "high": 2651.0,
                "low": 2649.0,
                "close": 2650.0,
                "tick_volume": 100
            })

        analysis = self.strategy.analyze(rates)
        self.assertIn("confluence_score", analysis)
        self.assertIn("grade", analysis)
        # Without confluence, score should be low and signal must be HOLD
        self.assertLess(analysis["confluence_score"], 75)
        self.assertEqual(analysis["signal"], "HOLD")


if __name__ == "__main__":
    unittest.main()
