# modules/trading/indicator.py
import numpy as np
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

class TradeSignal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"

@dataclass
class SignalDetail:
    direction: TradeSignal
    entry_price: Optional[float]
    trade_count: int
    aggressive: bool
    signal_start_bar: int
    trades_taken: int
    entry_type: str
    limit_price: Optional[float] = None
    comment: str = ""

@dataclass
class SwingPoint:
    x: int
    y: float
    direction: int

@dataclass
class OrderBlock:
    top: float
    bottom: float
    loc: int
    breaker: bool = False
    break_loc: Optional[int] = None

@dataclass
class FVG:
    left: int
    top: float
    right: int
    bottom: float
    active: bool = True
    direction: str = "bull"

@dataclass
class Displacement:
    bar: int
    direction: str

@dataclass
class VolumeImbalance:
    bar: int
    direction: str
    lines: Tuple

@dataclass
class Trade:
    ticket: int
    symbol: str
    type: str
    volume: float
    entry_price: float
    sl: float
    tp: float
    entry_time: datetime
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    profit: float = 0.0
    comment: str = ""

    def to_dict(self):
        return {
            'ticket': self.ticket,
            'symbol': self.symbol,
            'type': self.type,
            'volume': self.volume,
            'entry_price': self.entry_price,
            'sl': self.sl,
            'tp': self.tp,
            'entry_time': self.entry_time.isoformat() if self.entry_time else None,
            'exit_price': self.exit_price,
            'exit_time': self.exit_time.isoformat() if self.exit_time else None,
            'profit': self.profit,
            'comment': self.comment
        }

class OrderType(Enum):
    LONG = "LONG"
    SHORT = "SHORT"

class PositionStatus(Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    STOPPED = "STOPPED"
    TAKEN_PROFIT = "TAKEN_PROFIT"

@dataclass
class Position:
    ticket: int
    symbol: str
    order_type: OrderType
    volume: float
    entry_price: float
    current_price: float
    stop_loss: float
    take_profit: float
    trailing_stop: Optional[float] = None
    trailing_take_profit: Optional[float] = None
    highest_price: Optional[float] = None
    lowest_price: Optional[float] = None
    breakeven_reached: bool = False
    status: PositionStatus = PositionStatus.OPEN
    entry_time: datetime = field(default_factory=datetime.now)
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    profit: float = 0.0
    comment: str = ""
    last_locked_profit: float = 0.0
    total_locked_profit: float = 0.0
    lock_levels: List[float] = field(default_factory=list)
    mt5_profit: float = 0.0

    def update_current_price(self, price: float):
        self.current_price = price
        if self.order_type == OrderType.LONG:
            if self.highest_price is None or price > self.highest_price:
                self.highest_price = price
        else:
            if self.lowest_price is None or price < self.lowest_price:
                self.lowest_price = price

    def calculate_pnl(self) -> float:
        if self.order_type == OrderType.LONG:
            return (self.current_price - self.entry_price) * self.volume * 100000
        else:
            return (self.entry_price - self.current_price) * self.volume * 100000

# ========== Combined ICT and SMS Indicator ==========

class CombinedICTandSMSIndicator:
    """
    Combines ICT Concepts and Smart Money Structure
    to generate exact entry levels and track trade counts.
    """

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self._set_defaults()

        self.bar_index = -1
        self.last_price = None
        self.atr = None
        self.volatility_factor = None
        self.momentum_threshold = None
        self.pre_momentum_threshold = None

        self.opens = []
        self.highs = []
        self.lows = []
        self.closes = []
        self.volumes = []

        self.swing_points: List[SwingPoint] = []
        self.last_high = None
        self.last_low = None
        self.last_high_idx = None
        self.last_low_idx = None

        self.bull_obs: List[OrderBlock] = []
        self.bear_obs: List[OrderBlock] = []
        self.fvg_bull: List[FVG] = []
        self.fvg_bear: List[FVG] = []
        self.displacements: List[Displacement] = []
        self.vi_items: List[VolumeImbalance] = []

        self.ms_dir = 0
        self.last_signal_bar = -self.config['min_signal_distance'] - 1
        self.last_signal = TradeSignal.NEUTRAL
        self.last_trend = 0

        self.signal_start_bar = -1
        self.signal_direction = TradeSignal.NEUTRAL
        self.trades_taken_in_signal = 0
        self.session_trades = 0
        self.last_trade_bar = -1
        self.last_trade_minute = None

        self.signal_history = []

    def _set_defaults(self):
        defaults = {
            'use_ict_mss': True,
            'use_ict_bos': True,
            'use_ict_fvg': True,
            'use_ict_ob': True,
            'use_ict_vi': True,
            'use_ict_displacement': False,
            'use_sms_momentum_filter': True,
            'use_sms_trend_filter': True,
            'use_sms_volume_filter': True,
            'use_sms_breakout_filter': True,
            'use_sms_divergence': True,
            'use_sts': False,
            'require_fvg_confirmation': False,
            'require_ob_confirmation': False,
            'momentum_threshold_base': 0.01,
            'sms_pre_momentum_factor': 0.5,
            'length': 5,
            'atr_period': 14,
            'rsi_period': 14,
            'cci_period': 20,
            'williams_period': 14,
            'rsi_overbought': 70.0,
            'rsi_oversold': 30.0,
            'cci_overbought': 100.0,
            'cci_oversold': -100.0,
            'williams_overbought': -20.0,
            'williams_oversold': -80.0,
            'min_trades_per_signal': 5,
            'max_trades_per_session': 5,
            'aggressive_trades_per_minute': 2,
            'min_signal_distance': 5,
            'sms_volume_long_period': 50,
            'sms_volume_short_period': 5,
            'sms_breakout_period': 5,
            'max_vi': 2,
            'max_fvg': 5,
            'max_obs': 10,
            'max_swing_points': 50,
            'fvg_type': 'FVG',
            'use_body_for_ob': True,
        }
        for k, v in defaults.items():
            if k not in self.config:
                self.config[k] = v

    def update(self, open: float, high: float, low: float, close: float, volume: float = 0):
        self.bar_index += 1
        self.opens.append(open)
        self.highs.append(high)
        self.lows.append(low)
        self.closes.append(close)
        self.volumes.append(volume)

        self._update_atr()
        self._update_volatility_and_thresholds(close)
        self._detect_swings()
        self._detect_mss_bos()
        if self.config['use_ict_displacement']:
            self._detect_displacement(open, high, low, close)
        if self.config['use_ict_vi']:
            self._detect_volume_imbalance(open, high, low, close, volume)
        if self.config['use_ict_fvg']:
            self._detect_fvg()
        if self.config['use_ict_ob']:
            self._detect_order_blocks()

        self._update_fvgs()
        self._update_obs()

    def _update_atr(self):
        if len(self.closes) < self.config['atr_period']:
            self.atr = None
            return
        if self.bar_index == 0:
            tr = self.highs[0] - self.lows[0]
        else:
            tr = max(
                self.highs[-1] - self.lows[-1],
                abs(self.highs[-1] - self.closes[-2]),
                abs(self.lows[-1] - self.closes[-2])
            )
        if self.bar_index >= self.config['atr_period']:
            trs = []
            for i in range(self.bar_index - self.config['atr_period'] + 1, self.bar_index + 1):
                if i == 0:
                    trs.append(self.highs[0] - self.lows[0])
                else:
                    trs.append(max(
                        self.highs[i] - self.lows[i],
                        abs(self.highs[i] - self.closes[i-1]),
                        abs(self.lows[i] - self.closes[i-1])
                    ))
            self.atr = np.mean(trs)
        else:
            self.atr = None

    def _update_volatility_and_thresholds(self, close):
        if self.atr and close != 0:
            self.volatility_factor = self.atr / close
        else:
            self.volatility_factor = 0
        self.momentum_threshold = self.config['momentum_threshold_base'] * (1 + self.volatility_factor * 2)
        self.pre_momentum_threshold = self.momentum_threshold * self.config['sms_pre_momentum_factor'] * (1 - self.volatility_factor * 0.5)

    def _detect_swings(self):
        length = self.config['length']
        if self.bar_index < length * 2:
            return
        start = self.bar_index - length
        end = self.bar_index + length
        if end < len(self.highs):
            window_high = self.highs[start:end+1]
            if self.highs[-1] == max(window_high):
                self.last_high = self.highs[-1]
                self.last_high_idx = self.bar_index
                self._add_swing_point(self.bar_index, self.highs[-1], 1)
        window_low = self.lows[start:end+1]
        if self.lows[-1] == min(window_low):
            self.last_low = self.lows[-1]
            self.last_low_idx = self.bar_index
            self._add_swing_point(self.bar_index, self.lows[-1], -1)

    def _add_swing_point(self, x, y, direction):
        self.swing_points.append(SwingPoint(x, y, direction))
        if len(self.swing_points) > self.config['max_swing_points']:
            self.swing_points.pop(0)

    def _detect_mss_bos(self):
        if len(self.swing_points) < 2:
            return
        last = self.swing_points[-1]
        prev = None
        for sp in reversed(self.swing_points[:-1]):
            if sp.direction != last.direction:
                prev = sp
                break
        if prev is None:
            return
        recent, older = (last, prev) if last.x > prev.x else (prev, last)
        close = self.closes[-1]

        if close > older.y and older.direction == 1 and self.ms_dir < 1:
            self.ms_dir = 1
        elif close < older.y and older.direction == -1 and self.ms_dir > -1:
            self.ms_dir = -1

    def _detect_displacement(self, open, high, low, close):
        body = abs(close - open)
        if body == 0:
            return
        upper_wick = high - max(close, open)
        lower_wick = min(close, open) - low
        ratio = 0.36
        if upper_wick < body * ratio and lower_wick < body * ratio:
            direction = "up" if close > open else "down"
            self.displacements.append(Displacement(self.bar_index, direction))
            if len(self.displacements) > 10:
                self.displacements.pop(0)

    def _detect_volume_imbalance(self, open, high, low, close, volume):
        if self.bar_index < 1:
            return
        o_prev = self.opens[-2]
        h_prev = self.highs[-2]
        l_prev = self.lows[-2]
        c_prev = self.closes[-2]
        mn = min(close, open)
        mx = max(close, open)

        if open > c_prev and h_prev > l_prev and close > c_prev and open > o_prev and h_prev < mn:
            self._add_vi(self.bar_index, "bull")
        elif open < c_prev and l_prev < h_prev and close < c_prev and open < o_prev and l_prev > mx:
            self._add_vi(self.bar_index, "bear")

    def _add_vi(self, bar, direction):
        self.vi_items.append(VolumeImbalance(bar, direction, None))
        if len(self.vi_items) > self.config['max_vi']:
            self.vi_items.pop(0)

    def _detect_fvg(self):
        if self.bar_index < 2:
            return
        open = self.opens[-1]
        high = self.highs[-1]
        low = self.lows[-1]
        close = self.closes[-1]
        open1 = self.opens[-2]
        high1 = self.highs[-2]
        low1 = self.lows[-2]
        close1 = self.closes[-2]
        open2 = self.opens[-3]
        high2 = self.highs[-3]
        low2 = self.lows[-3]
        close2 = self.closes[-3]

        body1 = abs(close1 - open1)
        if body1 == 0:
            return
        upper_wick1 = high1 - max(close1, open1)
        lower_wick1 = min(close1, open1) - low1
        prev_displaced = (upper_wick1 < body1 * 0.36 and lower_wick1 < body1 * 0.36)
        if not prev_displaced:
            return

        fvg_type = self.config['fvg_type']
        if fvg_type == 'FVG':
            bull_fvg = low > high2
            bear_fvg = high < low2
        else:
            bull_fvg = low < high2
            bear_fvg = high > low2

        if bull_fvg:
            if fvg_type == 'FVG':
                top = low
                bottom = high2
            else:
                top = high2
                bottom = low
            self._add_fvg("bull", self.bar_index-2, top, self.bar_index, bottom)
        elif bear_fvg:
            if fvg_type == 'FVG':
                top = low2
                bottom = high
            else:
                top = high
                bottom = low2
            self._add_fvg("bear", self.bar_index-2, top, self.bar_index, bottom)

    def _add_fvg(self, direction, left, top, right, bottom):
        fvg = FVG(left=left, top=top, right=right, bottom=bottom, active=True, direction=direction)
        if direction == "bull":
            self.fvg_bull.append(fvg)
            if len(self.fvg_bull) > self.config['max_fvg']:
                self.fvg_bull.pop(0)
        else:
            self.fvg_bear.append(fvg)
            if len(self.fvg_bear) > self.config['max_fvg']:
                self.fvg_bear.pop(0)

    def _update_fvgs(self):
        current_low = self.lows[-1]
        current_high = self.highs[-1]
        for fvg in self.fvg_bull:
            if fvg.active:
                fvg.right = self.bar_index + 8
                if current_low < fvg.bottom:
                    fvg.right = self.bar_index
                    fvg.active = False
        for fvg in self.fvg_bear:
            if fvg.active:
                fvg.right = self.bar_index + 8
                if current_high > fvg.top:
                    fvg.right = self.bar_index
                    fvg.active = False

    def _detect_order_blocks(self):
        if self.bar_index < 1:
            return
        if self.last_high_idx is not None and self.last_high_idx < self.bar_index:
            if self.closes[-1] > self.last_high:
                start = self.last_high_idx + 1
                if start <= self.bar_index:
                    window_lows = self.lows[start:self.bar_index+1]
                    if window_lows:
                        min_low_idx = start + np.argmin(window_lows)
                        self.bull_obs.append(OrderBlock(
                            top=self.highs[min_low_idx],
                            bottom=self.lows[min_low_idx],
                            loc=min_low_idx,
                            breaker=False,
                            break_loc=None
                        ))
                        if len(self.bull_obs) > self.config['max_obs']:
                            self.bull_obs.pop(0)
        if self.last_low_idx is not None and self.last_low_idx < self.bar_index:
            if self.closes[-1] < self.last_low:
                start = self.last_low_idx + 1
                if start <= self.bar_index:
                    window_highs = self.highs[start:self.bar_index+1]
                    if window_highs:
                        max_high_idx = start + np.argmax(window_highs)
                        self.bear_obs.append(OrderBlock(
                            top=self.highs[max_high_idx],
                            bottom=self.lows[max_high_idx],
                            loc=max_high_idx,
                            breaker=False,
                            break_loc=None
                        ))
                        if len(self.bear_obs) > self.config['max_obs']:
                            self.bear_obs.pop(0)

    def _update_obs(self):
        current_close = self.closes[-1]
        for ob in self.bull_obs[:]:
            if not ob.breaker:
                if current_close < ob.bottom:
                    ob.breaker = True
                    ob.break_loc = self.bar_index
            else:
                if current_close > ob.top:
                    self.bull_obs.remove(ob)
        for ob in self.bear_obs[:]:
            if not ob.breaker:
                if current_close > ob.top:
                    ob.breaker = True
                    ob.break_loc = self.bar_index
            else:
                if current_close < ob.bottom:
                    self.bear_obs.remove(ob)

    def _compute_sms_signal(self) -> TradeSignal:
        if self.bar_index < 1:
            return TradeSignal.NEUTRAL
        price_change = ((self.closes[-1] - self.closes[-2]) / self.closes[-2]) * 100
        if self.config['use_sms_momentum_filter']:
            if price_change > self.momentum_threshold:
                return TradeSignal.BUY
            elif price_change < -self.momentum_threshold:
                return TradeSignal.SELL
        return TradeSignal.NEUTRAL

    def _get_ict_signal(self) -> TradeSignal:
        bullish = any(fvg.active and fvg.direction == "bull" for fvg in self.fvg_bull)
        bearish = any(fvg.active and fvg.direction == "bear" for fvg in self.fvg_bear)
        if not bullish and not bearish:
            bullish = any(not ob.breaker for ob in self.bull_obs)
            bearish = any(not ob.breaker for ob in self.bear_obs)
        if self.ms_dir == 1:
            bullish = True
        elif self.ms_dir == -1:
            bearish = True

        if bullish and not bearish:
            return TradeSignal.BUY
        if bearish and not bullish:
            return TradeSignal.SELL
        return TradeSignal.NEUTRAL

    def _get_combined_direction(self, news_sentiment: float = 0.0) -> TradeSignal:
        sms = self._compute_sms_signal()
        ict = self._get_ict_signal()

        if self.config.get('use_news_sentiment', False) and abs(news_sentiment) > 0.3:
            if news_sentiment > 0.5:
                ict = TradeSignal.BUY if ict != TradeSignal.SELL else TradeSignal.NEUTRAL
            elif news_sentiment < -0.5:
                ict = TradeSignal.SELL if ict != TradeSignal.BUY else TradeSignal.NEUTRAL

        if sms != TradeSignal.NEUTRAL:
            if self.config['require_fvg_confirmation'] and not self._has_fvg(sms):
                return TradeSignal.NEUTRAL
            if self.config['require_ob_confirmation'] and not self._has_ob(sms):
                return TradeSignal.NEUTRAL
            return sms
        return ict

    def _has_fvg(self, signal: TradeSignal) -> bool:
        if signal == TradeSignal.BUY:
            return any(fvg.active and fvg.direction == "bull" for fvg in self.fvg_bull)
        if signal == TradeSignal.SELL:
            return any(fvg.active and fvg.direction == "bear" for fvg in self.fvg_bear)
        return False

    def _has_ob(self, signal: TradeSignal) -> bool:
        if signal == TradeSignal.BUY:
            return any(not ob.breaker for ob in self.bull_obs)
        if signal == TradeSignal.SELL:
            return any(not ob.breaker for ob in self.bear_obs)
        return False

    def _get_best_entry(self, signal: TradeSignal) -> Tuple[Optional[float], str, Optional[float], str]:
        if signal == TradeSignal.NEUTRAL:
            return None, '', None, "No signal"

        current_close = self.closes[-1]

        if signal == TradeSignal.BUY and self.last_high_idx is not None:
            if current_close > self.last_high:
                return current_close, 'market', None, "SMS BOS break above last high"
        if signal == TradeSignal.SELL and self.last_low_idx is not None:
            if current_close < self.last_low:
                return current_close, 'market', None, "SMS BOS break below last low"

        if signal == TradeSignal.BUY:
            for ob in self.bull_obs:
                if not ob.breaker and ob.loc < self.bar_index:
                    limit = ob.bottom
                    if current_close > limit:
                        return limit, 'limit', limit, f"Bullish OB retest at {limit:.2f}"
        if signal == TradeSignal.SELL:
            for ob in self.bear_obs:
                if not ob.breaker and ob.loc < self.bar_index:
                    limit = ob.top
                    if current_close < limit:
                        return limit, 'limit', limit, f"Bearish OB retest at {limit:.2f}"

        if signal == TradeSignal.BUY:
            for fvg in self.fvg_bull:
                if fvg.active:
                    limit = fvg.bottom
                    if current_close > limit:
                        return limit, 'limit', limit, f"Bullish FVG retest at {limit:.2f}"
        if signal == TradeSignal.SELL:
            for fvg in self.fvg_bear:
                if fvg.active:
                    limit = fvg.top
                    if current_close < limit:
                        return limit, 'limit', limit, f"Bearish FVG retest at {limit:.2f}"

        return current_close, 'market', None, "Fallback market entry"

    def _reset_signal(self, new_signal: TradeSignal):
        self.signal_start_bar = self.bar_index
        self.signal_direction = new_signal
        self.trades_taken_in_signal = 0

    def _can_trade_aggressive(self) -> bool:
        if self.signal_direction == TradeSignal.NEUTRAL:
            return False
        return self.trades_taken_in_signal < self.config['min_trades_per_signal']

    def get_signal_detail(self, news_sentiment: float = 0.0) -> SignalDetail:
        direction = self._get_combined_direction(news_sentiment)

        if direction != self.signal_direction:
            self._reset_signal(direction)

        entry_price, entry_type, limit_price, comment = self._get_best_entry(direction)

        remaining = max(0, self.config['min_trades_per_signal'] - self.trades_taken_in_signal)
        aggressive = self._can_trade_aggressive() and remaining > 0

        if direction != TradeSignal.NEUTRAL:
            self.signal_history.append((self.bar_index, direction.value, entry_price or 0))
            if len(self.signal_history) > 50:
                self.signal_history.pop(0)

        return SignalDetail(
            direction=direction,
            entry_price=entry_price,
            trade_count=remaining,
            aggressive=aggressive,
            signal_start_bar=self.signal_start_bar,
            trades_taken=self.trades_taken_in_signal,
            entry_type=entry_type,
            limit_price=limit_price,
            comment=comment
        )

    def confirm_trade_placed(self):
        if self.signal_direction != TradeSignal.NEUTRAL:
            self.trades_taken_in_signal += 1
            self.session_trades += 1
            self.last_trade_bar = self.bar_index

    def reset_session(self):
        self.session_trades = 0
        self.trades_taken_in_signal = 0
        self.signal_direction = TradeSignal.NEUTRAL
        self.signal_start_bar = -1

    def get_signal_history(self):
        return self.signal_history