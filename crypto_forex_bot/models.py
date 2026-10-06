"""
Data models and typed contracts for Exness Algorithmic Trading Suite.
Provides structured types for trade parameters, market scan candidates,
and technical analysis results.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class TradeParams:
    """Standardized trade execution parameters."""
    symbol: str
    signal: str  # "BUY" or "SELL"
    lot: float
    entry: float
    sl: float
    tp: float
    rr: float = 2.0
    limit_offset: float = 0.0
    order_type: str = "MARKET"


@dataclass
class ScanCandidate:
    """Evaluated market candidate from basket scanner."""
    symbol: str
    signal: str  # "BUY", "SELL", or "HOLD"
    score: int = 0
    reason: str = ""
    filter_reason: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """Output from quantitative confluence strategy analysis."""
    signal: str
    score: int
    reason: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    filter_reason: str = ""


@dataclass
class ExecutionResult:
    """Output from order execution on broker."""
    ticket: int
    symbol: str
    price: float
    lot: float
    sl: float
    tp: float
    latency_ms: float = 0.0
    slippage_pips: float = 0.0
