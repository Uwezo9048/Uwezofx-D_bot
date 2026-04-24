# modules/trading/strategies.py
from typing import Tuple, Optional
from modules.trading.analyzer import MarketAnalyzer

class DigitStats:
    def __init__(self, digit: int):
        self.digit = digit
        self.count = 0
        self.percentage = 0.0
        self.color = "neutral"

class DigitAnalyzer:
    def __init__(self, window_size: int = 100, long_window: int = None, short_window: int = None):
        if long_window is None:
            self.long_window = window_size
        else:
            self.long_window = long_window
        if short_window is None:
            self.short_window = max(10, self.long_window // 5)
        else:
            self.short_window = short_window
        self.history: list = []
        self.digits = {d: DigitStats(d) for d in range(10)}
        self._update_stats()

    def add_tick(self, price: float):
        last_digit = int(str(price).split('.')[-1][-1])
        self.history.append(last_digit)
        if len(self.history) > self.long_window:
            self.history.pop(0)
        self._update_stats()
        self._update_colors()

    def _update_stats(self):
        total = len(self.history)
        if total == 0:
            return
        counts = {d: 0 for d in range(10)}
        for d in self.history:
            counts[d] += 1
        for d in range(10):
            self.digits[d].count = counts[d]
            self.digits[d].percentage = (counts[d] / total) * 100

    def _update_colors(self):
        if len(self.history) < self.short_window:
            return
        short_history = self.history[-self.short_window:]
        short_counts = {d: 0 for d in range(10)}
        for d in short_history:
            short_counts[d] += 1
        short_pct = {d: (short_counts[d] / self.short_window) * 100 for d in range(10)}
        long_pct = {d: self.digits[d].percentage for d in range(10)}
        for d in range(10):
            diff = short_pct[d] - long_pct[d]
            if diff >= 1.0:
                self.digits[d].color = "red"
            elif diff >= 0.5:
                self.digits[d].color = "yellow"
            elif diff <= -1.0:
                self.digits[d].color = "blue"
            elif diff <= -0.5:
                self.digits[d].color = "green"
            else:
                self.digits[d].color = "neutral"

    def get_last_digit(self) -> Optional[int]:
        return self.history[-1] if self.history else None


class StrategySignals:
    @staticmethod
    def over_under_signal(digit_analyzer: DigitAnalyzer) -> Tuple[str, Optional[int]]:
        stats = digit_analyzer.digits
        low_digits = [0, 1, 2, 3]
        high_digits = [4, 5, 6, 7, 8, 9]

        over_weak_ok = False
        for d in low_digits:
            if stats[d].percentage < 10.0 and stats[d].color in ['red', 'yellow']:
                over_weak_ok = True
                break

        high_count = 0
        for d in high_digits:
            if stats[d].percentage >= 11.0 and stats[d].color in ['blue', 'green']:
                high_count += 1
        over_strong_ok = high_count >= 2

        high_weak_ok = False
        for d in [6, 7, 8, 9]:
            if stats[d].percentage < 10.0 and stats[d].color in ['red', 'yellow']:
                high_weak_ok = True
                break

        low_count = 0
        for d in range(6):
            if stats[d].percentage >= 11.0 and stats[d].color in ['blue', 'green']:
                low_count += 1
        under_strong_ok = low_count >= 2

        if over_weak_ok and over_strong_ok:
            return "OVER", None
        elif high_weak_ok and under_strong_ok:
            return "UNDER", None
        return "NEUTRAL", None

    @staticmethod
    def even_odd_signal(digit_analyzer: DigitAnalyzer) -> Tuple[str, Optional[int]]:
        stats = digit_analyzer.digits
        even_digits = [0, 2, 4, 6, 8]
        odd_digits = [1, 3, 5, 7, 9]

        blue_on_even = any(stats[d].color == 'blue' and stats[d].percentage > 11.0 for d in even_digits)
        green_on_even = any(stats[d].color == 'green' and stats[d].percentage > 11.0 for d in even_digits)
        red_on_odd = any(stats[d].color == 'red' and stats[d].percentage <= 8.6 for d in odd_digits)
        yellow_on_odd = any(stats[d].color == 'yellow' and stats[d].percentage <= 9.5 for d in odd_digits)
        even_ok = blue_on_even and green_on_even and red_on_odd and yellow_on_odd

        blue_on_odd = any(stats[d].color == 'blue' and stats[d].percentage > 11.0 for d in odd_digits)
        green_on_odd = any(stats[d].color == 'green' and stats[d].percentage > 11.0 for d in odd_digits)
        red_on_even = any(stats[d].color == 'red' and stats[d].percentage <= 8.6 for d in even_digits)
        yellow_on_even = any(stats[d].color == 'yellow' and stats[d].percentage <= 9.5 for d in even_digits)
        odd_ok = blue_on_odd and green_on_odd and red_on_even and yellow_on_even

        if even_ok:
            return "EVEN", None
        elif odd_ok:
            return "ODD", None
        return "NEUTRAL", None

    @staticmethod
    def get_best_strategy(digit_analyzer: DigitAnalyzer) -> str:
        over_signal, _ = StrategySignals.over_under_signal(digit_analyzer)
        even_signal, _ = StrategySignals.even_odd_signal(digit_analyzer)
        if over_signal != "NEUTRAL" and even_signal != "NEUTRAL":
            return over_signal
        elif over_signal != "NEUTRAL":
            return over_signal
        elif even_signal != "NEUTRAL":
            return even_signal
        return "NEUTRAL"
