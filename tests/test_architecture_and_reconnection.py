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


class TestArchitectureAndReconnection(unittest.TestCase):
    """Test suite verifying unified BaseOrderManager, GoldOrderManager, and MT5 Reconnection."""

    def test_base_order_manager_shared_inheritance(self):
        """Verify that both OrderManager and GoldOrderManager inherit from BaseOrderManager."""
        from crypto_forex_bot.base_order_manager import BaseOrderManager
        from crypto_forex_bot.order_manager import OrderManager
        from gold_scalper.order_manager_gold import GoldOrderManager

        connector_mock = MagicMock()
        connector_mock.get_pip_size.return_value = 0.0001

        with patch("MetaTrader5.positions_get", return_value=[]):
            om_swing = OrderManager(connector_mock)
            om_gold = GoldOrderManager(connector_mock)

        self.assertIsInstance(om_swing, BaseOrderManager)
        self.assertIsInstance(om_gold, BaseOrderManager)
        self.assertEqual(om_swing.magic_number, 112233)
        self.assertEqual(om_gold.magic_number, 777001)
        print("  [PASS] Test 1: OrderManager and GoldOrderManager successfully inherit from BaseOrderManager")

    def test_shared_closed_deal_detection_and_journaling(self):
        """Verify that BaseOrderManager accurately audits deals, detects closed trades, and logs exits."""
        from crypto_forex_bot.base_order_manager import BaseOrderManager

        connector_mock = MagicMock()
        connector_mock.get_pip_size.return_value = 0.01  # Gold point
        connector_mock.get_account_summary.return_value = {"balance": 105.0}

        journal_mock = MagicMock()
        notifier_mock = MagicMock()
        risk_mock = MagicMock()

        bom = BaseOrderManager(
            connector=connector_mock,
            magic_number=777001,
            notifier=notifier_mock,
            journal=journal_mock,
            risk_manager=risk_mock,
        )

        # Populate a tracked position
        bom.tracked_positions[12345] = {
            "ticket": 12345,
            "symbol": "XAUUSDm",
            "signal": "BUY",
            "entry": 2000.0,
            "lot": 0.01,
            "sl": 1997.0,
            "tp": 2005.0,
        }

        # Mock deal history for closed ticket
        mock_deal = MagicMock()
        mock_deal.price = 2005.0
        mock_deal.profit = 5.00
        mock_deal.swap = 0.00
        mock_deal.commission = -0.10
        mock_deal.comment = "[tp 2005.0]"

        with patch("MetaTrader5.history_deals_get", return_value=[mock_deal]), \
             patch("MetaTrader5.positions_get", return_value=[]):
            # Position has disappeared from active positions
            closed_summaries = bom.detect_and_handle_closed_positions(current_positions=[])

        self.assertEqual(len(closed_summaries), 1)
        summary = closed_summaries[0]
        self.assertEqual(summary["ticket"], 12345)
        self.assertAlmostEqual(summary["pnl"], 4.90)
        self.assertEqual(summary["reason"], "Take Profit Hit")

        # Verify journal record_exit was called with correct net PnL and exit price
        journal_mock.record_exit.assert_called_once()
        args = journal_mock.record_exit.call_args[1]
        self.assertEqual(args["ticket"], 12345)
        self.assertEqual(args["exit_price"], 2005.0)
        self.assertAlmostEqual(args["pnl_usd"], 4.90)

        # Verify risk manager and notifier were updated
        risk_mock.register_trade_outcome.assert_called_once_with(True)
        notifier_mock.notify_trade_closed.assert_called_once()
        print("  [PASS] Test 2: Shared deal auditing, net PnL, journal exit, and notifier verified")

    def test_gold_scalper_spread_guard_protection(self):
        """Verify that GoldOrderManager rejects scalps when spread exceeds MAX_SPREAD_POINTS."""
        from gold_scalper.order_manager_gold import GoldOrderManager
        import gold_scalper.config_gold as config_gold

        connector_mock = MagicMock()
        connector_mock.get_pip_size.return_value = 0.01

        with patch("MetaTrader5.positions_get", return_value=[]):
            om_gold = GoldOrderManager(connector_mock)

        # Mock tick with wide spread: Ask 2001.00, Bid 2000.50 -> 500 points ($0.50 > $0.20 allowed)
        wide_tick = MagicMock()
        wide_tick.ask = 2001.00
        wide_tick.bid = 2000.50

        mock_info = MagicMock()
        mock_info.digits = 3
        mock_info.volume_min = 0.01
        mock_info.volume_max = 10.0

        with patch("MetaTrader5.symbol_info_tick", return_value=wide_tick), \
             patch("MetaTrader5.symbol_info", return_value=mock_info), \
             patch("MetaTrader5.order_send") as mock_send:
            ticket = om_gold.execute_scalp("BUY", atr_val=2.50)

        self.assertIsNone(ticket)
        mock_send.assert_not_called()
        print("  [PASS] Test 3: GoldOrderManager spread anomaly shield successfully blocked wide spread scalp")

    def test_mt5_connector_auto_recovery_on_rate_fetch(self):
        """Verify that MT5Connector triggers ensure_connection if rates fetch drops."""
        from crypto_forex_bot.mt5_connector import MT5Connector

        connector = MT5Connector()

        # Mock terminal disconnected then restored
        mock_term_down = MagicMock()
        mock_term_down.connected = False

        mock_rates = [{"time": 1700000000, "close": 2000.0}]

        with patch("MetaTrader5.copy_rates_from_pos", side_effect=[None, mock_rates]), \
             patch("MetaTrader5.terminal_info", return_value=mock_term_down), \
             patch.object(connector, "ensure_connection", return_value=True) as mock_ensure:
            rates = connector.get_rates("XAUUSDm", "M5", count=10)

        self.assertEqual(rates, mock_rates)
        mock_ensure.assert_called_once()
        print("  [PASS] Test 4: MT5Connector auto-recovery triggered during rate fetch drop")


if __name__ == "__main__":
    unittest.main()
