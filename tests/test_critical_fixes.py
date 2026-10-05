import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Ensure paths
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(TESTS_DIR)
CRYPTO_DIR = os.path.join(PROJECT_ROOT, "crypto_forex_bot")
GOLD_DIR = os.path.join(PROJECT_ROOT, "gold_scalper")

for path in [PROJECT_ROOT, CRYPTO_DIR, GOLD_DIR]:
    if path not in sys.path:
        sys.path.insert(0, path)

import MetaTrader5 as mt5

class TestCriticalRuntimeFixes(unittest.TestCase):

    def test_buy_partial_take_profit_remaining_vol(self):
        """Verify that BUY partial take profit computes remaining_vol without NameError."""
        from order_manager import OrderManager

        connector_mock = MagicMock()
        connector_mock.get_pip_dollar_value.return_value = 0.10
        connector_mock.get_pip_size.return_value = 0.0001
        
        tick_mock = MagicMock()
        tick_mock.bid = 1.1030
        tick_mock.ask = 1.1032
        connector_mock.get_symbol_tick.return_value = tick_mock
        connector_mock.get_account_summary.return_value = {"balance": 100.0}

        om = OrderManager(connector_mock)
        om.notifier = MagicMock()
        om.journal = MagicMock()

        # Mock an active BUY position (0.04 lots)
        mock_pos = MagicMock()
        mock_pos.ticket = 991122
        mock_pos.symbol = "EURUSDm"
        mock_pos.type = mt5.ORDER_TYPE_BUY
        mock_pos.price_open = 1.1000
        mock_pos.sl = 1.0980
        mock_pos.tp = 1.1050
        mock_pos.volume = 0.04

        om.get_bot_positions = MagicMock(return_value=[mock_pos])
        om.close_partial_position = MagicMock(return_value=True)
        om.update_sl = MagicMock(return_value=True)
        om.tracked_positions[991122] = {"partial_closed": False, "be_locked": False}

        # Execute position management
        om.manage_trailing_and_breakeven("EURUSDm")

        # Verify close_partial_position was called for 50% = 0.02 lots
        om.close_partial_position.assert_called_once_with(mock_pos, 0.02)
        # Verify notifier was called with correct remaining_vol (0.02)
        om.notifier.notify_partial_tp_locked.assert_called_once()
        call_args = om.notifier.notify_partial_tp_locked.call_args[0]
        # args: (symbol, ticket, close_vol, remaining_vol, pnl_banked, be_price)
        self.assertEqual(call_args[0], "EURUSDm")
        self.assertEqual(call_args[1], 991122)
        self.assertEqual(call_args[2], 0.02) # close_vol
        self.assertEqual(call_args[3], 0.02) # remaining_vol
        self.assertTrue(om.tracked_positions[991122]["partial_closed"])
        print("  [PASS] Test 1: BUY partial take-profit correctly calculated remaining_vol (0.02 lot) without NameError")

    def test_gold_scalper_dynamic_filling_mode(self):
        """Verify that GoldScalperBot resolves broker filling mode dynamically."""
        from bot_gold import GoldScalperBot

        bot = GoldScalperBot()
        
        # Scenario A: Broker supports IOC (filling_mode = 2)
        mock_sym_ioc = MagicMock()
        mock_sym_ioc.filling_mode = 2 # SYMBOL_FILLING_IOC
        with patch("MetaTrader5.symbol_info", return_value=mock_sym_ioc):
            mode = bot.get_filling_mode("XAUUSDm")
            self.assertEqual(mode, mt5.ORDER_FILLING_IOC)

        # Scenario B: Broker supports FOK only (filling_mode = 1)
        mock_sym_fok = MagicMock()
        mock_sym_fok.filling_mode = 1 # SYMBOL_FILLING_FOK
        mock_sym_fok.volume_min = 0.01
        mock_sym_fok.digits = 3
        with patch("MetaTrader5.symbol_info", return_value=mock_sym_fok):
            mode = bot.get_filling_mode("XAUUSDm")
            self.assertEqual(mode, mt5.ORDER_FILLING_FOK)

        # Verify manage_gold_positions sends request with dynamic filling mode
        mock_pos = MagicMock()
        mock_pos.ticket = 778899
        mock_pos.symbol = "XAUUSDm"
        mock_pos.type = mt5.ORDER_TYPE_BUY
        mock_pos.price_open = 2000.00
        mock_pos.sl = 1995.00
        mock_pos.tp = 2010.00
        mock_pos.volume = 0.02

        bot.get_gold_positions = MagicMock(return_value=[mock_pos])
        mock_tick = MagicMock()
        mock_tick.bid = 2005.00
        mock_tick.ask = 2005.20
        
        sent_requests = []
        def capture_order_send(req):
            sent_requests.append(req)
            res = MagicMock()
            res.retcode = mt5.TRADE_RETCODE_DONE
            return res

        with patch("MetaTrader5.symbol_info_tick", return_value=mock_tick), \
             patch("MetaTrader5.symbol_info", return_value=mock_sym_fok), \
             patch("MetaTrader5.order_send", side_effect=capture_order_send):
            bot.manage_gold_positions(atr_val=2.50)

        # First request is the partial close DEAL
        self.assertGreaterEqual(len(sent_requests), 1)
        self.assertEqual(sent_requests[0]["action"], mt5.TRADE_ACTION_DEAL)
        self.assertEqual(sent_requests[0]["type_filling"], mt5.ORDER_FILLING_FOK)
        print("  [PASS] Test 2: Gold Scalper successfully used broker-supported ORDER_FILLING_FOK dynamically")

    def test_dynamic_margin_fallback_calculation(self):
        """Verify that RiskManager uses accurate symbol contract size on margin calculation fallback."""
        from risk_manager import RiskManager

        connector_mock = MagicMock()
        connector_mock.get_account_summary.return_value = {
            "balance": 100.0,
            "equity": 100.0,
            "free_margin": 50.0,
            "leverage": 200,
            "trade_allowed": True
        }
        tick_mock = MagicMock()
        tick_mock.ask = 65000.0  # BTC price
        connector_mock.get_symbol_tick.return_value = tick_mock
        connector_mock.get_current_spread_pips.return_value = 10.0

        risk = RiskManager(connector_mock)
        # Disable filters not under test
        risk.check_trading_session = MagicMock(return_value=(True, "OK"))
        risk.check_spread_anomaly = MagicMock(return_value=(True, "OK"))
        risk.check_cooldown = MagicMock(return_value=(True, "OK"))
        risk.check_friday_cutoff = MagicMock(return_value=(True, "OK"))
        risk.news_filter.is_news_blackout = MagicMock(return_value=(False, "OK", None))

        # Test BTCUSDm (contract_size = 1.0)
        btc_info = MagicMock()
        btc_info.trade_contract_size = 1.0
        btc_info.volume_min = 0.01
        btc_info.volume_max = 10.0
        btc_info.volume_step = 0.01

        # When order_calc_margin returns None (fallback triggered)
        with patch("MetaTrader5.order_calc_margin", return_value=None), \
             patch("MetaTrader5.symbol_info", return_value=btc_info):
            
            # calculate required margin with 0.01 lot BTC at $65,000, leverage 1:200
            # expected = (1.0 * 0.01 * 65000.0) / 200 = $3.25
            lot = 0.01
            contract_sz = btc_info.trade_contract_size
            expected_fallback = (contract_sz * lot * tick_mock.ask) / 200.0
            self.assertAlmostEqual(expected_fallback, 3.25, places=2)

            can_trade, reason = risk.can_open_trade("BTCUSDm", active_positions_count=0)
            self.assertTrue(can_trade, f"Trade should have passed with margin ~$3.25, but failed: {reason}")

        # If it had used old hardcoded 100,000.0:
        old_flawed_margin = (100000.0 * 0.01 * 65000.0) / 200.0
        self.assertEqual(old_flawed_margin, 325000.0) # $325,000!

        print("  [PASS] Test 3: Margin fallback correctly used BTC contract size (1.0 -> $3.25 margin) instead of $325,000.00")

if __name__ == "__main__":
    unittest.main()
