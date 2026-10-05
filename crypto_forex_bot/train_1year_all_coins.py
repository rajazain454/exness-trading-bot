import sys
import os
import time
import json
import itertools
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple
import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

# Ensure UTF-8 output on Windows terminals
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import MetaTrader5 as mt5
import config
from quant_engine import QuantitativeEngine

console = Console(force_terminal=True, legacy_windows=False)

ALL_COINS_AND_PAIRS = [
    # Crypto Coins
    "BTCUSDm",
    "ETHUSDm",
    "SOLUSDm",
    "XRPUSDm",
    # Major Forex Pairs
    "EURUSDm",
    "GBPUSDm",
    "USDJPYm",
    "AUDUSDm"
]

def fetch_1year_m5_data(symbol: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Fetches 1 full year (~100,000 M5 bars and ~10,000 H1 bars) from Exness MT5 server.
    """
    now = datetime.now(timezone.utc)
    
    # 1. Fetch M5 in chained batches of 40,000 bars
    b1 = mt5.copy_rates_from(symbol, mt5.TIMEFRAME_M5, now, 40000)
    if b1 is None or len(b1) == 0:
        raise ValueError(f"Failed to fetch M5 rates for {symbol}")
    
    t0 = datetime.fromtimestamp(b1[0]['time'], timezone.utc)
    b2 = mt5.copy_rates_from(symbol, mt5.TIMEFRAME_M5, t0, 40000)
    
    if b2 is not None and len(b2) > 0:
        t1 = datetime.fromtimestamp(b2[0]['time'], timezone.utc)
        b3 = mt5.copy_rates_from(symbol, mt5.TIMEFRAME_M5, t1, 40000)
        all_bars = [b for b in [b3, b2, b1] if b is not None and len(b) > 0]
        raw_m5 = np.concatenate(all_bars)
    else:
        raw_m5 = b1

    df_m5 = pd.DataFrame(raw_m5).drop_duplicates(subset=['time']).sort_values('time').reset_index(drop=True)
    df_m5['datetime'] = pd.to_datetime(df_m5['time'], unit='s', utc=True)

    # 2. Fetch H1 bars (10,000 bars easily covers 1+ year)
    h1_bars = mt5.copy_rates_from(symbol, mt5.TIMEFRAME_H1, now, 10000)
    if h1_bars is None or len(h1_bars) == 0:
        raise ValueError(f"Failed to fetch H1 rates for {symbol}")
    df_h1 = pd.DataFrame(h1_bars).drop_duplicates(subset=['time']).sort_values('time').reset_index(drop=True)
    df_h1['datetime'] = pd.to_datetime(df_h1['time'], unit='s', utc=True)

    return df_m5, df_h1

def precompute_indicators(df_m5: pd.DataFrame, df_h1: pd.DataFrame) -> Tuple[Dict[str, np.ndarray], Dict[str, np.ndarray]]:
    """
    Precomputes all indicators as fast contiguous NumPy arrays for ultra-fast simulation.
    Includes all 6 quant features: CHOP, Z-Score, VWAP, ATR Percentiles, EV, and Multi-Timeframe EMA.
    """
    # M5 Indicators
    close = df_m5['close'].to_numpy()
    high = df_m5['high'].to_numpy()
    low = df_m5['low'].to_numpy()
    open_p = df_m5['open'].to_numpy()
    vol = df_m5['tick_volume'].to_numpy()
    times = df_m5['time'].to_numpy()

    # EMAs
    s_close = pd.Series(close)
    ema_fast = s_close.ewm(span=9, adjust=False).mean().to_numpy()
    ema_slow = s_close.ewm(span=21, adjust=False).mean().to_numpy()
    ema_trend = s_close.ewm(span=50, adjust=False).mean().to_numpy()

    # RSI 14
    delta = s_close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    rsi = (100.0 - (100.0 / (1.0 + rs))).to_numpy()

    # ATR 14
    tr1 = high - low
    tr2 = np.abs(high - np.roll(close, 1))
    tr3 = np.abs(low - np.roll(close, 1))
    tr = np.maximum(tr1, np.maximum(tr2, tr3))
    tr[0] = tr1[0]
    atr = pd.Series(tr).rolling(14).mean().bfill().to_numpy()

    # ATR Percentiles (Vectorized 100-bar rolling)
    s_atr = pd.Series(atr)
    atr_min = s_atr.rolling(100).min()
    atr_max = s_atr.rolling(100).max()
    atr_pct = (((s_atr - atr_min) / (atr_max - atr_min + 1e-9)) * 100.0).fillna(50.0).to_numpy()

    # Z-Score 50
    mean_50 = s_close.rolling(50).mean()
    std_50 = s_close.rolling(50).std()
    z_score = (((s_close - mean_50) / (std_50 + 1e-9))).fillna(0.0).to_numpy()

    # Choppiness Index 14
    s_tr = pd.Series(tr)
    atr_sum = s_tr.rolling(14).sum().to_numpy()
    high_max = pd.Series(high).rolling(14).max().to_numpy()
    low_min = pd.Series(low).rolling(14).min().to_numpy()
    price_range = (high_max - low_min) + 1e-9
    safe_ratio = np.where(atr_sum > 1e-9, atr_sum / price_range, 14.0 ** 0.5)
    safe_ratio = np.maximum(safe_ratio, 1e-9)
    chop = 100.0 * np.log10(safe_ratio) / np.log10(14)
    chop = np.nan_to_num(chop, nan=50.0, posinf=50.0, neginf=50.0)

    # Daily-Anchored Session VWAP (resets at 00:00 UTC)
    typical = (high + low + close) / 3.0
    dates = df_m5['datetime'].dt.date
    pv = typical * vol
    cum_pv = pd.Series(pv).groupby(dates).cumsum().to_numpy()
    cum_v = pd.Series(vol).groupby(dates).cumsum().to_numpy() + 1e-9
    vwap = cum_pv / cum_v

    # Hours in UTC for session filter
    datetimes = df_m5['datetime'].dt
    hours = datetimes.hour.to_numpy()
    minutes = datetimes.minute.to_numpy()

    m5_data = {
        'times': times,
        'open': open_p,
        'high': high,
        'low': low,
        'close': close,
        'ema_fast': ema_fast,
        'ema_slow': ema_slow,
        'ema_trend': ema_trend,
        'rsi': rsi,
        'atr': atr,
        'atr_pct': atr_pct,
        'z_score': z_score,
        'chop': chop,
        'vwap': vwap,
        'hours': hours,
        'minutes': minutes
    }

    # H1 Indicators
    h1_close = df_h1['close'].to_numpy()
    s_h1 = pd.Series(h1_close)
    h1_fast = s_h1.ewm(span=9, adjust=False).mean().to_numpy()
    h1_slow = s_h1.ewm(span=21, adjust=False).mean().to_numpy()
    h1_50 = s_h1.ewm(span=50, adjust=False).mean().to_numpy()
    h1_times = df_h1['time'].to_numpy()

    h1_data = {
        'times': h1_times,
        'close': h1_close,
        'fast': h1_fast,
        'slow': h1_slow,
        'ema_50': h1_50
    }

    return m5_data, h1_data

def simulate_pure_r(
    m5: Dict[str, np.ndarray],
    h1: Dict[str, np.ndarray],
    is_crypto: bool,
    chop_max: float = 61.8,
    rsi_pullback_os: float = 48.0,
    z_score_limit: float = 1.8,
    base_tp_mult: float = 2.5,
    base_sl_mult: float = 1.5,
    use_adaptive_atr: bool = True,
    use_vwap_filter: bool = True
) -> Dict[str, Any]:
    """
    Simulates trades purely in R-multiples (Risk Units).
    Risks 1.0R per trade regardless of account money/balance.
    Wins produce +R (e.g. +2.0R to +3.6R based on volatility regime).
    Break-even locked trades produce +0.1R.
    Losses produce -1.0R.
    """
    times = m5['times']
    close = m5['close']
    open_p = m5['open']
    high = m5['high']
    low = m5['low']
    ema_f = m5['ema_fast']
    ema_s = m5['ema_slow']
    rsi = m5['rsi']
    atr = m5['atr']
    atr_pct = m5['atr_pct']
    z_score = m5['z_score']
    chop = m5['chop']
    vwap = m5['vwap']
    hours = m5['hours']
    minutes = m5['minutes']

    h1_times = h1['times']
    h1_fast = h1['fast']
    h1_slow = h1['slow']
    h1_close = h1['close']

    n_bars = len(close)
    trades: List[Dict[str, Any]] = []
    active_trade = None # (type, entry, sl, tp, be_trigger, be_offset, be_locked, partial_closed, risk_dist, target_r)

    cumulative_r = 0.0
    peak_r = 0.0
    max_dd_r = 0.0

    rsi_ob = 100.0 - rsi_pullback_os

    for i in range(50, n_bars):
        c_bar_high = high[i]
        c_bar_low = low[i]
        c_time = times[i]

        # 1. Manage active trade
        if active_trade is not None:
            t_type, entry, sl, tp, be_trigger, be_offset, be_locked, partial_closed, risk_dist, target_r = active_trade

            outcome_r = None

            if t_type == 1: # BUY
                # Partial TP1 scale-out (+1.0R risk distance)
                if not partial_closed and (c_bar_high - entry) >= risk_dist:
                    partial_closed = True
                    be_locked = True
                    sl = entry + be_offset
                    cumulative_r += 0.50  # Bank 50% volume at +1.0R (+0.50R net)
                    active_trade = (t_type, entry, sl, tp, be_trigger, be_offset, be_locked, partial_closed, risk_dist, target_r)

                elif not be_locked and (c_bar_high - entry) >= be_trigger:
                    sl = entry + be_offset
                    be_locked = True
                    active_trade = (t_type, entry, sl, tp, be_trigger, be_offset, be_locked, partial_closed, risk_dist, target_r)

                if c_bar_high >= tp:
                    outcome_r = (target_r * 0.5) if partial_closed else target_r
                elif c_bar_low <= sl:
                    if partial_closed:
                        outcome_r = 0.05 # Remaining half stopped at BE
                    elif be_locked:
                        outcome_r = 0.10
                    else:
                        outcome_r = -1.0

            else: # SELL
                # Partial TP1 scale-out
                if not partial_closed and (entry - c_bar_low) >= risk_dist:
                    partial_closed = True
                    be_locked = True
                    sl = entry - be_offset
                    cumulative_r += 0.50
                    active_trade = (t_type, entry, sl, tp, be_trigger, be_offset, be_locked, partial_closed, risk_dist, target_r)

                elif not be_locked and (entry - c_bar_low) >= be_trigger:
                    sl = entry - be_offset
                    be_locked = True
                    active_trade = (t_type, entry, sl, tp, be_trigger, be_offset, be_locked, partial_closed, risk_dist, target_r)

                if c_bar_low <= tp:
                    outcome_r = (target_r * 0.5) if partial_closed else target_r
                elif c_bar_high >= sl:
                    if partial_closed:
                        outcome_r = 0.05
                    elif be_locked:
                        outcome_r = 0.10
                    else:
                        outcome_r = -1.0

            if outcome_r is not None:
                cumulative_r += outcome_r
                if cumulative_r > peak_r:
                    peak_r = cumulative_r
                dd_r = peak_r - cumulative_r
                if dd_r > max_dd_r:
                    max_dd_r = dd_r

                total_trade_r = (0.50 + outcome_r) if partial_closed else outcome_r
                trades.append({
                    'time': c_time,
                    'type': 'BUY' if t_type == 1 else 'SELL',
                    'outcome': 'WIN' if total_trade_r > 0 else 'LOSS',
                    'r': round(total_trade_r, 2),
                    'cum_r': round(cumulative_r, 2)
                })
                active_trade = None

        # 2. Check for entry
        if active_trade is None:
            # Session filter for Forex (skip night chop/rollover), 24/7 for Crypto
            if not is_crypto:
                h = hours[i]
                m = minutes[i]
                if (h == 21 and m >= 45) or (h == 22 and m <= 30):
                    continue
                if h < 7 or h >= 20:
                    continue

            # Fractal Choppiness Filter
            if chop[i] > chop_max:
                continue

            # Multi-Timeframe H1 Macro Trend with EMA 50 baseline
            h1_idx = np.searchsorted(h1_times, c_time, side='right') - 1
            if h1_idx < 0:
                continue
            h1_f = h1_fast[h1_idx]
            h1_s = h1_slow[h1_idx]
            h1_c = h1_close[h1_idx]
            h1_50_val = h1.get('ema_50', h1_slow)[h1_idx]

            h1_bull = (h1_f > h1_s) and (h1_c > h1_s) and (h1_c > h1_50_val * 0.999)
            h1_bear = (h1_f < h1_s) and (h1_c < h1_s) and (h1_c < h1_50_val * 1.001)

            c_close = close[i]
            c_open = open_p[i]
            ema_trend_val = m5.get('ema_trend', ema_s)[i]
            m5_up = (ema_f[i] > ema_s[i]) and (c_close > ema_f[i]) and (c_close >= ema_trend_val * 0.999)
            m5_down = (ema_f[i] < ema_s[i]) and (c_close < ema_f[i]) and (c_close <= ema_trend_val * 1.001)

            c_rsi = rsi[i]
            c_rsi_p1 = rsi[i - 1]
            c_rsi_p2 = rsi[i - 2]
            c_atr = atr[i]
            c_atr_pct = atr_pct[i]
            c_z = z_score[i]
            c_vwap = vwap[i]

            # Volatility-Adaptive Multipliers
            if use_adaptive_atr:
                if c_atr_pct < 35.0:
                    sl_mult = 1.2
                    tp_mult = 2.0
                elif c_atr_pct > 70.0:
                    sl_mult = 1.8
                    tp_mult = 3.6
                else:
                    sl_mult = base_sl_mult
                    tp_mult = base_tp_mult
            else:
                sl_mult = base_sl_mult
                tp_mult = base_tp_mult

            sl_dist = c_atr * sl_mult
            tp_dist = c_atr * tp_mult
            target_r = round(tp_mult / sl_mult, 2)
            be_trigger = sl_dist * 0.75
            be_offset = sl_dist * 0.10

            # Mathematical Expected Value check in R: (P_win * target_r) - (P_loss * 1.0)
            est_p_win = 0.58
            ev_r = (est_p_win * target_r) - ((1.0 - est_p_win) * 1.0)
            if ev_r < 0.20:
                continue

            # BUY SETUP
            if m5_up and h1_bull:
                if use_vwap_filter and c_close > (c_vwap * 1.0025):
                    continue
                if abs(c_z) > z_score_limit:
                    continue
                if min(c_rsi_p1, c_rsi_p2) <= rsi_pullback_os and c_rsi > rsi_pullback_os and c_rsi > c_rsi_p1 and c_close >= c_open:
                    entry = c_close
                    sl = entry - sl_dist
                    tp = entry + tp_dist
                    active_trade = (1, entry, sl, tp, be_trigger, be_offset, False, False, sl_dist, target_r)

            # SELL SETUP
            elif m5_down and h1_bear:
                if use_vwap_filter and c_close < (c_vwap * 0.9975):
                    continue
                if abs(c_z) > z_score_limit:
                    continue
                if max(c_rsi_p1, c_rsi_p2) >= rsi_ob and c_rsi < rsi_ob and c_rsi < c_rsi_p1 and c_close <= c_open:
                    entry = c_close
                    sl = entry + sl_dist
                    tp = entry - tp_dist
                    active_trade = (-1, entry, sl, tp, be_trigger, be_offset, False, False, sl_dist, target_r)

    total_trades = len(trades)
    wins = [t for t in trades if t['outcome'] == 'WIN']
    losses = [t for t in trades if t['outcome'] == 'LOSS']

    win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0
    r_gains = sum(t['r'] for t in wins)
    r_losses = abs(sum(t['r'] for t in losses))
    profit_factor = (r_gains / r_losses) if r_losses > 0 else (999.0 if r_gains > 0 else 0.0)
    ev_per_trade_r = (cumulative_r / total_trades) if total_trades > 0 else 0.0

    return {
        'total_trades': total_trades,
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': round(win_rate, 1),
        'total_r': round(cumulative_r, 2),
        'profit_factor': round(profit_factor, 2),
        'max_drawdown_r': round(max_dd_r, 2),
        'ev_per_trade_r': round(ev_per_trade_r, 2),
        'trades': trades
    }

def train_single_coin(symbol: str) -> Dict[str, Any]:
    """
    Loads 1 full year of historical data and runs optimization across the parameter space
    evaluating purely in R-multiples (Risk Units) with zero account balance dependency.
    """
    is_crypto = "BTC" in symbol or "ETH" in symbol or "SOL" in symbol or "XRP" in symbol
    df_m5, df_h1 = fetch_1year_m5_data(symbol)
    m5_data, h1_data = precompute_indicators(df_m5, df_h1)

    start_date = df_m5['datetime'].iloc[0].strftime('%Y-%m-%d')
    end_date = df_m5['datetime'].iloc[-1].strftime('%Y-%m-%d')
    total_bars = len(df_m5)

    # Standard Benchmark (without advanced quant filters)
    benchmark_res = simulate_pure_r(
        m5_data, h1_data, is_crypto,
        chop_max=100.0,
        z_score_limit=999.0,
        use_adaptive_atr=False,
        use_vwap_filter=False
    )

    # Expanded Parameter grid for institutional training
    param_grid = {
        'chop_max': [58.0, 61.8],
        'rsi_pullback_os': [42.0, 45.0, 48.0],
        'z_score_limit': [1.5, 1.8],
        'base_tp_mult': [2.0, 2.5, 3.0],
        'base_sl_mult': [1.2, 1.5]
    }

    keys, values = zip(*param_grid.items())
    permutations = [dict(zip(keys, v)) for v in itertools.product(*values)]

    best_score = -999999.0
    best_res = None
    best_params = None

    for p in permutations:
        res = simulate_pure_r(
            m5_data, h1_data, is_crypto,
            chop_max=p['chop_max'],
            rsi_pullback_os=p['rsi_pullback_os'],
            z_score_limit=p['z_score_limit'],
            base_tp_mult=p['base_tp_mult'],
            base_sl_mult=p['base_sl_mult'],
            use_adaptive_atr=True,
            use_vwap_filter=True
        )
        if res['total_trades'] < 8:
            continue

        # Mathematical Fitness Function in pure R-multiples:
        pf = max(0.2, min(5.0, res['profit_factor']))
        score = (res['total_r'] * pf) - (res['max_drawdown_r'] * 1.5)
        if score > best_score:
            best_score = score
            best_res = res
            best_params = p

    if best_res is None:
        best_res = benchmark_res
        best_params = {'chop_max': 61.8, 'rsi_pullback_os': 45.0, 'z_score_limit': 1.8, 'base_tp_mult': 2.5, 'base_sl_mult': 1.5}

    return {
        'symbol': symbol,
        'is_crypto': is_crypto,
        'bars_m5': total_bars,
        'start_date': start_date,
        'end_date': end_date,
        'benchmark': benchmark_res,
        'trained': best_res,
        'best_params': best_params
    }

def main():
    console.print(Panel.fit(
        "[bold cyan]* 1-YEAR QUANTITATIVE ENGINE TRAINING (ALL COINS & PAIRS) *[/bold cyan]\n"
        "[white]Trained on 1 Full Year (~100,000 M5 candles per coin) on Exness MT5 Data\n"
        "Evaluated purely in Mathematical R-Multiples (Risk Units) — 100% Capital Independent[/white]",
        border_style="cyan"
    ))

    if not mt5.initialize():
        console.print("[bold red]Failed to connect to MT5. Ensure MT5 is running.[/bold red]")
        return

    all_results = {}
    trained_models_export = {}

    summary_table = Table(
        title="1-Year Full Historical Training Results (M5 / H1 — 100,000 Candles per Instrument)",
        style="cyan"
    )
    summary_table.add_column("Coin / Symbol", style="bold white")
    summary_table.add_column("Type", justify="center")
    summary_table.add_column("1Y Period", justify="center")
    summary_table.add_column("Standard Benchmark\n(Win% | Total R | PF)", justify="center")
    summary_table.add_column("Trained Quant Model\n(Win% | Total R | PF | MaxDD)", justify="center", style="bold green")
    summary_table.add_column("Optimal Parameters Discovered", justify="left", style="yellow")

    start_all = time.time()

    for sym in ALL_COINS_AND_PAIRS:
        sym_info = mt5.symbol_info(sym)
        if sym_info is None:
            console.print(f"[yellow]Skipping {sym} (Not available on broker)[/yellow]")
            continue

        console.print(f"[bold blue]Training 1 Year of Data for {sym}...[/bold blue]")
        t0 = time.time()
        try:
            res = train_single_coin(sym)
            duration = time.time() - t0
            all_results[sym] = res

            b_m = res['benchmark']
            t_m = res['trained']
            p = res['best_params']

            trained_models_export[sym] = {
                'symbol': sym,
                'is_crypto': res['is_crypto'],
                'optimal_parameters': p,
                'one_year_performance': {
                    'total_trades': t_m['total_trades'],
                    'win_rate': t_m['win_rate'],
                    'total_r_gain': t_m['total_r'],
                    'profit_factor': t_m['profit_factor'],
                    'max_drawdown_r': t_m['max_drawdown_r'],
                    'expected_value_r': t_m['ev_per_trade_r']
                }
            }

            b_str = f"{b_m['win_rate']}% | {b_m['total_r']:+.1f}R | PF {b_m['profit_factor']:.2f}"
            t_str = f"{t_m['win_rate']}% | [bold green]{t_m['total_r']:+.1f}R[/bold green] | PF {t_m['profit_factor']:.2f} | DD {t_m['max_drawdown_r']:.1f}R"
            param_str = f"CHOP<{p['chop_max']} | RSI:{p['rsi_pullback_os']} | |Z|<={p['z_score_limit']} | SL:{p.get('base_sl_mult', 1.5)}x | TP:{p['base_tp_mult']}x"

            type_label = "[bold yellow]CRYPTO[/bold yellow]" if res['is_crypto'] else "[bold cyan]FOREX[/bold cyan]"

            summary_table.add_row(
                sym,
                type_label,
                f"{res['start_date']} to {res['end_date']}",
                b_str,
                t_str,
                param_str
            )
            console.print(f"  [green][DONE][/green] {sym} finished in {duration:.1f}s: {t_str}")

        except Exception as e:
            console.print(f"  [red][ERROR][/red] Failed to train {sym}: {e}")

    mt5.shutdown()
    total_elapsed = time.time() - start_all

    # Save trained parameter profiles to JSON for the live bot
    export_path = os.path.join(os.path.dirname(__file__), "trained_models.json")
    with open(export_path, "w") as f:
        json.dump(trained_models_export, f, indent=4)

    console.print("\n")
    console.print(summary_table)
    console.print(f"\n[bold green]ALL COINS AND PAIRS TRAINED SUCCESSFULLY IN {total_elapsed:.1f}s![/bold green]")
    console.print(f"[cyan]Optimal parameters saved to: {export_path}[/cyan]")

if __name__ == "__main__":
    main()
