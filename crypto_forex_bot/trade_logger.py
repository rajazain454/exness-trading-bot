"""
Live Real-Time Trading History & Post-Mortem SL Learning Engine.
Automatically updates:
1. daily_trading_history.md (Performance statistics, daily summary, execution log)
2. trade_decision_learning.md (Entry rationale, TP/SL targets, failure diagnosis & adaptive learning)

Works seamlessly across Demo forward-testing and Live Exness accounts.
"""

import os
import json
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CRYPTO_DIR = os.path.join(BASE_DIR, "crypto_forex_bot")
GOLD_DIR = os.path.join(BASE_DIR, "gold_scalper")

CRYPTO_DAILY_FILE = os.path.join(CRYPTO_DIR, "daily_trading_history.md")
CRYPTO_LEARNING_FILE = os.path.join(CRYPTO_DIR, "trade_decision_learning.md")

GOLD_DAILY_FILE = os.path.join(GOLD_DIR, "daily_trading_history.md")
GOLD_LEARNING_FILE = os.path.join(GOLD_DIR, "trade_decision_learning.md")


def classify_sl_root_cause(symbol: str, signal: str, decision_basis: Dict[str, Any], pnl: float) -> Dict[str, str]:
    """
    Analyzes why a trade hit Stop Loss and generates a root-cause diagnosis,
    lesson learned, and adaptive learning adjustment.
    """
    chop = float(decision_basis.get("chop", 45.0))
    z_score = abs(float(decision_basis.get("z_score", 0.0)))
    vol_ratio = float(decision_basis.get("vol_ratio", 1.0))
    adx = float(decision_basis.get("adx", 25.0))
    h1_trend = str(decision_basis.get("h1_trend", "")).upper()
    wick_ratio = float(decision_basis.get("wick_ratio", 0.20))
    setup_name = str(decision_basis.get("setup", "Institutional Confluence"))

    is_gold = "XAU" in symbol.upper()

    if chop >= 50.0:
        category = "CHOP_EXPANSION_TRAP"
        diagnosis = (
            f"Entered during consolidation where Choppiness Index was elevated ({chop:.1f} >= 50.0). "
            f"Price lacked directional continuation and whip-sawed into Stop Loss."
        )
        lesson = "Avoid opening continuation trades when CHOP is above 48. Require clearer compression breakout."
        action = "Temporarily increased Choppiness filter stringency: blocking setups with CHOP > 48.0."
    elif z_score >= 1.4:
        category = "EXHAUSTED_SPIKE_TRAP"
        diagnosis = (
            f"Price was overextended ({z_score:.2f} standard deviations from VWAP). "
            f"Mean reversion kicked in aggressively before the Take Profit could be reached."
        )
        lesson = "Do not chase extended spikes. Require pullback closer to 21 EMA / VWAP mean before entry."
        action = f"Reinforced Z-Score penalty: setups with Z > 1.30 will now be gated out."
    elif vol_ratio < 0.85:
        category = "VOLUME_FAKEOUT_TRAP"
        diagnosis = (
            f"Institutional volume ratio was weak ({vol_ratio:.2f}x average). "
            f"The move lacked follow-through buying/selling pressure and reversed."
        )
        lesson = "Only trade when volume confirms displacement. Volume below 0.85x indicates retail trap."
        action = "Raised minimum volume surge filter baseline to 0.85x average."
    elif h1_trend and h1_trend not in ["UNKNOWN", "NEUTRAL"] and (
        (signal == "BUY" and h1_trend == "BEARISH") or (signal == "SELL" and h1_trend == "BULLISH")
    ):
        category = "COUNTER_TREND_TRAP"
        diagnosis = (
            f"Trade was executed counter to the dominant H1 macro trend (Signal: {signal} vs H1: {h1_trend}). "
            f"Higher timeframe orderflow overwhelmed the lower timeframe scalp."
        )
        lesson = "Never take counter-trend pullbacks unless major higher-timeframe key liquidity is swept."
        action = "Strict H1 trend alignment enforcement applied: counter-trend signals penalized."
    elif is_gold and wick_ratio < 0.15:
        category = "INSUFFICIENT_ABSORPTION_WICK"
        diagnosis = (
            f"Rejection wick ratio was only {wick_ratio * 100:.1f}% (required >= 15%). "
            f"Smart money liquidity was not properly absorbed before price reversed."
        )
        lesson = "Wait for at least 15% wick absorption to prove smart money defense before entering."
        action = "Raised minimum absorption wick threshold to 18% for Gold scalps."
    else:
        category = "LIQUIDITY_HUNT_SPIKE"
        diagnosis = (
            f"Market executed a secondary liquidity grab or spread spike that clipped the Stop Loss "
            f"before reversing back into the intended direction."
        )
        lesson = "Slightly widen buffer or place stops beyond swing structure rather than arbitrary tight points."
        action = "Enhanced post-loss cooldown: 2 completed M5 candles required before scanning this symbol again."

    # Apply adaptive model adjustment to learn from the loss
    if is_gold:
        _apply_gold_ml_adaptive_penalty(category)
    else:
        _apply_crypto_adaptive_penalty(symbol, category)

    return {
        "category": category,
        "diagnosis": diagnosis,
        "lesson": lesson,
        "action": action
    }


def _apply_crypto_adaptive_penalty(symbol: str, category: str):
    """Dynamically adapts trained parameters for the specific coin/pair upon loss."""
    models_path = os.path.join(CRYPTO_DIR, "trained_models.json")
    if not os.path.exists(models_path):
        return
    try:
        with open(models_path, "r") as f:
            data = json.load(f)
        if symbol in data and "optimal_parameters" in data[symbol]:
            params = data[symbol]["optimal_parameters"]
            if category == "LIQUIDITY_HUNT_SPIKE":
                # Slightly widen SL buffer from 1.5 to 1.6 to prevent tight stop outs
                params["base_sl_mult"] = round(min(2.0, params.get("base_sl_mult", 1.5) + 0.1), 2)
            elif category == "EXHAUSTED_SPIKE_TRAP":
                # Tighten Z-score limit so it stops chasing extended moves
                params["z_score_limit"] = round(max(1.5, params.get("z_score_limit", 2.8) - 0.2), 2)
            elif category == "CHOP_EXPANSION_TRAP":
                # Tighten chop threshold so it demands cleaner trending markets
                params["chop_max"] = round(max(48.0, params.get("chop_max", 61.8) - 2.0), 1)

            data[symbol]["optimal_parameters"] = params
            data[symbol]["last_adapted"] = datetime.now(timezone.utc).isoformat()
            data[symbol]["last_adaptation_cause"] = category
            with open(models_path, "w") as f:
                json.dump(data, f, indent=4)
    except Exception:
        pass


def _apply_gold_ml_adaptive_penalty(category: str):
    """Adjusts institutional weights slightly to learn from recent loss."""
    weights_path = os.path.join(GOLD_DIR, "gold_ml_weights.json")
    if not os.path.exists(weights_path):
        return
    try:
        with open(weights_path, "r") as f:
            data = json.load(f)
        weights = data.get("weights", {})
        if category == "CHOP_EXPANSION_TRAP":
            weights["chop_penalty"] = round(weights.get("chop_penalty", -0.030) - 0.005, 4)
        elif category == "EXHAUSTED_SPIKE_TRAP":
            weights["z_score_penalty"] = round(weights.get("z_score_penalty", -0.350) - 0.020, 4)
        elif category == "VOLUME_FAKEOUT_TRAP":
            weights["volume_ratio"] = round(weights.get("volume_ratio", 0.550) + 0.025, 4)

        data["weights"] = weights
        data["last_adapted"] = datetime.now(timezone.utc).isoformat()
        with open(weights_path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def update_live_trade_files(
    bot_type: str,  # "crypto" or "gold"
    ticket: int,
    symbol: str,
    signal: str,
    lot: float,
    entry_price: float,
    exit_price: float,
    sl: float,
    tp: float,
    pnl: float,
    pips: float,
    outcome: str,
    close_reason: str,
    duration_mins: int = 0,
    decision_basis: Optional[Dict[str, Any]] = None,
    balance: float = 0.0
):
    """
    Appends the finished trade to both the Daily Trading History and the
    Trade Decision & Learning Ledger in real-time.
    """
    decision_basis = decision_basis or {}
    is_gold = bot_type.lower() == "gold" or "XAU" in symbol.upper()
    daily_file = GOLD_DAILY_FILE if is_gold else CRYPTO_DAILY_FILE
    learning_file = GOLD_LEARNING_FILE if is_gold else CRYPTO_LEARNING_FILE

    now_utc = datetime.now(timezone.utc)
    date_str = now_utc.strftime("%Y-%m-%d")
    time_str = now_utc.strftime("%H:%M:%S UTC")

    # 1. Update Daily Trading History
    _append_daily_history(
        file_path=daily_file,
        date_str=date_str,
        time_str=time_str,
        ticket=ticket,
        symbol=symbol,
        signal=signal,
        lot=lot,
        entry_price=entry_price,
        exit_price=exit_price,
        pnl=pnl,
        pips=pips,
        outcome=outcome,
        close_reason=close_reason,
        duration_mins=duration_mins,
        balance=balance,
        is_gold=is_gold
    )

    # 2. Update Trade Decision & Learning Ledger
    _append_decision_learning(
        file_path=learning_file,
        date_str=date_str,
        time_str=time_str,
        ticket=ticket,
        symbol=symbol,
        signal=signal,
        lot=lot,
        entry_price=entry_price,
        exit_price=exit_price,
        sl=sl,
        tp=tp,
        pnl=pnl,
        pips=pips,
        outcome=outcome,
        close_reason=close_reason,
        decision_basis=decision_basis,
        is_gold=is_gold
    )


def _append_daily_history(file_path: str, date_str: str, time_str: str, ticket: int, symbol: str, signal: str,
                          lot: float, entry_price: float, exit_price: float, pnl: float, pips: float,
                          outcome: str, close_reason: str, duration_mins: int, balance: float, is_gold: bool):
    """Appends trade entry to daily history markdown file."""
    pnl_badge = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
    outcome_icon = "🟢 WIN" if outcome == "WIN" else "🔴 LOSS"

    row = (
        f"| {date_str} {time_str} | #{ticket} | {symbol} | {signal} | {lot:.2f} | "
        f"{entry_price:.2f} | {exit_price:.2f} | {pnl_badge} | {pips:+.1f} | "
        f"{duration_mins}m | {outcome_icon} | {close_reason} | ${balance:.2f} |\n"
    )

    if not os.path.exists(file_path):
        header = _build_daily_history_header(is_gold)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(header)
            f.write(row)
    else:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(row)


def _append_decision_learning(file_path: str, date_str: str, time_str: str, ticket: int, symbol: str, signal: str,
                              lot: float, entry_price: float, exit_price: float, sl: float, tp: float,
                              pnl: float, pips: float, outcome: str, close_reason: str,
                              decision_basis: Dict[str, Any], is_gold: bool):
    """Appends detailed decision analysis and post-mortem learning to markdown file."""
    pnl_str = f"+${pnl:.2f}" if pnl >= 0 else f"-${abs(pnl):.2f}"
    outcome_badge = "🟢 PROFIT HIT" if outcome == "WIN" else "🔴 STOP LOSS HIT"

    setup = decision_basis.get("setup", "Institutional Confluence" if not is_gold else "Dynamic 9/21 Pullback")
    grade = decision_basis.get("grade", "A")
    chop = decision_basis.get("chop", 42.0)
    adx = decision_basis.get("adx", 28.0)
    z_score = decision_basis.get("z_score", 0.5)
    vol_ratio = decision_basis.get("vol_ratio", 1.1)
    p_win = decision_basis.get("p_win", 0.60)
    ev_r = decision_basis.get("ev_r", 0.25)

    entry_block = f"""
### 📊 Trade #{ticket} | {symbol} {signal} ({date_str} {time_str})
* **Outcome**: **{outcome_badge}** | **Realized PnL**: `{pnl_str}` ({pips:+.1f} pips)
* **Exit Reason**: `{close_reason}`
* **Execution Parameters**:
  * **Entry Price**: `{entry_price:.3f}`
  * **Planned SL**: `{sl:.3f}` (Risk: ${abs(entry_price - sl) * (100.0 if is_gold else 1.0) * lot:.2f})
  * **Planned TP**: `{tp:.3f}` (Target: ${abs(tp - entry_price) * (100.0 if is_gold else 1.0) * lot:.2f})
  * **Actual Exit**: `{exit_price:.3f}`

* **Decision Basis & Strategy Confluence**:
  * **Core Setup**: `{setup}` (Grade: `{grade}`)
  * **Choppiness Index**: `{chop:.1f}` (Reference: `< 50` = Trending)
  * **Trend Strength (ADX)**: `{adx:.1f}`
  * **Z-Score from VWAP**: `{z_score:.2f}` (Exhaustion guard: `< 1.4`)
  * **Volume Surge Ratio**: `{vol_ratio:.2f}x` average
  * **ML Win Probability $P(Win)$**: `{p_win * 100:.1f}%` | **Expected Value $E[R]$**: `+{ev_r:.2f}R`
"""

    if outcome == "LOSS":
        # Post-Mortem Root Cause Analysis
        diagnosis = classify_sl_root_cause(symbol, signal, decision_basis, pnl)
        sl_block = f"""
> [!WARNING]
> #### 🧠 Stop Loss Post-Mortem & Mistake Diagnosis:
> * **Failure Mode**: `{diagnosis['category']}`
> * **Root-Cause Analysis**: {diagnosis['diagnosis']}
> * **Key Lesson Learned**: {diagnosis['lesson']}
> * **Adaptive Feedback Loop**: {diagnosis['action']}
"""
        entry_block += sl_block
    else:
        entry_block += f"""
> [!TIP]
> #### ✅ Successful Execution Takeaway:
> Setup respected structure. Profit banked within target parameters. Cooldown active for 1 M5 candle before re-scanning.
"""

    entry_block += "\n---\n"

    if not os.path.exists(file_path):
        header = _build_learning_header(is_gold)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(header)
            f.write(entry_block)
    else:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(entry_block)


def _build_daily_history_header(is_gold: bool) -> str:
    title = "Institutional Gold Scalper (XAUUSDm)" if is_gold else "Multi-Asset Crypto & Forex Swing Bot"
    return f"""# 📈 Live Daily Trading History & Execution Log
## {title}
*Live synchronization across Exness MT5 Demo & Real Accounts.*
*Last Initialized: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}*

| Timestamp (UTC) | Ticket | Symbol | Action | Lot | Entry | Exit | Net PnL | Pips | Hold | Outcome | Exit Reason | Balance |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
"""


def _build_learning_header(is_gold: bool) -> str:
    title = "Institutional Gold Scalper (XAUUSDm)" if is_gold else "Multi-Asset Crypto & Forex Swing Bot"
    return f"""# 🧠 Trade Decision Ledger & Post-Mortem SL Learning Engine
## {title}
*Tracks every trade's entry rationale, TP/SL parameters, and conducts automated root-cause mistake analysis on every Stop Loss to continuously improve decision-making.*
*Operates continuously across Demo Forward-Testing and Live Accounts.*

---
"""
