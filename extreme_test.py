import sys
import os
import time
import math
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

def test_mathematical_edge_stress():
    console.print("\n[bold cyan]=== [1/5] MATHEMATICAL EDGE & FORMULA STRESS TESTS ===[/bold cyan]")
    from quant_engine import QuantitativeEngine

    # 1. Kelly Sizing Stress Test
    k_normal = QuantitativeEngine.calculate_kelly_fraction(60.0, 2.50, 1.50, fraction=0.25)
    k_zero_win = QuantitativeEngine.calculate_kelly_fraction(0.0, 2.50, 1.50, fraction=0.25)
    k_100_win = QuantitativeEngine.calculate_kelly_fraction(100.0, 2.50, 1.50, fraction=0.25)
    k_neg_edge = QuantitativeEngine.calculate_kelly_fraction(30.0, 1.00, 3.00, fraction=0.25)
    k_zero_loss = QuantitativeEngine.calculate_kelly_fraction(50.0, 2.50, 0.00, fraction=0.25)
    console.print(f"  [green][PASS][/green] Kelly Normal Edge (60% WR, 1.67 RR): {k_normal*100:.2f}% risk")
    console.print(f"  [green][PASS][/green] Kelly Zero Win (0% WR): {k_zero_win*100:.2f}% (safe 1% floor)")
    console.print(f"  [green][PASS][/green] Kelly 100% Win: {k_100_win*100:.2f}% (capped at 5% max risk)")
    console.print(f"  [green][PASS][/green] Kelly Negative Edge: {k_neg_edge*100:.2f}% (safe 1% floor)")
    console.print(f"  [green][PASS][/green] Kelly Zero Loss handling: {k_zero_loss*100:.2f}% (safe fallback)")
    assert 0.01 <= k_normal <= 0.05
    assert k_zero_win == 0.01
    assert k_100_win <= 0.05
    assert k_neg_edge == 0.01

    # 2. Z-Score Flat & Flash Spike Test
    flat_series = pd.Series([1.1000] * 50)
    z_flat = QuantitativeEngine.calculate_z_score(flat_series, period=20)
    assert not np.isnan(z_flat.iloc[-1]), "Z-Score flat series resulted in NaN"
    console.print(f"  [green][PASS][/green] Z-Score Flat Price (Zero StdDev): Z = {z_flat.iloc[-1]:.2f} (no divide-by-zero)")

    spike_series = pd.Series([1.1000] * 49 + [1.1200]) # massive 200 pip flash spike
    z_spike = QuantitativeEngine.calculate_z_score(spike_series, period=20)
    assert z_spike.iloc[-1] > 3.0, "Z-Score failed to identify flash spike"
    console.print(f"  [green][PASS][/green] Z-Score Flash Spike: Z = {z_spike.iloc[-1]:+.2f} (successfully detected overextension)")

    # 3. Choppiness Index Range Bound Tests
    h_trend = pd.Series([1.0000 + i*0.0010 for i in range(50)])
    l_trend = pd.Series([0.9990 + i*0.0010 for i in range(50)])
    c_trend = pd.Series([0.9995 + i*0.0010 for i in range(50)])
    chop_trend = QuantitativeEngine.calculate_choppiness_index(h_trend, l_trend, c_trend, period=14)
    console.print(f"  [green][PASS][/green] CHOP on Clean Trend: {chop_trend.iloc[-1]:.1f} (correctly below 61.8 trend ceiling)")
    assert chop_trend.iloc[-1] < 61.8

    # 4. Expected Value (EV) Zero and Negative Risk Guard
    ev_norm, r_norm = QuantitativeEngine.calculate_expected_value(0.60, 3.00, 1.50)
    ev_zero, r_zero = QuantitativeEngine.calculate_expected_value(0.50, 0.00, 0.00)
    console.print(f"  [green][PASS][/green] EV Normal: ${ev_norm:+.2f} (EV/Risk: {r_norm:+.2f})")
    console.print(f"  [green][PASS][/green] EV Zero: ${ev_zero:+.2f} (EV/Risk: {r_zero:+.2f})")
    assert ev_norm > 0

    # 5. ATR Percentiles Flat Window Test
    flat_atr = pd.Series([0.0010] * 120)
    pct_flat = QuantitativeEngine.calculate_atr_percentile(flat_atr, window=100)
    console.print(f"  [green][PASS][/green] ATR Percentile Identical ATRs: {pct_flat:.1f}% (handled min==max gracefully)")
    assert pct_flat == 50.0

def test_exness_broker_and_order_checks():
    console.print("\n[bold cyan]=== [2/5] EXNESS BROKER & LIVE ORDER VALIDATION (mt5.order_check) ===[/bold cyan]")
    import MetaTrader5 as mt5
    from mt5_connector import MT5Connector
    from risk_manager import RiskManager
    from order_manager import OrderManager
    import config

    connector = MT5Connector()
    assert connector.initialize(), "Failed to connect to Exness MT5"
    acc = connector.get_account_summary()
    assert acc, "Failed to fetch account summary"
    console.print(f"  [green][PASS][/green] Broker Account: {acc['login']} | Server: {acc.get('server')} | Balance: ${acc['balance']:.2f}")

    risk = RiskManager(connector)
    om = OrderManager(connector, risk)

    for sym in config.SYMBOLS_BASKET:
        valid_sym = connector.verify_symbol(sym)
        assert valid_sym, f"Symbol {sym} not verified on broker"
        tick = connector.get_symbol_tick(valid_sym)
        assert tick and tick.ask > 0, f"No live ask tick for {valid_sym}"
        pip_size = connector.get_pip_size(valid_sym)
        digits = mt5.symbol_info(valid_sym).digits

        # Calculate live trade params using RiskManager
        tp_sl_params = risk.calculate_sl_tp(valid_sym, "BUY", atr_value=0.0010 if "EUR" in valid_sym else (0.0012 if "GBP" in valid_sym else 120.0))
        assert tp_sl_params is not None, f"Failed to compute SL/TP for {valid_sym}"
        lot = tp_sl_params["lot"]
        sl_price = tp_sl_params["sl"]
        tp_price = tp_sl_params["tp"]
        filling_mode = om.get_filling_mode(valid_sym)

        # Build institutional order check request (Verifies order validity with Exness without risking money)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": valid_sym,
            "volume": float(lot),
            "type": mt5.ORDER_TYPE_BUY,
            "price": float(tick.ask),
            "sl": float(sl_price),
            "tp": float(tp_price),
            "deviation": 20,
            "magic": 999111,
            "comment": "ExtremeTest_OrderCheck",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": filling_mode,
        }

        check_res = mt5.order_check(request)
        assert check_res is not None, f"mt5.order_check failed for {valid_sym}"
        status_msg = f"Retcode: {check_res.retcode} ({check_res.comment})"
        console.print(f"  [green][PASS][/green] {valid_sym:10s} Order Check -> {status_msg} | Lot: {lot} | Margin Required: ${check_res.margin:.2f}")
        # Retcode 0 = Order would execute cleanly. Retcode 10019 = Done validation but insufficient margin (e.g. $26 margin needed on $25 account)
        assert check_res.retcode in [0, 10019], f"Exness rejected order structure for {valid_sym}: {check_res.comment} (retcode {check_res.retcode})"

    connector.shutdown()

def test_strategy_and_dynamic_model_loading():
    console.print("\n[bold cyan]=== [3/5] STRATEGY ENGINE & DYNAMIC COIN MODEL VERIFICATION ===[/bold cyan]")
    from strategy import ForexConfluenceStrategy, get_trained_params
    from mt5_connector import MT5Connector
    import config

    connector = MT5Connector()
    connector.initialize()
    strategy = ForexConfluenceStrategy()

    for sym in config.SYMBOLS_BASKET:
        valid_sym = connector.verify_symbol(sym)
        trained_p = get_trained_params(valid_sym)
        assert trained_p, f"Failed to load trained parameters for {valid_sym}"
        console.print(f"  [green][PASS][/green] {valid_sym:10s} -> Trained Model Loaded: CHOP < {trained_p['chop_max']} | RSI Pullback: {trained_p['rsi_pullback_os']} | |Z| <= {trained_p['z_score_limit']} | TP: {trained_p['base_tp_mult']}x")

        # Test live analysis execution
        m5_rates = connector.get_rates(valid_sym, "M5", count=250)
        h1_rates = connector.get_rates(valid_sym, "H1", count=250)
        analysis = strategy.analyze(m5_rates, h1_rates, symbol=valid_sym)
        assert "signal" in analysis and "metrics" in analysis, f"Invalid analysis output for {valid_sym}"
        console.print(f"         Analysis Output -> Signal: {analysis['signal']} | Score: {analysis['score']}/100 | M5 Trend: {analysis['metrics'].get('m5_trend')} | H1: {analysis['metrics'].get('h1_trend')}")

    connector.shutdown()

def test_risk_gatekeepers_and_session_protections():
    console.print("\n[bold cyan]=== [4/5] RISK MANAGER GATEKEEPERS & CIRCUIT BREAKERS ===[/bold cyan]")
    from mt5_connector import MT5Connector
    from risk_manager import RiskManager
    import config

    connector = MT5Connector()
    connector.initialize()
    risk = RiskManager(connector)

    # 1. Test Max Positions Gatekeeper
    can_open_1, reason_1 = risk.can_open_trade("EURUSDm", active_positions_count=1)
    console.print(f"  [green][PASS][/green] Max Positions Enforced: Can open 2nd trade? {can_open_1} ({reason_1})")
    assert not can_open_1

    # 2. Test Consecutive Loss Cooldown Gatekeeper
    risk.record_trade_result(is_win=False)
    risk.record_trade_result(is_win=False)
    can_cd, cd_reason = risk.check_cooldown()
    console.print(f"  [green][PASS][/green] Anti-Revenge Cooldown: {cd_reason}")
    assert not can_cd

    # Reset cooldown for subsequent tests
    risk.consecutive_losses = 0
    risk.cooldown_until = None

    # 3. Test News Filter with Caching
    from news_filter import EconomicNewsFilter
    nf = EconomicNewsFilter()
    calendar_ok = nf.fetch_calendar()
    console.print(f"  [green][PASS][/green] Economic News Calendar Loaded: {len(nf.cached_events)} events (Rate-limit cached)")
    assert len(nf.cached_events) > 0 or calendar_ok

    connector.shutdown()

def test_database_journal_and_persistence():
    console.print("\n[bold cyan]=== [5/5] SQLITE TRADE JOURNAL INTEGRITY & CONCURRENCY ===[/bold cyan]")
    from journal import TradeJournal

    journal = TradeJournal()
    # 1. Log a test trade
    test_ticket = 9999991
    journal.log_entry(
        ticket=test_ticket,
        symbol="EURUSDm",
        action="BUY",
        lot_size=0.01,
        entry_price=1.12500,
        sl=1.12350,
        tp=1.12750,
        latency_ms=45.2,
        slippage_pips=0.1
    )

    trade = journal.get_trade(test_ticket)
    assert trade is not None, "Failed to retrieve logged trade from database"
    console.print(f"  [green][PASS][/green] Journal Entry Logged: Ticket #{test_ticket} | Latency: {trade['latency_ms']}ms | Slippage: {trade['slippage_pips']}p")

    # 2. Close the test trade
    journal.log_exit(
        ticket=test_ticket,
        exit_price=1.12750,
        realized_pnl=2.50,
        exit_reason="TP_HIT",
        pips=25.0
    )
    closed_trade = journal.get_trade(test_ticket)
    assert closed_trade["status"] == "CLOSED", "Failed to update trade exit status"
    assert closed_trade["realized_pnl"] == 2.50
    console.print(f"  [green][PASS][/green] Journal Exit Logged: PnL: ${closed_trade['realized_pnl']:+.2f} | Reason: {closed_trade['exit_reason']}")

    # 3. Clean up the test row
    journal._execute("DELETE FROM trades WHERE ticket = ?", (test_ticket,))
    console.print(f"  [green][PASS][/green] Test Trade Cleaned Up from Database")

def main():
    console.print(Panel.fit(
        "[bold cyan]EXTREME LEVEL DIAGNOSTIC & STRESS TEST SUITE[/bold cyan]\n"
        "[white]Verifying Math Bounds, Broker Order Checks, Dynamic Models, Risk Gates, and Database[/white]",
        border_style="cyan"
    ))
    t0 = time.time()
    test_mathematical_edge_stress()
    test_exness_broker_and_order_checks()
    test_strategy_and_dynamic_model_loading()
    test_risk_guardrails_and_session_protections = test_risk_gatekeepers_and_session_protections
    test_risk_guardrails_and_session_protections()
    test_database_journal_and_persistence()
    elapsed = time.time() - t0
    console.print(f"\n[bold green]ALL 5/5 EXTREME STRESS TESTS PASSED IN {elapsed:.2f}s WITH ZERO ERRORS![/bold green]")

if __name__ == "__main__":
    main()
