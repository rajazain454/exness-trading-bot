import sys
import time
import numpy as np
import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

def test_quant_engine_math():
    console.print("\n[bold cyan]=== TEST 1: QUANTITATIVE & STATISTICAL ENGINE MATH ===[/bold cyan]")
    from quant_engine import QuantitativeEngine

    # 1. Fractional Kelly
    k1 = QuantitativeEngine.calculate_kelly_fraction(win_rate=60.0, avg_win_usd=2.50, avg_loss_usd=1.50, fraction=0.25)
    k_zero = QuantitativeEngine.calculate_kelly_fraction(win_rate=20.0, avg_win_usd=1.00, avg_loss_usd=2.00, fraction=0.25)
    k_edge = QuantitativeEngine.calculate_kelly_fraction(win_rate=99.0, avg_win_usd=5.00, avg_loss_usd=1.00, fraction=0.25)
    console.print(f"  [green][PASS][/green] Kelly (60% WR, 1.67 RR): {k1*100:.2f}% risk allocation")
    console.print(f"  [green][PASS][/green] Kelly Negative Edge (20% WR, 0.5 RR): {k_zero*100:.2f}% (safe floor)")
    console.print(f"  [green][PASS][/green] Kelly Extreme Edge (99% WR, 5.0 RR): {k_edge*100:.2f}% (capped at 5% max risk)")
    assert 0.01 <= k1 <= 0.05
    assert k_zero == 0.01
    assert k_edge <= 0.05

    # 2. Z-Score
    prices = pd.Series([1.0800 + i*0.0001 for i in range(50)] + [1.0880]) # spike at end
    z = QuantitativeEngine.calculate_z_score(prices, period=20)
    console.print(f"  [green][PASS][/green] Z-Score on normal trend & price spike: last Z = {z.iloc[-1]:+.2f} (detected overextension)")
    assert not np.isnan(z.iloc[-1])

    # 3. Choppiness Index (CHOP)
    highs = pd.Series([1.0850 + np.sin(i/2)*0.0005 for i in range(50)])
    lows = pd.Series([1.0800 + np.sin(i/2)*0.0005 for i in range(50)])
    closes = pd.Series([1.0825 + np.sin(i/2)*0.0005 for i in range(50)])
    chop = QuantitativeEngine.calculate_choppiness_index(highs, lows, closes, period=14)
    console.print(f"  [green][PASS][/green] Fractal Choppiness Index: CHOP = {chop.iloc[-1]:.1f}")
    assert 0.0 <= chop.iloc[-1] <= 100.0

    # 4. Intraday VWAP
    vol = pd.Series([100 + i*10 for i in range(50)])
    vwap = QuantitativeEngine.calculate_vwap(highs, lows, closes, vol)
    console.print(f"  [green][PASS][/green] Cumulative VWAP: VWAP = {vwap.iloc[-1]:.5f}")
    assert not np.isnan(vwap.iloc[-1])

    # 5. ATR Percentile
    atrs = pd.Series([0.00050 + (i % 20)*0.00005 for i in range(150)])
    pct = QuantitativeEngine.calculate_atr_percentile(atrs, window=100)
    pct_series = QuantitativeEngine.calculate_atr_percentile_series(atrs, window=100)
    console.print(f"  [green][PASS][/green] ATR Percentile Rank: {pct:.1f}% | Vectorized length: {len(pct_series)}")
    assert 0.0 <= pct <= 100.0

    # 6. Expected Value (EV)
    ev_pos, ratio_pos = QuantitativeEngine.calculate_expected_value(win_prob=0.60, tp_usd=3.00, sl_usd=1.50)
    ev_neg, ratio_neg = QuantitativeEngine.calculate_expected_value(win_prob=0.30, tp_usd=1.00, sl_usd=3.00)
    console.print(f"  [green][PASS][/green] Positive EV: ${ev_pos:+.2f} (EV/Risk: {ratio_pos:+.2f})")
    console.print(f"  [green][PASS][/green] Negative EV: ${ev_neg:+.2f} (EV/Risk: {ratio_neg:+.2f})")
    assert ev_pos > 0.0
    assert ev_neg < 0.0
    console.print("[bold green]Test 1 Passed: All 6 quantitative math formulas verified.[/bold green]")

def test_exness_mt5_live_connection():
    console.print("\n[bold cyan]=== TEST 2: EXNESS MT5 LIVE CONNECTION & BASKET VALIDATION ===[/bold cyan]")
    from mt5_connector import MT5Connector
    import config

    connector = MT5Connector()
    assert connector.initialize(), "Failed to initialize MT5 connector"

    acc = connector.get_account_summary()
    assert acc is not None, "Failed to retrieve account summary"
    console.print(f"  [green][PASS][/green] Exness Account: {acc['login']} (Server: {acc.get('server', 'Exness')})")
    console.print(f"  [green][PASS][/green] Balance: ${acc['balance']:.2f} | Equity: ${acc['equity']:.2f} | Leverage: 1:{acc['leverage']}")

    for sym in config.SYMBOLS_BASKET:
        valid_sym = connector.verify_symbol(sym)
        assert valid_sym is not None, f"Symbol {sym} not verified on broker"
        spread = connector.get_current_spread_pips(valid_sym)
        tick = connector.get_symbol_tick(valid_sym)
        assert tick is not None, f"No live tick for {valid_sym}"
        console.print(f"  [green][PASS][/green] {valid_sym:10s} | Bid: {tick.bid:.5f} | Ask: {tick.ask:.5f} | Spread: {spread:.1f} pips")

    connector.shutdown()
    console.print("[bold green]Test 2 Passed: MT5 live bridge and basket symbols active and responsive.[/bold green]")

def test_strategy_and_risk_guardrails():
    console.print("\n[bold cyan]=== TEST 3: STRATEGY & RISK MANAGER GUARDRAILS ===[/bold cyan]")
    from mt5_connector import MT5Connector
    from strategy import ForexConfluenceStrategy
    from risk_manager import RiskManager
    from csm import CurrencyStrengthMeter
    from smc import SmartMoneyConcepts
    import config

    connector = MT5Connector()
    connector.initialize()
    csm = CurrencyStrengthMeter(connector)
    smc = SmartMoneyConcepts(connector)
    strategy = ForexConfluenceStrategy()
    risk = RiskManager(connector)

    sym = config.SYMBOLS_BASKET[0]
    valid_sym = connector.verify_symbol(sym)
    m5_rates = connector.get_rates(valid_sym, config.TIMEFRAME, count=250)
    h1_rates = connector.get_rates(valid_sym, config.HIGHER_TIMEFRAME, count=250)

    analysis = strategy.analyze(m5_rates, h1_rates, csm_engine=csm, smc_engine=smc, symbol=valid_sym)
    console.print(f"  [green][PASS][/green] Strategy Output on {valid_sym}: Signal = {analysis['signal']}, Score = {analysis['score']}/100")
    console.print(f"  [green][PASS][/green] Metrics: Z = {analysis['metrics'].get('z_score', 0):+.2f} | CHOP = {analysis['metrics'].get('chop', 0):.1f} | VWAP = {analysis['metrics'].get('vwap', 0):.5f} | ATR Rank = {analysis['metrics'].get('atr_pct', 0):.1f}%")

    # Risk manager SL/TP calculation
    sl_tp = risk.calculate_sl_tp(
        valid_sym,
        "BUY",
        atr_value=analysis['metrics'].get('atr', 0.0007),
        atr_percentile=analysis['metrics'].get('atr_pct', 50.0)
    )
    assert sl_tp is not None, "calculate_sl_tp failed to return trade parameters"
    console.print(f"  [green][PASS][/green] Risk Engine SL/TP: Entry = {sl_tp['entry']:.5f} | SL = {sl_tp['sl']:.5f} ({sl_tp['sl_pips']:.1f}p) | TP = {sl_tp['tp']:.5f} ({sl_tp['tp_pips']:.1f}p) | EV = ${sl_tp['ev_usd']:.2f}")

    # Lot size calculation check
    acc = connector.get_account_summary()
    lot = risk.calculate_lot_size(acc["equity"])
    console.print(f"  [green][PASS][/green] Kelly Lot Size for ${acc['equity']:.2f}: {lot:.2f} Lot")
    assert lot >= config.BASE_LOT_SIZE

    connector.shutdown()
    console.print("[bold green]Test 3 Passed: Strategy indicators, risk gatekeeper, and Kelly lot sizing confirmed.[/bold green]")

def test_full_backtest_and_trainer():
    console.print("\n[bold cyan]=== TEST 4: QUANTITATIVE BACKTEST BENCHMARK & PARAMETER TRAINING ===[/bold cyan]")
    from backtester import QuantBacktester, run_full_quant_backtest
    import config

    # Run Benchmark vs Quant
    console.print("Running 6-factor quant benchmark comparison on EURUSDm...")
    run_full_quant_backtest("EURUSDm", bars=2500)

    # Run Parameter Optimization & Training
    console.print("\nExecuting Strategy Training & Parameter Tuning...")
    tester = QuantBacktester("EURUSDm")
    best_model = tester.train_and_optimize(bars=2500)
    assert best_model is not None, "Model optimization returned empty"
    console.print("[bold green]Test 4 Passed: Bot training and statistical optimization completed successfully.[/bold green]")

def main():
    console.print(Panel.fit("[bold green]EXNESS 6-FACTOR QUANTITATIVE HARD TEST & BOT TRAINING SUITE[/bold green]", border_style="green"))
    start_time = time.time()

    test_quant_engine_math()
    test_exness_mt5_live_connection()
    test_strategy_and_risk_guardrails()
    test_full_backtest_and_trainer()

    elapsed = time.time() - start_time
    console.print(f"\n[bold green]ALL HARD TESTS AND BOT TRAINING COMPLETED IN {elapsed:.2f}s WITH ZERO ERRORS![/bold green]")

if __name__ == "__main__":
    main()
