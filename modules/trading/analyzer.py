# modules/trading/analyzer.py
import numpy as np
from scipy.signal import argrelextrema
from sklearn.linear_model import LinearRegression
from typing import List, Tuple, Optional
from dataclasses import dataclass

@dataclass
class SRLevel:
    price: float
    type: str
    strength: int

class MarketAnalyzer:
    def __init__(self, closes, highs, lows, lookback=100):
        self.closes = closes[-lookback:]
        self.highs = highs[-lookback:]
        self.lows = lows[-lookback:]

    def find_support_resistance(self, order=5, tolerance=0.002) -> List[SRLevel]:
        highs = np.array(self.highs)
        lows = np.array(self.lows)
        maxima = argrelextrema(highs, np.greater, order=order)[0]
        minima = argrelextrema(lows, np.less, order=order)[0]
        levels = []
        for idx in maxima:
            levels.append(SRLevel(highs[idx], 'resistance', 1))
        for idx in minima:
            levels.append(SRLevel(lows[idx], 'support', 1))
        merged = []
        for l in levels:
            found = False
            for m in merged:
                if abs(l.price - m.price) / m.price < tolerance:
                    m.strength += 1
                    found = True
                    break
            if not found:
                merged.append(l)
        return merged

    def find_trendline(self) -> Tuple[Optional[float], Optional[float]]:
        if len(self.closes) < 20:
            return None, None
        x = np.arange(len(self.closes))
        model = LinearRegression()
        model.fit(x.reshape(-1,1), self.closes)
        return model.coef_[0], model.intercept_

    @staticmethod
    def calculate_rsi(closes, period=14) -> float:
        if len(closes) < period+1:
            return 50.0
        deltas = np.diff(closes[-period-1:])
        gains = deltas[deltas > 0].sum() / period
        losses = -deltas[deltas < 0].sum() / period
        if losses == 0:
            return 100.0
        rs = gains / losses
        return 100 - (100 / (1 + rs))

    @staticmethod
    def moving_average_cross(closes, fast=5, slow=10) -> int:
        if len(closes) < slow+1:
            return 0
        fast_ma = np.mean(closes[-fast-1:-1])
        slow_ma = np.mean(closes[-slow-1:-1])
        fast_ma_now = np.mean(closes[-fast:])
        slow_ma_now = np.mean(closes[-slow:])
        if fast_ma <= slow_ma and fast_ma_now > slow_ma_now:
            return 1
        elif fast_ma >= slow_ma and fast_ma_now < slow_ma_now:
            return -1
        return 0