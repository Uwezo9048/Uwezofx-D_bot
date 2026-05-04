# tests/test_indicator.py
import unittest
from modules.trading.indicator import CombinedICTandSMSIndicator, TradeSignal

class TestCombinedICTandSMSIndicator(unittest.TestCase):
    def setUp(self):
        self.indicator = CombinedICTandSMSIndicator()

    def test_initial_signal_neutral(self):
        detail = self.indicator.get_signal_detail()
        self.assertEqual(detail.direction, TradeSignal.NEUTRAL)

    def test_update_adds_bars(self):
        self.indicator.update(1.1000, 1.1010, 1.0990, 1.1005, 1000)
        self.assertEqual(len(self.indicator.opens), 1)
        self.assertEqual(len(self.indicator.closes), 1)

    def test_signal_history_empty_initially(self):
        self.assertEqual(len(self.indicator.get_signal_history()), 0)

    def test_reset_signal(self):
        self.indicator._reset_signal(TradeSignal.BUY)
        self.assertEqual(self.indicator.signal_direction, TradeSignal.BUY)
        self.assertEqual(self.indicator.trades_taken_in_signal, 0)
        self.assertGreater(self.indicator.signal_start_bar, -1)

if __name__ == '__main__':
    unittest.main()