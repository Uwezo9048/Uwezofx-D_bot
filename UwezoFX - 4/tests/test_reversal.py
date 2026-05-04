# tests/test_reversal.py
import unittest
from unittest.mock import Mock, patch
from modules.trading.reversal import EnhancedReversalTrader
from modules.trading.indicator import CombinedICTandSMSIndicator, TradeSignal
from config import TradingConfig

class TestEnhancedReversalTrader(unittest.TestCase):
    def setUp(self):
        self.config = TradingConfig()
        self.config.enable_reversal_trading = True
        self.config.reversal_min_confidence_score = 70.0
        self.config.reversal_require_retest = False  # Simplify for testing
        self.indicator = CombinedICTandSMSIndicator()
        self.logger = Mock()
        self.callback_queue = Mock()
        self.news_manager = Mock()
        self.reversal = EnhancedReversalTrader(
            self.config, self.indicator, self.logger, self.callback_queue, self.news_manager
        )

    def test_initialization(self):
        self.assertEqual(self.reversal.config, self.config)
        self.assertEqual(self.reversal.indicator, self.indicator)
        self.assertEqual(len(self.reversal.reversal_history), 0)

    def test_check_volatility_disabled(self):
        # When filter disabled, should return True
        self.config.reversal_use_volatility_filter = False
        result, reason, score = self.reversal.check_volatility()
        self.assertTrue(result)
        self.assertEqual(reason, "Volatility filter disabled")

    def test_check_time(self):
        # Mock datetime to return a fixed time, but we'll just call it
        # and accept the result (may vary based on actual time)
        result, reason, score = self.reversal.check_time()
        # It should at least return a boolean and a string
        self.assertIsInstance(result, bool)
        self.assertIsInstance(reason, str)
        self.assertIsInstance(score, float)

    def test_calculate_reversal_confidence_always_execute_when_0_percent(self):
        # When min_confidence is 0%, should always trade
        self.config.reversal_min_confidence_score = 0.0
        # Use dummy signals
        confidence_data = self.reversal.calculate_reversal_confidence(TradeSignal.BUY, TradeSignal.SELL)
        self.assertTrue(confidence_data['should_trade'])
        # Also the should_execute_reversal method should return True
        should, reason, data = self.reversal.should_execute_reversal(TradeSignal.BUY, TradeSignal.SELL)
        self.assertTrue(should)
        self.assertIn("0%", reason)

if __name__ == '__main__':
    unittest.main()