import pandas as pd
import numpy as np
from rich.console import Console
from rich.table import Table
import MetaTrader5 as mt5
import itertools
from typing import Dict, Any, List, Tuple, Optional

import config
from mt5_connector import MT5Connector
from strategy import ForexConfluenceStrategy
from quant_engine import QuantitativeEngine

console = Console()

class QuantBacktester:
    """
    Advanced Quantitative Backtesting and Training Engine for Exness.
    Simulates all 6 Quantitative Edges:
    1. Fractional Kelly Criterion Position Sizing
    2. Statistical Z-Score Mean-Reversion Pullback Filter
    3. Volatility-Adaptive ATR Percentile Dynamic R:R
    4. Fractal Choppiness Index (CHOP) Filter
    5. Mathematical Expected Value (EV) Gatekeeper
    6. Intraday VWAP Institutional Discount/Premium Filter
    """

    def __init__(self, symbol: str = "EURUSDm", initial_balance: float = 30.0):
        self.symbol = symbol
        self.initial_balance = initial_balance
        self.connector = MT5Connector()
        self.strategy = ForexConfluenceStrategy()

    def load_data(self, bars: int = 4000) -> Tuple[pd.DataFrame, pd.DataFrame, float]:
        """Loads and precomputes M5 and H1 indicators."""
        if not self.connector.initialize():
            raise ConnectionError("Failed to initialize MT5 for backtest.")

        valid_symbol = self.connector.verify_symbol(self.symbol)
        if not valid_symbol:
            self.connector.shutdown()
            raise ValueError(f"Symbol {self.symbol} not found on broker.")

        pip_size = self.connector.get_pip_size(valid_symbol)
        m5_rates = self.connector.get_rates(valid_symbol, "M5", count=bars)
        h1_rates = self.connector.get_rates(valid_symbol, "H1", count=max(400, bars // 10))
        self.connector.shutdown()

        if m5_rates is None or len(m5_rates) < 250:
            raise ValueError(f"Insufficient historical bars returned for {self.symbol}.")

        df_m5 = self.strategy.calculate_indicators(m5_rates)
        df_h1 = self.strategy.calculate_indicators(h1_rates)

        # Add vectorized ATR percentiles
        df_m5["atr_pct"] = QuantitativeEngine.calculate_atr_percentile_series(pd.Series(df_m5["atr"], dtype=float), window=100)

        return df_m5, df_h1, pip_size

    def simulate(
        self,
        df_m5: pd.DataFrame,
        df_h1: pd.DataFrame,
        pip_size: float,
        chop_max: float = 61.8,
        rsi_oversold: float = 48.0,
        rsi_overbought: float = 52.0,
        z_score_limit: float = 1.8,
        use_kelly: bool = True,
        use_adaptive_atr: bool = True,
        use_ev_filter: bool = True,
        use_vwap_filter: bool = True,
        be_trigger_pips: float = 10.0,
        be_offset_pips: float = 1.0,
        base_sl_mult: float = 1.5,
        base_tp_mult: float = 2.5,
        spread_pips: float = 1.2,
        slippage_pips: float = 0.2
    ) -> Dict[str, Any]:
        """
        Executes a bar-by-bar backtest simulation with given quantitative parameters,
        incorporating realistic broker spread and slippage friction.
        """
        balance = self.initial_balance
        peak_balance = self.initial_balance
        max_drawdown_usd = 0.0

        trades: List[Dict[str, Any]] = []
        active_trade = None

        be_trigger_dist = be_trigger_pips * pip_size
        be_offset_dist = be_offset_pips * pip_size
        spread_dist = spread_pips * pip_size
        slippage_dist = slippage_pips * pip_size

        # Precompute H1 trend index mapping for fast lookups
        h1_times = df_h1["time"].values
        h1_fast = df_h1["ema_fast"].values
        h1_slow = df_h1["ema_slow"].values
        h1_close = df_h1["close"].values

        for i in range(self.strategy.ema_slow + 2, len(df_m5)):
            curr_bar = df_m5.iloc[i]
            prev_bar = df_m5.iloc[i - 1]
            prev2_bar = df_m5.iloc[i - 2]
            bar_time = curr_bar["time"]

            # 1. Manage active trade
            if active_trade is not None:
                trade_type: str = str(active_trade["type"])
                entry_price: float = float(active_trade["entry_price"])
                sl_price: float = float(active_trade["sl"])
                tp_price: float = float(active_trade["tp"])
                lot: float = float(active_trade["lot"])
                be_locked: bool = bool(active_trade["be_locked"])

                high_val: float = float(curr_bar["high"])
                low_val: float = float(curr_bar["low"])

                # Break-Even logic
                if not be_locked:
                    if trade_type == "BUY" and (high_val - entry_price) >= be_trigger_dist:
                        sl_price = entry_price + be_offset_dist
                        active_trade["sl"] = sl_price
                        active_trade["be_locked"] = True
                    elif trade_type == "SELL" and (entry_price - low_val) >= be_trigger_dist:
                        sl_price = entry_price - be_offset_dist
                        active_trade["sl"] = sl_price
                        active_trade["be_locked"] = True

                exit_price: Optional[float] = None
                outcome: Optional[str] = None

                if trade_type == "BUY":
                    if low_val <= sl_price:
                        exit_price = sl_price
                        outcome = "WIN" if sl_price > entry_price else "LOSS"
                    elif high_val >= tp_price:
                        exit_price = tp_price
                        outcome = "WIN"
                elif trade_type == "SELL":
                    if high_val >= sl_price:
                        exit_price = sl_price
                        outcome = "WIN" if sl_price < entry_price else "LOSS"
                    elif low_val <= tp_price:
                        exit_price = tp_price
                        outcome = "WIN"

                if exit_price is not None:
                    pips = (exit_price - entry_price) / pip_size if trade_type == "BUY" else (entry_price - exit_price) / pip_size
                    pip_val = (lot / 0.01) * 0.10
                    pnl_usd = round(pips * pip_val, 2)
                    balance += pnl_usd
                    if balance > peak_balance:
                        peak_balance = balance
                    dd = peak_balance - balance
                    if dd > max_drawdown_usd:
                        max_drawdown_usd = dd

                    trades.append({
                        "time": bar_time,
                        "type": trade_type,
                        "lot": lot,
                        "entry": entry_price,
                        "exit": exit_price,
                        "pips": round(pips, 1),
                        "pnl": pnl_usd,
                        "outcome": outcome,
                        "balance": round(balance, 2)
                    })
                    active_trade = None

            # 2. Check for entry if no trade active
            if active_trade is None:
                close = curr_bar["close"]
                open_p = curr_bar["open"]
                ema_f = curr_bar["ema_fast"]
                ema_s = curr_bar["ema_slow"]
                rsi = curr_bar["rsi"]
                rsi_p1 = prev_bar["rsi"]
                rsi_p2 = prev2_bar["rsi"]
                atr = curr_bar["atr"] if not np.isnan(curr_bar["atr"]) else 0.00070
                atr_pct = curr_bar["atr_pct"] if not np.isnan(curr_bar["atr_pct"]) else 50.0
                chop = curr_bar["chop"] if not np.isnan(curr_bar["chop"]) else 50.0
                z_score = curr_bar["z_score"] if not np.isnan(curr_bar["z_score"]) else 0.0
                vwap = curr_bar["vwap"] if not np.isnan(curr_bar["vwap"]) else close

                # Fractal Choppiness Filter
                if chop > chop_max:
                    continue

                # Multi-Timeframe H1 Macro Trend alignment
                h1_arr = np.asarray(h1_times)
                h1_idx: int = int(np.searchsorted(h1_arr, bar_time, side="right")) - 1
                if h1_idx < 0:
                    continue
                h1_f = float(h1_fast[h1_idx])
                h1_s = float(h1_slow[h1_idx])
                h1_c = float(h1_close[h1_idx])

                h1_bullish = (h1_f > h1_s) and (h1_c > h1_f)
                h1_bearish = (h1_f < h1_s) and (h1_c < h1_f)

                m5_uptrend = (ema_f > ema_s) and (close > ema_f)
                m5_downtrend = (ema_f < ema_s) and (close < ema_f)

                # Volatility-Adaptive ATR Multipliers
                if use_adaptive_atr:
                    if atr_pct < 35.0:
                        sl_mult = 1.2
                        tp_mult = 2.0
                    elif atr_pct > 70.0:
                        sl_mult = 1.8
                        tp_mult = 3.6
                    else:
                        sl_mult = base_sl_mult
                        tp_mult = base_tp_mult
                else:
                    sl_mult = base_sl_mult
                    tp_mult = base_tp_mult

                atr_pips = atr / pip_size
                sl_pips = max(config.MIN_SL_PIPS, min(config.MAX_SL_PIPS, atr_pips * sl_mult))
                tp_pips = round(sl_pips * (tp_mult / sl_mult), 1)
                sl_dist = sl_pips * pip_size
                tp_dist = tp_pips * pip_size

                # Sizing: Kelly vs Fixed compounding
                if use_kelly:
                    # Calculate rolling win rate from last 10 trades if available
                    past_wins = [t for t in trades[-15:] if t["outcome"] == "WIN"]
                    win_r = (len(past_wins) / len(trades[-15:]) * 100.0) if len(trades) >= 5 else 60.0
                    safe_risk_fraction = QuantitativeEngine.calculate_kelly_fraction(
                        win_rate=win_r,
                        avg_win_usd=2.50,
                        avg_loss_usd=1.50,
                        fraction=config.KELLY_FRACTION
                    )
                    risk_budget = balance * safe_risk_fraction
                    units = risk_budget / (sl_pips * 0.10)
                    sim_lot = round(max(config.BASE_LOT_SIZE, units * config.BASE_LOT_SIZE), 2)
                    sim_lot = min(sim_lot, config.MAX_LOT_SIZE)
                else:
                    multiplier = int(balance // config.CAPITAL_PER_001_LOT)
                    sim_lot = round(max(config.BASE_LOT_SIZE, multiplier * config.BASE_LOT_SIZE), 2)
                    sim_lot = min(sim_lot, config.MAX_LOT_SIZE)

                # Mathematical Expected Value (EV) check
                if use_ev_filter:
                    pip_dollar = (sim_lot / 0.01) * 0.10
                    sl_usd = sl_pips * pip_dollar
                    tp_usd = tp_pips * pip_dollar
                    est_win_prob = 0.58
                    ev_usd, _ = QuantitativeEngine.calculate_expected_value(est_win_prob, tp_usd, sl_usd)
                    if ev_usd < config.MIN_EXPECTED_VALUE_USD:
                        continue

                # Signal Evaluation with Z-Score & VWAP
                if m5_uptrend and h1_bullish:
                    # VWAP filter: price near or below VWAP (discount)
                    if use_vwap_filter and close > (vwap * 1.0025):
                        continue
                    # Z-Score pullback check
                    if abs(z_score) > z_score_limit:
                        continue
                    # RSI Pullback trigger
                    if min(rsi_p1, rsi_p2) <= rsi_oversold and rsi > rsi_oversold and rsi > rsi_p1 and close >= open_p:
                        real_entry = close + (spread_dist / 2.0) + slippage_dist
                        active_trade = {
                            "type": "BUY",
                            "lot": sim_lot,
                            "entry_price": real_entry,
                            "sl": round(real_entry - sl_dist, 5),
                            "tp": round(real_entry + tp_dist, 5),
                            "entry_time": bar_time,
                            "be_locked": False
                        }

                elif m5_downtrend and h1_bearish:
                    # VWAP filter: price near or above VWAP (premium)
                    if use_vwap_filter and close < (vwap * 0.9975):
                        continue
                    # Z-Score pullback check
                    if abs(z_score) > z_score_limit:
                        continue
                    # RSI Pullback trigger
                    if max(rsi_p1, rsi_p2) >= rsi_overbought and rsi < rsi_overbought and rsi < rsi_p1 and close <= open_p:
                        real_entry = close - (spread_dist / 2.0) - slippage_dist
                        active_trade = {
                            "type": "SELL",
                            "lot": sim_lot,
                            "entry_price": real_entry,
                            "sl": round(real_entry + sl_dist, 5),
                            "tp": round(real_entry - tp_dist, 5),
                            "entry_time": bar_time,
                            "be_locked": False
                        }

        total_trades = len(trades)
        wins = [t for t in trades if t["outcome"] == "WIN"]
        losses = [t for t in trades if t["outcome"] == "LOSS"]
        win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0
        total_profit = sum(t["pnl"] for t in wins)
        total_loss = abs(sum(t["pnl"] for t in losses))
        profit_factor = (total_profit / total_loss) if total_loss > 0 else (999.0 if total_profit > 0 else 0.0)
        net_pnl = balance - self.initial_balance

        return {
            "symbol": self.symbol,
            "starting_balance": self.initial_balance,
            "final_balance": round(balance, 2),
            "net_pnl": round(net_pnl, 2),
            "return_pct": round((net_pnl / self.initial_balance) * 100.0, 1),
            "total_trades": total_trades,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 1),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_usd": round(max_drawdown_usd, 2),
            "max_drawdown_pct": round((max_drawdown_usd / self.initial_balance) * 100.0, 1),
            "trades": trades
        }

    def train_and_optimize(self, bars: int = 4000) -> Dict[str, Any]:
        """
        Grid search optimization across quantitative parameters to find the highest
        performing statistical parameters for the currency pair.
        """
        console.print(f"[bold magenta]Training & Optimizing Quantitative Model for {self.symbol} ({bars} bars)...[/bold magenta]")
        df_m5, df_h1, pip_size = self.load_data(bars)

        param_grid = {
            "chop_max": [58.0, 61.8, 65.0],
            "rsi_oversold": [45.0, 48.0, 50.0],
            "z_score_limit": [1.5, 1.8, 2.2],
            "base_tp_mult": [2.2, 2.5, 3.0]
        }

        keys, values = zip(*param_grid.items())
        permutations_dicts = [dict(zip(keys, v)) for v in itertools.product(*values)]

        results = []
        for params in permutations_dicts:
            res = self.simulate(
                df_m5=df_m5,
                df_h1=df_h1,
                pip_size=pip_size,
                chop_max=params["chop_max"],
                rsi_oversold=params["rsi_oversold"],
                rsi_overbought=100.0 - params["rsi_oversold"],
                z_score_limit=params["z_score_limit"],
                base_tp_mult=params["base_tp_mult"]
            )
            # Fitness score: Reward high profit factor and return, penalize drawdown
            score = (res["profit_factor"] * 10.0) + res["return_pct"] - (res["max_drawdown_pct"] * 1.5)
            results.append({
                "params": params,
                "metrics": res,
                "score": score
            })

        # Sort by fitness score
        results.sort(key=lambda x: x["score"], reverse=True)
        best = results[0]

        console.print(f"[bold green]Optimization Complete! Top Model Discovered:[/bold green]")
        best_p = best["params"]
        best_m = best["metrics"]

        table = Table(title=f"Optimized Model Results ({self.symbol})", style="magenta")
        table.add_column("Parameter / Metric", style="bold white")
        table.add_column("Optimal Value", style="bold green")

        table.add_row("CHOP Filter Threshold", f"CHOP < {best_p['chop_max']}")
        table.add_row("RSI Pullback Threshold", f"{best_p['rsi_oversold']} / {100.0 - best_p['rsi_oversold']}")
        table.add_row("Z-Score Pullback Limit", f"|Z| <= {best_p['z_score_limit']}")
        table.add_row("Take-Profit Multiplier", f"{best_p['base_tp_mult']}x ATR")
        table.add_row("Win Rate", f"{best_m['win_rate']}% ({best_m['wins']}W / {best_m['losses']}L)")
        table.add_row("Profit Factor", f"{best_m['profit_factor']}")
        table.add_row("Net Profit", f"${best_m['net_pnl']:+.2f} ({best_m['return_pct']:+.1f}%)")
        table.add_row("Max Drawdown", f"${best_m['max_drawdown_usd']:.2f} ({best_m['max_drawdown_pct']:.1f}%)")
        table.add_row("Total Trades", str(best_m["total_trades"]))

        console.print(table)
        return best


def run_full_quant_backtest(symbol: str = "EURUSDm", bars: int = 4000):
    """Runs a benchmark backtest showing Baseline vs Quant Math."""
    tester = QuantBacktester(symbol=symbol)
    try:
        df_m5, df_h1, pip_size = tester.load_data(bars)
    except Exception as e:
        console.print(f"[bold red]Failed to load market data: {e}[/bold red]")
        return

    # 1. Baseline Test (Without Quant Filters)
    console.print(f"[bold yellow]1. Running Standard Multi-Timeframe Benchmark...[/bold yellow]")
    baseline_res = tester.simulate(
        df_m5, df_h1, pip_size,
        chop_max=100.0, # no chop filter
        z_score_limit=999.0, # no z filter
        use_kelly=False,
        use_adaptive_atr=False,
        use_ev_filter=False,
        use_vwap_filter=False
    )

    # 2. Advanced Quant Test (All 6 Edges Active)
    console.print(f"[bold cyan]2. Running 6-Factor Quantitative Edge Simulation...[/bold cyan]")
    quant_res = tester.simulate(
        df_m5, df_h1, pip_size,
        chop_max=config.CHOP_MAX_THRESHOLD,
        z_score_limit=config.Z_SCORE_PULLBACK_MAX,
        use_kelly=config.USE_KELLY_SIZING,
        use_adaptive_atr=config.ADAPTIVE_ATR_PERCENTILE_ENABLED,
        use_ev_filter=config.EXPECTED_VALUE_FILTER_ENABLED,
        use_vwap_filter=config.VWAP_FILTER_ENABLED
    )

    # Render Side-by-Side Comparison Table
    table = Table(title=f"Quantitative Edge Comparison ({symbol} - M5/H1 - {bars} Bars)", style="cyan")
    table.add_column("Metric", style="bold white")
    table.add_column("Standard Benchmark", justify="right")
    table.add_column("6-Factor Quant Edge", justify="right", style="bold green")

    table.add_row("Starting Capital", f"${baseline_res['starting_balance']:.2f}", f"${quant_res['starting_balance']:.2f}")
    table.add_row("Final Balance", f"${baseline_res['final_balance']:.2f}", f"${quant_res['final_balance']:.2f}")
    table.add_row("Net Profit", f"${baseline_res['net_pnl']:+.2f} ({baseline_res['return_pct']:+.1f}%)", f"${quant_res['net_pnl']:+.2f} ({quant_res['return_pct']:+.1f}%)")
    table.add_row("Total Trades", str(baseline_res['total_trades']), str(quant_res['total_trades']))
    table.add_row("Win Rate", f"{baseline_res['win_rate']}%", f"{quant_res['win_rate']}%")
    table.add_row("Profit Factor", f"{baseline_res['profit_factor']:.2f}", f"{quant_res['profit_factor']:.2f}")
    table.add_row("Max Drawdown", f"${baseline_res['max_drawdown_usd']:.2f} ({baseline_res['max_drawdown_pct']:.1f}%)", f"${quant_res['max_drawdown_usd']:.2f} ({quant_res['max_drawdown_pct']:.1f}%)")

    console.print(table)


if __name__ == "__main__":
    run_full_quant_backtest()
