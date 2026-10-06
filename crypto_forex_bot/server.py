"""
FastAPI Machine Learning & Quantitative Strategy Server
Integrates Exness Algorithmic Trading Suite with MetaTrader 5 Expert Advisor (Octa_Hybrid_Demo_EA.mq5).
Serves the POST /predict endpoint with real-time quantitative confluence scoring.
"""

import sys
import os
from typing import List, Optional, Any, Dict, Union, cast
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

import config
from quant_engine import QuantitativeEngine
from strategy import ForexConfluenceStrategy, get_trained_params

# Initialize FastAPI app
app = FastAPI(
    title="Exness Quant & ML Prediction Engine",
    description="Institutional Quantitative Confluence Server for MT5 Expert Advisor (Octa_Hybrid_Demo_EA)",
    version="2.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

strategy = ForexConfluenceStrategy()


class PredictRequest(BaseModel):
    symbol: str = Field(..., description="Symbol e.g. EURUSDm", json_schema_extra={"example": "EURUSDm"})
    timeframe: str = Field(default="M5", description="Timeframe e.g. M5", json_schema_extra={"example": "M5"})
    bars: List[List[Union[int, float]]] = Field(
        ...,
        description="List of OHLC bars: [time, open, high, low, close] or [time, open, high, low, close, tick_volume]"
    )
    h1_bars: Optional[List[List[Union[int, float]]]] = Field(
        default=None,
        description="Optional list of H1 bars for macro trend confirmation"
    )


class PredictResponse(BaseModel):
    signal: int = Field(..., description="1 = BUY, -1 = SELL, 0 = HOLD")
    confidence: float = Field(..., description="Confidence score from 0.0 to 1.0")
    suggested_threshold: float = Field(..., description="Recommended minimum confidence threshold")
    model_used: str = Field(..., description="Name of the model or strategy engine used")
    reason: str = Field(..., description="Detailed diagnostic or confluence reason")
    metrics: Dict[str, Any] = Field(default_factory=dict, description="Key indicator metrics")


def parse_bars_to_records(bars: List[List[Union[int, float]]]) -> List[Dict[str, Any]]:
    """Converts raw list of bar lists to MT5-like dictionary records."""
    records = []
    for bar in bars:
        if len(bar) < 5:
            continue
        t = int(bar[0])
        o = float(bar[1])
        h = float(bar[2])
        l = float(bar[3])
        c = float(bar[4])
        v = float(bar[5]) if len(bar) >= 6 else 100.0

        records.append({
            "time": t,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "tick_volume": v
        })
    return records


def resample_to_h1(m5_records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Synthesizes H1 candles from M5 candles if H1 bars were not supplied."""
    if len(m5_records) < 24:
        return m5_records

    df = pd.DataFrame(m5_records)
    df["dt"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("dt").sort_index()

    h1_df = df.resample("1h").agg({
        "time": "first",
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "tick_volume": "sum"
    }).dropna().reset_index(drop=True)

    return cast(List[Dict[str, Any]], cast(Any, h1_df).to_dict(orient="records"))


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "Exness Quant Confluence Prediction Server",
        "version": "2.2.0",
        "time_utc": datetime.now(timezone.utc).isoformat()
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "timeframe": config.TIMEFRAME,
        "higher_timeframe": config.HIGHER_TIMEFRAME,
        "basket": config.SYMBOLS_BASKET,
        "kelly_sizing": config.USE_KELLY_SIZING,
        "chop_guard": config.CHOP_FILTER_ENABLED,
        "z_score_guard": config.Z_SCORE_FILTER_ENABLED
    }


@app.get("/metrics")
def get_metrics():
    """Exports key operational and trading metrics for external monitoring."""
    journal_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trading_journal.db")
    stats = {}
    if os.path.exists(journal_path):
        try:
            from journal import TradeJournal
            j = TradeJournal(journal_path)
            stats = j.get_all_time_stats()
            j.close()
        except Exception as e:
            stats = {"error": str(e)}
    return {
        "status": "online",
        "basket": config.SYMBOLS_BASKET,
        "max_open_positions": config.MAX_OPEN_POSITIONS,
        "max_daily_loss_usd": config.MAX_DAILY_LOSS_USD,
        "stats": stats,
        "timestamp_utc": datetime.now(timezone.utc).isoformat()
    }


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    """
    Evaluates market data passed from MT5 EA and returns institutional trade signal.
    """
    if not req.bars or len(req.bars) < 30:
        return PredictResponse(
            signal=0,
            confidence=0.0,
            suggested_threshold=0.65,
            model_used="ForexConfluenceStrategy_v2.2",
            reason=f"Insufficient bars provided: received {len(req.bars) if req.bars else 0}, need >= 30",
            metrics={}
        )

    # 1. Parse bars
    m5_records = parse_bars_to_records(req.bars)

    # 2. Parse or synthesize H1 bars
    if req.h1_bars and len(req.h1_bars) >= 20:
        h1_records = parse_bars_to_records(req.h1_bars)
    else:
        h1_records = resample_to_h1(m5_records)

    # 3. Execute institutional quantitative confluence strategy
    analysis = strategy.analyze(
        m5_rates=m5_records,
        h1_rates=h1_records,
        csm_engine=None,
        smc_engine=None,
        symbol=req.symbol
    )

    raw_signal = analysis.get("signal", "HOLD")
    score = analysis.get("score", 0)
    reason = analysis.get("reason", "")
    metrics = analysis.get("metrics", {})

    # Map signal string to MT5 EA integer
    if raw_signal == "BUY":
        signal_int = 1
        confidence = round(max(0.65, score / 100.0), 4)
    elif raw_signal == "SELL":
        signal_int = -1
        confidence = round(max(0.65, score / 100.0), 4)
    else:
        signal_int = 0
        confidence = 0.0

    # Retrieve symbol-specific parameters if trained
    trained_p = get_trained_params(req.symbol)
    model_tag = f"QuantEnsemble_v2.2[{req.symbol}]" if trained_p else "QuantEnsemble_v2.2[Default]"

    suggested_threshold = 0.65

    return PredictResponse(
        signal=signal_int,
        confidence=confidence,
        suggested_threshold=suggested_threshold,
        model_used=model_tag,
        reason=reason,
        metrics=metrics
    )


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
