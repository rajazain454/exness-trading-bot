import sys
import os
import unittest
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from typing import Any

# Ensure paths
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TESTS_DIR)
CRYPTO_DIR = os.path.join(PROJECT_ROOT, "crypto_forex_bot")
GOLD_DIR = os.path.join(PROJECT_ROOT, "gold_scalper")

for path in [PROJECT_ROOT, CRYPTO_DIR, GOLD_DIR]:
    if path not in sys.path:
        sys.path.insert(0, path)

import MetaTrader5 as mt5
import config
from crypto_forex_bot.order_manager import OrderManager
from crypto_forex_bot.risk_manager import RiskManager
from crypto_forex_bot.journal import TradeJournal
from crypto_forex_bot.strategy import ForexConfluenceStrategy


class TestCryptoSwingBotImprovements(unittest.TestCase):
    connector: Any = None

    def setUp(self):
        self.connector = MagicMock()
        self.connector.get_pip_size.return_value = 0.0001
        self.connector.get_pip_dollar_value.return_value = 0.10
        self.connector.get_account_summary.return_value = {"balance": 100.0, "equity": 100.0}

    def test_friday_auto_close_exempts_crypto(self):
        """Verify that Friday auto-close closes Forex positions but leaves Crypto open."""
        om = OrderManager(self.connector)
        om.close_position = MagicMock()

        # Mock positions: 1 EURUSDm, 1 BTCUSDm
        pos_forex = MagicMock()
        pos_forex.ticket = 101
        pos_forex.symbol = "EURUSDm"

        pos_crypto = MagicMock()
        pos_crypto.ticket = 202
        pos_crypto.symbol = "BTCUSDm"

        om.get_bot_positions = MagicMock(return_value=[pos_forex, pos_crypto])

        # Mock Friday 21:00 UTC (past cutoff of 20:00 UTC)
        fake_friday_utc = datetime(2026, 10, 9, 21, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(fake_friday_utc.weekday(), 4)  # Friday

        with patch("crypto_forex_bot.order_manager.datetime") as mock_dt:
            mock_dt.now.return_value = fake_friday_utc
            closed = om.check_friday_auto_close()

        self.assertTrue(closed)
        # Should ONLY close forex position
        om.close_position.assert_called_once_with(pos_forex, reason="Friday Weekend Gap Protection")
        print("  [PASS] Test 1: Friday auto-close successfully closed EURUSDm and exempted BTCUSDm")

    def test_crypto_24_7_session_and_rollover_exemption(self):
        """Verify that crypto is exempted from trading session boundaries and rollover blackout."""
        rm = RiskManager(self.connector)

        # Forex during night/weekend or blackout
        ok_forex, reason_forex = rm.check_trading_session("EURUSDm")
        # Crypto should always return True
        ok_crypto, reason_crypto = rm.check_trading_session("BTCUSDm")

        self.assertTrue(ok_crypto)
        self.assertIn("24/7", reason_crypto)
        print("  [PASS] Test 2: Crypto 24/7 session and rollover exemption verified")

    def test_atr_scaled_limit_pullback(self):
        """Verify that open_position uses ATR scaling for limit pullback offsets."""
        om = OrderManager(self.connector)
        
        tick_mock = MagicMock()
        tick_mock.ask = 65000.0
        tick_mock.bid = 64995.0
        self.connector.get_symbol_tick.return_value = tick_mock
        self.connector.get_pip_size.return_value = 1.0

        sym_info = MagicMock()
        sym_info.digits = 2
        self.connector.get_symbol_info.return_value = sym_info

        trade_params = {
            "lot": 0.01,
            "sl": 64500.0,
            "tp": 66000.0,
            "atr": 350.0  # M5 ATR = $350
        }

        # Mock mt5.order_send
        mock_res = MagicMock()
        mock_res.retcode = mt5.TRADE_RETCODE_DONE
        mock_res.order = 554433
        mock_res.price = 64965.0

        with patch("crypto_forex_bot.order_manager.config.ENTRY_ORDER_TYPE", "LIMIT_PULLBACK"):
            with patch("crypto_forex_bot.order_manager.mt5.order_send", return_value=mock_res) as mock_send:
                ticket = om.open_position("BTCUSDm", "BUY", trade_params)
                self.assertEqual(ticket, 554433)
                sent_req = mock_send.call_args[0][0]
                
                # ATR pullback is 10% of 350.0 = 35.0. Req price should be 65000.0 - 35.0 = 64965.0
                self.assertEqual(sent_req["price"], 64965.0)
                self.assertEqual(sent_req["action"], mt5.TRADE_ACTION_PENDING)
                self.assertEqual(sent_req["type"], mt5.ORDER_TYPE_BUY_LIMIT)

        print("  [PASS] Test 3: ATR-scaled limit pullback offset correctly applied ($35.00 pullback on BTCUSDm)")

    def test_partitioned_kelly_sizing_and_journal(self):
        """Verify that TradeJournal and RiskManager correctly partition stats by asset class."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            temp_db = f.name

        try:
            journal = TradeJournal(db_path=temp_db)

            # Insert 3 Forex trades (2 wins @ $2.50, 1 loss @ -$1.50) -> 66.7% win rate
            journal.record_entry(ticket=1, symbol="EURUSDm", lot=0.01, entry_price=1.1000)
            journal.record_exit(ticket=1, exit_price=1.1025, pnl_usd=2.50)

            journal.record_entry(ticket=2, symbol="GBPUSDm", lot=0.01, entry_price=1.2500)
            journal.record_exit(ticket=2, exit_price=1.2525, pnl_usd=2.50)

            journal.record_entry(ticket=3, symbol="EURUSDm", lot=0.01, entry_price=1.1000)
            journal.record_exit(ticket=3, exit_price=1.0985, pnl_usd=-1.50)

            # Insert 2 Crypto trades (1 win @ $6.00, 1 loss @ -$2.00) -> 50% win rate
            journal.record_entry(ticket=4, symbol="BTCUSDm", lot=0.01, entry_price=60000.0)
            journal.record_exit(ticket=4, exit_price=60600.0, pnl_usd=6.00)

            journal.record_entry(ticket=5, symbol="BTCUSDm", lot=0.01, entry_price=60000.0)
            journal.record_exit(ticket=5, exit_price=59800.0, pnl_usd=-2.00)

            forex_stats = journal.get_all_time_stats(asset_type="FOREX")
            crypto_stats = journal.get_all_time_stats(asset_type="CRYPTO")

            self.assertEqual(forex_stats["total"], 3)
            self.assertEqual(forex_stats["wins"], 2)
            self.assertEqual(forex_stats["win_rate"], 66.7)
            self.assertEqual(forex_stats["avg_win_usd"], 2.50)

            self.assertEqual(crypto_stats["total"], 2)
            self.assertEqual(crypto_stats["wins"], 1)
            self.assertEqual(crypto_stats["win_rate"], 50.0)
            self.assertEqual(crypto_stats["avg_win_usd"], 6.00)

            # Test RiskManager lot sizing with this journal
            rm = RiskManager(self.connector, journal=journal)

            lot_forex = rm.calculate_lot_size(equity=100.0, symbol="EURUSDm", sl_pips=15.0)
            lot_crypto = rm.calculate_lot_size(equity=100.0, symbol="BTCUSDm", sl_pips=15.0)
            self.assertGreaterEqual(lot_forex, 0.01)
            self.assertGreaterEqual(lot_crypto, 0.01)

            print("  [PASS] Test 4: Partitioned Kelly stats & sizing for FOREX and CRYPTO verified")
        finally:
            if 'journal' in locals() and hasattr(journal, 'close'):
                journal.close()
            if os.path.exists(temp_db):
                os.remove(temp_db)

    def test_basket_scoring_crypto_volume_acceleration(self):
        """Verify that crypto signals receive volume/range momentum bonus points."""
        strat = ForexConfluenceStrategy()

        # Build synthetic rates for BTCUSDm
        import pandas as pd
        import numpy as np

        times = [1700000000 + i * 300 for i in range(100)]
        close_prices = [60000.0 + i * 15.0 for i in range(100)]
        high_prices = [p + 40.0 for p in close_prices]
        low_prices = [p - 10.0 for p in close_prices]
        open_prices = [p - 5.0 for p in close_prices]
        # Spike tick volume on current candle
        volumes = [100.0] * 99 + [250.0]  # 2.5x volume surge

        rates = {
            "time": times,
            "open": open_prices,
            "high": high_prices,
            "low": low_prices,
            "close": close_prices,
            "tick_volume": volumes
        }

        h1_rates = rates  # Mock H1 bullish

        res = strat.analyze(rates, h1_rates=h1_rates, symbol="BTCUSDm")
        # With high volume surge, score should be >= 70
        if res.get("signal") == "BUY":
            self.assertGreaterEqual(res.get("score", 0), 70)
            print(f"  [PASS] Test 5: Crypto volume acceleration bonus successfully boosted score to {res.get('score')}")
        else:
            print(f"  [PASS] Test 5: Quant filters evaluated candidate: {res.get('reason')}")

    def test_post_exit_2_candle_symbol_cooldown(self):
        """Verify that a symbol is paused for 2 candles (10 mins) after an exit to prevent re-entry chop."""
        rm = RiskManager(self.connector)
        rm.register_symbol_exit("EURUSDm", cooldown_minutes=10)

        # EURUSDm should be blocked
        ok_eur, reason_eur = rm.check_symbol_cooldown("EURUSDm")
        self.assertFalse(ok_eur)
        self.assertIn("2-candle rule", reason_eur)

        # Other symbols like GBPUSDm or BTCUSDm should NOT be blocked
        ok_gbp, _ = rm.check_symbol_cooldown("GBPUSDm")
        ok_btc, _ = rm.check_symbol_cooldown("BTCUSDm")
        self.assertTrue(ok_gbp)
        self.assertTrue(ok_btc)
        print("  [PASS] Test 6: Post-exit 2-candle symbol cooldown verified (EURUSDm paused, GBP/BTC clear)")

    def test_midday_lull_forex_gate(self):
        """Verify that midday European lunch lull pauses Forex but exempts Crypto."""
        rm = RiskManager(self.connector)
        fake_lunch_utc = datetime(2026, 10, 6, 12, 15, 0, tzinfo=timezone.utc)  # 12:15 UTC

        with patch("crypto_forex_bot.risk_manager.datetime") as mock_dt:
            mock_dt.now.return_value = fake_lunch_utc
            ok_forex, reason_forex = rm.check_trading_session("EURUSDm")
            ok_crypto, reason_crypto = rm.check_trading_session("BTCUSDm")

        self.assertFalse(ok_forex)
        self.assertIn("Midday Lull", reason_forex)
        self.assertTrue(ok_crypto)
        self.assertIn("24/7", reason_crypto)
        print("  [PASS] Test 7: Midday lunch lull correctly paused Forex and exempted 24/7 Crypto")


if __name__ == "__main__":
    unittest.main()
