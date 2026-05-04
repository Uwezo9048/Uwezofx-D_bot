# tests/test_trailing.py
import unittest
from unittest.mock import Mock, patch
from modules.trading.trailing import TrailingStopLoss, TrailingConfig
from modules.trading.indicator import OrderType, Position, PositionStatus
from config import TradingConfig
import MetaTrader5 as mt5

class TestTrailingStopLoss(unittest.TestCase):
    def setUp(self):
        self.config = TradingConfig()
        self.config.enable_trailing_stop_loss = True
        self.config.lock_amount_dollars = 3.0
        self.config.step_amount_dollars = 4.0
        self.logger = Mock()
        self.callback_queue = Mock()
        self.trailing = TrailingStopLoss(self.config, self.logger, self.callback_queue)

    def test_initialization(self):
        self.assertEqual(self.trailing.trailing_config.enable_trailing_stop, True)
        self.assertEqual(self.trailing.trailing_config.lock_amount_dollars, 3.0)
        self.assertEqual(self.trailing.trailing_config.step_amount_dollars, 4.0)
        self.assertEqual(len(self.trailing.positions), 0)

    def test_add_position(self):
        with patch('MetaTrader5.symbol_info_tick') as mock_tick:
            mock_tick.return_value = type('obj', (object,), {'ask': 1.1000, 'bid': 1.0990})()
            result = self.trailing.add_position(
                ticket=12345,
                symbol='EURUSD',
                order_type=OrderType.LONG,
                volume=0.1,
                entry_price=1.1000,
                stop_loss=1.0950,
                take_profit=1.1100,
                comment='Test'
            )
            self.assertTrue(result)
            self.assertEqual(len(self.trailing.positions), 1)
            self.assertEqual(self.trailing.positions[12345].ticket, 12345)

    def test_close_position(self):
        # First add a position
        with patch('MetaTrader5.symbol_info_tick') as mock_tick:
            mock_tick.return_value = type('obj', (object,), {'ask': 1.1000, 'bid': 1.0990})()
            self.trailing.add_position(12345, 'EURUSD', OrderType.LONG, 0.1, 1.1000, 1.0950, 1.1100)
        # Then close it
        result = self.trailing.close_position(12345)
        self.assertTrue(result)
        self.assertEqual(len(self.trailing.positions), 0)
        self.assertEqual(self.trailing.performance_metrics['total_trades'], 1)

    def test_update_config(self):
        self.trailing.update_config(False, 5.0, 6.0)
        self.assertEqual(self.trailing.trailing_config.enable_trailing_stop, False)
        self.assertEqual(self.trailing.trailing_config.lock_amount_dollars, 5.0)
        self.assertEqual(self.trailing.trailing_config.step_amount_dollars, 6.0)

if __name__ == '__main__':
    unittest.main()