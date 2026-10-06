from typing import Dict, Any, List, Tuple
import config

class MarketRegimeDetector:
    """
    Market Regime Classifier:
    Categorizes market conditions into TRENDING, RANGING, or VOLATILE regimes
    based on ADX trend strength, Choppiness Index (CHOP), and ATR Percentile Rank.
    
    Regimes adapt strategy behavior:
    - TRENDING: Setup 1 (Pullback) and Setup 3 (Momentum Expansion) enabled.
    - RANGING: Blocks momentum expansion breakouts to prevent buying tops / selling bottoms.
    - VOLATILE: High ATR percentile (>80%), demands strict confluence and wider targets.
    """

    @staticmethod
    def classify_regime(
        adx_val: float,
        chop_val: float,
        atr_pct: float,
        z_score_val: float = 0.0
    ) -> Dict[str, Any]:
        """
        Evaluates quantitative regime indicators and returns regime metadata.
        """
        # Volatile Regime: Extreme ATR percentile expansion
        if atr_pct >= getattr(config, "VOLATILE_ATR_PCT_THRESHOLD", 82.0):
            return {
                "regime": "VOLATILE",
                "description": f"High Volatility Expansion (ATR Rank: {atr_pct:.1f}%)",
                "allowed_setups": ["SETUP_1_PULLBACK", "SETUP_2_FVG_MITIGATION"],
                "sl_mult_adjust": 1.15,
                "tp_mult_adjust": 1.25,
            }

        # Ranging / Consolidation Regime: High CHOP or very low ADX
        max_chop = getattr(config, "RANGING_CHOP_THRESHOLD", 58.0)
        min_adx = getattr(config, "RANGING_MIN_ADX", 18.0)
        if chop_val >= max_chop or adx_val < min_adx:
            return {
                "regime": "RANGING",
                "description": f"Consolidation / Range-Bound (CHOP: {chop_val:.1f}, ADX: {adx_val:.1f})",
                "allowed_setups": ["SETUP_2_FVG_MITIGATION"],  # Only allow high-confluence mitigation, no breakouts
                "sl_mult_adjust": 1.0,
                "tp_mult_adjust": 1.0,
            }

        # Trending Regime: Healthy directional strength
        return {
            "regime": "TRENDING",
            "description": f"Directional Trend (CHOP: {chop_val:.1f}, ADX: {adx_val:.1f})",
            "allowed_setups": ["SETUP_1_PULLBACK", "SETUP_2_FVG_MITIGATION", "SETUP_3_MOMENTUM_EXPANSION"],
            "sl_mult_adjust": 1.0,
            "tp_mult_adjust": 1.0,
        }
