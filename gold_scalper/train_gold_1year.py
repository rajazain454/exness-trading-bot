"""
1-Year Gold (XAUUSDm) Historical Backtester & Parameter Optimizer
Pulls 1 full year of M5 bars from Exness MT5 and runs multi-parameter optimization.
Saves optimal parameters to gold_scalper/gold_models.json.
"""

import sys
import os
import json
from datetime import datetime, timezone
import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Ensure parent directory is in path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import MetaTrader5 as mt5

console = Console()
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "gold_models.json")


def fetch_xau_data(count: int = 70000):
    """Fetches up to 70,000 M5 bars (~1 full year) and H1 bars from Exness MT5."""
    if not mt5.initialize():
        raise RuntimeError("MT5 initialization failed. Ensure MetaTrader 5 is open.")

    now = datetime.now(timezone.utc)
    console.print(f"[cyan]Fetching {count} historical M5 bars for XAUUSDm from Exness MT5...[/cyan]")

    # Fetch in batches if necessary
    raw_m5 = mt5.copy_rates_from("XAUUSDm", mt5.TIMEFRAME_M5, now, count)
    if raw_m5 is None or len(raw_m5) == 0:
        raise ValueError("Failed to fetch M5 rates for XAUUSDm from Exness.")

    df_m5 = pd.DataFrame(raw_m5).drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)
    df_m5["dt"] = pd.to_datetime(df_m5["time"], unit="s", utc=True)

    console.print(f"[green]Successfully loaded {len(df_m5)} M5 bars from {df_m5['dt'].iloc[0].strftime('%Y-%m-%d')} to {df_m5['dt'].iloc[-1].strftime('%Y-%m-%d')}[/green]")

    raw_h1 = mt5.copy_rates_from("XAUUSDm", mt5.TIMEFRAME_H1, now, 8000)
    df_h1 = pd.DataFrame(raw_h1).drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True) if raw_h1 is not None else None

    return df_m5, df_h1


def run_gold_simulation(df: pd.DataFrame, chop_max: float, z_limit: float, sl_mult: float, tp_mult: float) -> dict:
    """Simulates Gold Scalping strategy over historical bars."""
    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    open_p = df["open"].values
    hours = df["dt"].dt.hour.values

    # Precompute indicators
    s_close = pd.Series(close)
    s_high = pd.Series(high)
    s_low = pd.Series(low)

    ema9 = s_close.ewm(span=9, adjust=False).mean().values
    ema21 = s_close.ewm(span=21, adjust=False).mean().values
    ema50 = s_close.ewm(span=50, adjust=False).mean().values

    # ATR 14
    tr1 = s_high - s_low
    tr2 = (s_high - s_close.shift()).abs()
    tr3 = (s_low - s_close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().values

    # RSI 14
    delta = s_close.diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = (100 - (100 / (1 + (gain / (loss + 1e-9))))).values

    # CHOP 14
    atr_sum = tr.rolling(14).sum().values
    h_max = s_high.rolling(14).max().values
    l_min = s_low.rolling(14).min().values
    price_rng = (h_max - l_min) + 1e-9
    safe_ratio = np.where(atr_sum > 1e-9, atr_sum / price_rng, 14.0 ** 0.5)
    safe_ratio = np.maximum(safe_ratio, 1e-9)
    chop = 100.0 * np.log10(safe_ratio) / np.log10(14)
    chop = np.nan_to_num(chop, nan=50.0, posinf=50.0, neginf=50.0)

    # Z-Score 50
    m50 = s_close.rolling(50).mean().values
    std50 = s_close.rolling(50).std().values
    z_score = (close - m50) / (std50 + 1e-9)

    n = len(close)
    trades = []
    in_pos = False
    pos_type = 0
    entry_p = 0.0
    sl_p = 0.0
    tp_p = 0.0
    bars_held = 0

    for i in range(55, n - 1):
        if in_pos:
            bars_held += 1
            # Check exit
            if pos_type == 1:
                if high[i] >= tp_p:
                    trades.append(tp_mult / sl_mult)  # Gain in R
                    in_pos = False
                elif low[i] <= sl_p:
                    trades.append(-1.0)  # Loss in R
                    in_pos = False
                elif bars_held >= 36:  # Time exit
                    r_exit = (close[i] - entry_p) / ((entry_p - sl_p) + 1e-9)
                    trades.append(r_exit)
                    in_pos = False
            elif pos_type == -1:
                if low[i] <= tp_p:
                    trades.append(tp_mult / sl_mult)
                    in_pos = False
                elif high[i] >= sl_p:
                    trades.append(-1.0)
                    in_pos = False
                elif bars_held >= 36:
                    r_exit = (entry_p - close[i]) / ((sl_p - entry_p) + 1e-9)
                    trades.append(r_exit)
                    in_pos = False
            continue

        # Check entry during active hours (07:00 - 18:00 UTC)
        h = hours[i]
        if h < 7 or h >= 18:
            continue

        c_chop = chop[i]
        c_z = z_score[i]
        c_atr = atr[i]
        if np.isnan(c_chop) or np.isnan(c_z) or np.isnan(c_atr) or c_atr <= 0:
            continue

        if c_chop > chop_max or abs(c_z) > z_limit:
            continue

        c = close[i]
        e9 = ema9[i]
        e21 = ema21[i]
        e50 = ema50[i]
        r = rsi[i]
        r_prev = rsi[i - 1]

        # BUY Signal
        if e9 > e21 and c >= e50 * 0.9995:
            if (low[i] <= e9 * 1.0005 or low[i] <= e21 * 1.0008) and (r >= 48.0 and r > r_prev):
                in_pos = True
                pos_type = 1
                entry_p = c
                stop_dist = c_atr * sl_mult
                sl_p = entry_p - stop_dist
                tp_p = entry_p + (stop_dist * tp_mult)
                bars_held = 0
                continue

        # SELL Signal
        if e9 < e21 and c <= e50 * 1.0005:
            if (high[i] >= e9 * 0.9995 or high[i] >= e21 * 0.9992) and (r <= 52.0 and r < r_prev):
                in_pos = True
                pos_type = -1
                entry_p = c
                stop_dist = c_atr * sl_mult
                sl_p = entry_p + stop_dist
                tp_p = entry_p - (stop_dist * tp_mult)
                bars_held = 0
                continue

    if not trades:
        return {"total_trades": 0, "win_rate": 0.0, "total_r": 0.0, "profit_factor": 0.0, "ev": 0.0}

    arr = np.array(trades)
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    total_wins = len(wins)
    total_losses = len(losses)
    total_trades = len(arr)
    win_rate = (total_wins / total_trades) * 100.0 if total_trades > 0 else 0.0
    total_r = float(np.sum(arr))

    gross_profit = float(np.sum(wins)) if total_wins > 0 else 0.0
    gross_loss = float(abs(np.sum(losses))) if total_losses > 0 else 1e-9
    pf = gross_profit / gross_loss

    # Drawdown
    equity_curve = np.cumsum(arr)
    peak = np.maximum.accumulate(equity_curve)
    drawdowns = peak - equity_curve
    max_dd = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0
    ev = total_r / total_trades if total_trades > 0 else 0.0

    return {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 1),
        "total_r": round(total_r, 2),
        "profit_factor": round(pf, 2),
        "max_drawdown_r": round(max_dd, 2),
        "expected_value_r": round(ev, 3)
    }


def optimize_gold():
    """Runs grid optimization over key parameters."""
    df_m5, df_h1 = fetch_xau_data(65000)

    chop_tests = [55.0, 58.0, 61.8]
    z_tests = [1.8, 2.2]
    sl_tests = [1.2, 1.3, 1.5]
    tp_tests = [1.5, 2.0]

    best_config = None
    best_r = -9999.0
    best_stats = None

    table = Table(title="XAUUSDm (Gold) Parameter Optimization Results", style="yellow")
    table.add_column("CHOP", justify="center")
    table.add_column("Z-Lim", justify="center")
    table.add_column("SL Mult", justify="center")
    table.add_column("TP Mult", justify="center")
    table.add_column("Trades", justify="center")
    table.add_column("Win Rate", justify="right")
    table.add_column("Profit Factor", justify="right")
    table.add_column("Total R", justify="right")

    for chop_v in chop_tests:
        for z_v in z_tests:
            for sl_v in sl_tests:
                for tp_v in tp_tests:
                    stats = run_gold_simulation(df_m5, chop_v, z_v, sl_v, tp_v)
                    r_gain = stats["total_r"]
                    wr = stats["win_rate"]
                    pf = stats["profit_factor"]
                    n_tr = stats["total_trades"]

                    color = "green" if r_gain > 0 else "red"
                    table.add_row(
                        str(chop_v),
                        str(z_v),
                        str(sl_v),
                        str(tp_v),
                        str(n_tr),
                        f"{wr}%",
                        f"{pf:.2f}",
                        f"[{color}]{r_gain:+.2f} R[/{color}]"
                    )

                    if r_gain > best_r and n_tr >= 50:
                        best_r = r_gain
                        best_stats = stats
                        best_config = {
                            "chop_max": chop_v,
                            "z_score_limit": z_v,
                            "base_sl_mult": sl_v,
                            "base_tp_mult": tp_v
                        }

    console.print(table)

    if best_config:
        result = {
            "symbol": "XAUUSDm",
            "optimal_parameters": best_config,
            "one_year_performance": best_stats,
            "optimized_at_utc": datetime.now(timezone.utc).isoformat()
        }
        with open(OUTPUT_FILE, "w") as f:
            json.dump(result, f, indent=4)
        console.print(Panel(f"[bold green]Best Configuration Saved to {OUTPUT_FILE}![/bold green]\n"
                            f"Total R Gain: [bold cyan]+{best_stats['total_r']} R[/bold cyan] | "
                            f"Win Rate: [bold yellow]{best_stats['win_rate']}%[/bold yellow] | "
                            f"Profit Factor: [bold white]{best_stats['profit_factor']}[/bold white] | "
                            f"Trades: {best_stats['total_trades']}"))


if __name__ == "__main__":
    optimize_gold()
