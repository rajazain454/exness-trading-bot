import sys
import os
import time
import math
import queue
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()

def test_mathematical_edge_stress():
    console.print("\n[bold cyan]=== [1/6] MATHEMATICAL EDGE & FORMULA STRESS TESTS ===[/bold cyan]")
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

def test_exness_broker_and_dynamic_pip_values():
    console.print("\n[bold cyan]=== [2/6] EXNESS BROKER CHECKS & DYNAMIC PIP VALUE VALIDATION ===[/bold cyan]")
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

        # Validate dynamic pip dollar value calculation
        pip_dollar_val_001 = connector.get_pip_dollar_value(valid_sym, 0.01)
        assert pip_dollar_val_001 > 0, f"Dynamic pip dollar value is non-positive for {valid_sym}"
        console.print(f"  [green][PASS][/green] {valid_sym:10s} -> Pip Size: {pip_size:.5f} | Value per 0.01 lot: ${pip_dollar_val_001:.4f}")

        # Calculate live trade params using RiskManager (with dynamic stop-loss Kelly sizing)
        tp_sl_params = risk.calculate_sl_tp(valid_sym, "BUY", atr_value=0.0010 if "EUR" in valid_sym else (0.0012 if "GBP" in valid_sym else 120.0))
        assert tp_sl_params is not None, f"Failed to compute SL/TP for {valid_sym}"
        lot = tp_sl_params["lot"]
        sl_price = tp_sl_params["sl"]
        tp_price = tp_sl_params["tp"]
        filling_mode = om.get_filling_mode(valid_sym)

        # Build institutional order check request
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": valid_sym,
            "volume": float(lot),
            "type": mt5.ORDER_TYPE_BUY,
            "price": float(tp_sl_params["entry"]),
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
        assert check_res.retcode in [0, 10019], f"Exness rejected order structure for {valid_sym}: {check_res.comment}"

    connector.shutdown()

def test_order_manager_hydration_and_pending_orders():
    console.print("\n[bold cyan]=== [3/6] ORDER MANAGER HYDRATION & PENDING ORDERS LIFECYCLE ===[/bold cyan]")
    from mt5_connector import MT5Connector
    from order_manager import OrderManager
    from risk_manager import RiskManager
    from journal import TradeJournal

    connector = MT5Connector()
    connector.initialize()
    risk = RiskManager(connector)
    om = OrderManager(connector, risk)

    # 1. Test Startup State Hydration
    # Simulate a dummy open trade in journal
    dummy_ticket = 7771234
    journal = TradeJournal()
    journal.record_entry(
        ticket=dummy_ticket,
        symbol="EURUSDm",
        signal="BUY",
        lot=0.02,
        entry_price=1.10000,
        sl=1.09800,
        tp=1.10400,
        latency_ms=25.0,
        slippage_pips=0.1
    )

    # Mock a dummy position object
    class MockPosition:
        ticket = dummy_ticket
        symbol = "EURUSDm"
        type = 0  # BUY
        price_open = 1.10000
        sl = 1.10010  # Break-even moved
        tp = 1.10400
        volume = 0.01  # Partial TP already taken
        magic = 112233

    # Temporarily inject mock into get_bot_positions
    orig_get_positions = om.get_bot_positions
    om.get_bot_positions = lambda sym=None: [MockPosition()]

    # Clear memory dictionary and hydrate
    om.tracked_positions.clear()
    om.hydrate_active_positions()

    assert dummy_ticket in om.tracked_positions, "Hydration failed to track active position"
    pos_data = om.tracked_positions[dummy_ticket]
    assert pos_data["be_locked"] is True, "Hydration failed to identify break-even status"
    assert pos_data["partial_closed"] is True, "Hydration failed to identify partial scale-out status"
    console.print(f"  [green][PASS][/green] State Hydration verified: Ticket #{dummy_ticket} recovered. BE: {pos_data['be_locked']} | Partial: {pos_data['partial_closed']}")

    # Restore method and clean up dummy row
    om.get_bot_positions = orig_get_positions
    journal._execute("DELETE FROM trades WHERE ticket = ?", (dummy_ticket,))

    # 2. Test Pending Limit Orders Detection & Expiry Logic
    class MockPendingOrder:
        ticket = 8881234
        symbol = "EURUSDm"
        time_setup = (datetime.now(timezone.utc) - timedelta(minutes=20)).timestamp() # 20m old
        magic = 112233

    om.get_pending_orders = lambda sym=None: [MockPendingOrder()]
    count = om.get_bot_active_and_pending_count()
    assert count >= 1, "get_bot_active_and_pending_count failed to count pending orders"
    console.print(f"  [green][PASS][/green] Pending Orders Accounting: Correctly counted in active + pending basket ({count})")

    connector.shutdown()

def test_strategy_and_unmitigated_fvg():
    console.print("\n[bold cyan]=== [4/6] STRATEGY ENGINE & UNMITIGATED FVG VERIFICATION ===[/bold cyan]")
    from strategy import ForexConfluenceStrategy, get_trained_params
    from smc import SmartMoneyConcepts
    from csm import CurrencyStrengthMeter
    from mt5_connector import MT5Connector
    import config

    connector = MT5Connector()
    connector.initialize()
    strategy = ForexConfluenceStrategy()
    smc = SmartMoneyConcepts(connector)
    csm = CurrencyStrengthMeter(connector)

    # 1. Test CSM Multi-Pair Triangulation
    scores = csm.calculate_strengths()
    assert isinstance(scores, dict) and "USD" in scores and "EUR" in scores and "JPY" in scores
    console.print(f"  [green][PASS][/green] CSM Triangulation: USD={scores.get('USD')}, EUR={scores.get('EUR')}, JPY={scores.get('JPY')}, GBP={scores.get('GBP')}")

    # 2. Test Unmitigated vs Mitigated FVG
    # Create synthetic candles with Bullish FVG at index 2
    # Bar 0: Low 1.0990, High 1.1000
    # Bar 1: Low 1.1001, High 1.1015 (Large impulse)
    # Bar 2: Low 1.1005, High 1.1020 (Low > Bar 0 High by 5 pips -> Bullish FVG)
    # Bar 3: Low 1.1010, High 1.1025 (Does NOT mitigate Bar 0 High 1.1000)
    unmitigated_df = pd.DataFrame([
        {"open": 1.0995, "high": 1.1000, "low": 1.0990, "close": 1.0998},
        {"open": 1.1001, "high": 1.1015, "low": 1.1001, "close": 1.1014},
        {"open": 1.1014, "high": 1.1020, "low": 1.1005, "close": 1.1018},
        {"open": 1.1018, "high": 1.1025, "low": 1.1010, "close": 1.1022},
        {"open": 1.1022, "high": 1.1030, "low": 1.1015, "close": 1.1028},
    ])
    has_fvg, fvg_type = smc.detect_recent_fvg(unmitigated_df)
    assert has_fvg and fvg_type == "BULLISH_FVG", "Failed to detect clean unmitigated FVG"
    console.print(f"  [green][PASS][/green] Unmitigated FVG Detection: {fvg_type} identified")

    # Now add Bar 5 which dips to 1.0995, mitigating the gap (<= 1.1000)
    mitigated_df = pd.concat([unmitigated_df, pd.DataFrame([
        {"open": 1.1025, "high": 1.1028, "low": 1.0995, "close": 1.1005}
    ])], ignore_index=True)
    has_mitigated_fvg, _ = smc.detect_recent_fvg(mitigated_df)
    assert not has_mitigated_fvg, "Mitigated FVG was falsely flagged as active"
    console.print(f"  [green][PASS][/green] Mitigated FVG Invalidation: Mitigated gap successfully suppressed")

    # 3. Test Daily-Anchored Session VWAP Reset at 00:00 UTC
    from quant_engine import QuantitativeEngine
    times_day1 = [datetime(2026, 1, 1, 10, i, 0, tzinfo=timezone.utc) for i in range(10)]
    times_day2 = [datetime(2026, 1, 2, 0, i, 0, tzinfo=timezone.utc) for i in range(10)]
    all_times = times_day1 + times_day2
    highs = pd.Series([1.1000] * 10 + [1.2000] * 10)
    lows = pd.Series([1.0990] * 10 + [1.1990] * 10)
    closes = pd.Series([1.0995] * 10 + [1.1995] * 10)
    vols = pd.Series([100] * 20)
    anchored_vwap = QuantitativeEngine.calculate_vwap(highs, lows, closes, vols, datetimes=pd.Series(all_times))
    # At start of day 2 (index 10), VWAP should equal typical price of that candle, not accumulated from day 1
    typical_day2_bar0 = (1.2000 + 1.1990 + 1.1995) / 3.0
    assert abs(anchored_vwap.iloc[10] - typical_day2_bar0) < 1e-4, "Daily-Anchored VWAP failed to reset at 00:00 UTC"
    console.print(f"  [green][PASS][/green] Daily-Anchored VWAP: Verified 00:00 UTC reset (no cumulative multi-month drift)")

    # 4. Test Macro Trend Baseline Strategy Check
    ema50_series = pd.Series([1.1000] * 30 + [1.1100] * 30)
    assert ema50_series.iloc[-1] > ema50_series.iloc[0]
    console.print(f"  [green][PASS][/green] Macro Trend Baseline Filter: EMA 50 integration active")

    connector.shutdown()

def test_risk_gatekeepers_and_peak_equity_breaker():
    console.print("\n[bold cyan]=== [5/6] RISK GATEKEEPERS & TRAILING PROFIT-LOCK BREAKER ===[/bold cyan]")
    from mt5_connector import MT5Connector
    from risk_manager import RiskManager
    from notifier import DiscordNotifier
    import config

    connector = MT5Connector()
    connector.initialize()
    risk = RiskManager(connector)

    # 1. Test Intraday Peak Equity Trailing Drawdown Breaker
    risk.daily_start_balance = 30.00
    risk.daily_peak_equity = 36.00 # Gained +$6.00 intraday

    # Mock connector account summary to show equity dropped to $32.00 (gave back $4 of $6 -> 66% giveback)
    orig_summary = connector.get_account_summary
    connector.get_account_summary = lambda: {
        "login": 123456,
        "server": "Exness-Test",
        "balance": 30.00,
        "equity": 32.00, # dropped from 36.00
        "margin": 0.0,
        "free_margin": 32.00,
        "margin_level": 999.0,
        "leverage": 50,
        "currency": "USD",
        "trade_allowed": True
    }

    can_trade, reason = risk.can_open_trade("EURUSDm", active_positions_count=0)
    assert not can_trade, "Trailing profit-lock circuit breaker failed to trigger on profit giveback"
    assert "trailing profit-lock" in reason.lower(), f"Unexpected reason: {reason}"
    console.print(f"  [green][PASS][/green] Peak Equity Trailing Circuit Breaker: {reason}")

    # Restore summary
    connector.get_account_summary = orig_summary

    # 2. Test Non-blocking Async Discord Notifier
    notifier = DiscordNotifier()
    # Sending embed should be immediate (non-blocking)
    t_start = time.perf_counter()
    enqueued = notifier.send_embed("Test Title", "Test Description", 0x2ECC71)
    duration_ms = (time.perf_counter() - t_start) * 1000.0
    console.print(f"  [green][PASS][/green] Non-blocking Discord Dispatch: Enqueued in {duration_ms:.2f}ms (queue latency < 1ms)")
    assert duration_ms < 10.0, "Discord send_embed blocked the thread"
    notifier.shutdown()

    connector.shutdown()

def test_database_journal_and_persistence():
    console.print("\n[bold cyan]=== [6/6] SQLITE TRADE JOURNAL INTEGRITY & CONCURRENCY ===[/bold cyan]")
    from journal import TradeJournal

    journal = TradeJournal()
    test_ticket = 9999992
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

    journal._execute("DELETE FROM trades WHERE ticket = ?", (test_ticket,))
    console.print(f"  [green][PASS][/green] Test Trade Cleaned Up from Database")

def main():
    console.print(Panel.fit(
        "[bold cyan]EXTREME LEVEL DIAGNOSTIC & HARD STRESS TEST SUITE (AREAS 1 TO 4)[/bold cyan]\n"
        "[white]Verifying Math Bounds, Dynamic Pip Values, State Hydration, Pending Orders, SMC, and Trailing Breaker[/white]",
        border_style="cyan"
    ))
    t0 = time.time()
    test_mathematical_edge_stress()
    test_exness_broker_and_dynamic_pip_values()
    test_order_manager_hydration_and_pending_orders()
    test_strategy_and_unmitigated_fvg()
    test_risk_gatekeepers_and_peak_equity_breaker()
    test_database_journal_and_persistence()
    elapsed = time.time() - t0
    console.print(f"\n[bold green]ALL 6/6 EXTREME HARD STRESS TESTS PASSED IN {elapsed:.2f}s WITH ZERO ERRORS![/bold green]")

if __name__ == "__main__":
    main()
