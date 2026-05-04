# modules/trading/reversal.py
import numpy as np
import pandas as pd
from scipy.signal import argrelextrema
from sklearn.linear_model import LinearRegression
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime
import MetaTrader5 as mt5
from config import TradingConfig
from modules.trading.indicator import CombinedICTandSMSIndicator, TradeSignal

# =============================================================================
# SUPPORT/RESISTANCE & TRENDLINE CLASSES
# =============================================================================

@dataclass
class SupportResistanceLevel:
    """Data class for support/resistance levels"""
    price: float
    type: str  # 'support' or 'resistance'
    strength: int  # number of touches
    last_touch_index: int
    is_broken: bool = False

@dataclass
class TrendLine:
    """Data class for trendlines"""
    slope: float
    intercept: float
    type: str  # 'uptrend' or 'downtrend'
    start_index: int
    end_index: int
    strength: int  # number of touches
    current_value: float

# =============================================================================
# MARKET ANALYZER
# =============================================================================

class MarketAnalyzer:
    """
    Market analyzer for trendlines and support/resistance levels.
    Uses historical OHLC data to find key levels.
    """
    
    def __init__(self, data: pd.DataFrame, lookback_period: int = 100):
        """
        Initialize analyzer with price data.
        data must have 'high', 'low', 'close' columns.
        """
        self.data = data.tail(lookback_period).reset_index(drop=True)
        self.highs = self.data['high'].values
        self.lows = self.data['low'].values
        self.closes = self.data['close'].values
        self.timestamps = self.data.index.values
        
    def find_local_extrema(self, order: int = 5) -> Tuple[np.ndarray, np.ndarray]:
        """Find local maxima and minima"""
        local_maxima = argrelextrema(self.highs, np.greater, order=order)[0]
        local_minima = argrelextrema(self.lows, np.less, order=order)[0]
        return local_maxima, local_minima
    
    def find_horizontal_levels(self, 
                              price_tolerance: float = 0.02, 
                              min_touches: int = 2) -> List[SupportResistanceLevel]:
        """Find horizontal support and resistance levels"""
        local_maxima, local_minima = self.find_local_extrema()
        levels = []
        
        # Resistance levels (local maxima)
        resistance_levels = {}
        for idx in local_maxima:
            price = self.highs[idx]
            found = False
            for existing_price in list(resistance_levels.keys()):
                if abs(price - existing_price) / existing_price <= price_tolerance:
                    resistance_levels[existing_price].append(idx)
                    found = True
                    break
            if not found:
                resistance_levels[price] = [idx]
        
        # Support levels (local minima)
        support_levels = {}
        for idx in local_minima:
            price = self.lows[idx]
            found = False
            for existing_price in list(support_levels.keys()):
                if abs(price - existing_price) / existing_price <= price_tolerance:
                    support_levels[existing_price].append(idx)
                    found = True
                    break
            if not found:
                support_levels[price] = [idx]
        
        for price, touches in resistance_levels.items():
            if len(touches) >= min_touches:
                levels.append(SupportResistanceLevel(
                    price=price, type='resistance', strength=len(touches),
                    last_touch_index=max(touches)))
        
        for price, touches in support_levels.items():
            if len(touches) >= min_touches:
                levels.append(SupportResistanceLevel(
                    price=price, type='support', strength=len(touches),
                    last_touch_index=max(touches)))
        
        levels.sort(key=lambda x: x.price)
        return levels
    
    def detect_trendlines(self, 
                         min_touches: int = 3,
                         max_touch_distance: float = 0.02) -> List[TrendLine]:
        """Detect trendlines using linear regression on local extrema"""
        local_maxima, local_minima = self.find_local_extrema(order=3)
        trendlines = []
        
        # Uptrend lines (higher lows)
        if len(local_minima) >= min_touches:
            for i in range(len(local_minima) - min_touches + 1):
                for j in range(i + min_touches - 1, len(local_minima)):
                    points = local_minima[i:j+1]
                    if len(points) >= min_touches:
                        X = points.reshape(-1, 1)
                        y = self.lows[points]
                        model = LinearRegression()
                        model.fit(X, y)
                        slope = model.coef_[0]
                        if slope > 0:  # uptrend
                            touches = 0
                            for p in points:
                                line_val = slope * p + model.intercept_
                                if abs(self.lows[p] - line_val) / line_val <= max_touch_distance:
                                    touches += 1
                            if touches >= min_touches:
                                trendlines.append(TrendLine(
                                    slope=slope, intercept=model.intercept_, type='uptrend',
                                    start_index=points[0], end_index=points[-1], strength=touches,
                                    current_value=slope * len(self.data) + model.intercept_))
        
        # Downtrend lines (lower highs)
        if len(local_maxima) >= min_touches:
            for i in range(len(local_maxima) - min_touches + 1):
                for j in range(i + min_touches - 1, len(local_maxima)):
                    points = local_maxima[i:j+1]
                    if len(points) >= min_touches:
                        X = points.reshape(-1, 1)
                        y = self.highs[points]
                        model = LinearRegression()
                        model.fit(X, y)
                        slope = model.coef_[0]
                        if slope < 0:  # downtrend
                            touches = 0
                            for p in points:
                                line_val = slope * p + model.intercept_
                                if abs(self.highs[p] - line_val) / line_val <= max_touch_distance:
                                    touches += 1
                            if touches >= min_touches:
                                trendlines.append(TrendLine(
                                    slope=slope, intercept=model.intercept_, type='downtrend',
                                    start_index=points[0], end_index=points[-1], strength=touches,
                                    current_value=slope * len(self.data) + model.intercept_))
        
        trendlines.sort(key=lambda x: x.strength, reverse=True)
        return trendlines
    
    def find_confluence_zones(self, 
                             levels: List[SupportResistanceLevel], 
                             trendlines: List[TrendLine],
                             zone_width: float = 0.01) -> List[Dict]:
        """Find confluence zones where horizontal levels intersect trendlines"""
        confluence_zones = []
        current_price = self.closes[-1]
        
        for level in levels:
            zone_low = level.price * (1 - zone_width)
            zone_high = level.price * (1 + zone_width)
            intersecting = [t for t in trendlines if zone_low <= t.current_value <= zone_high]
            if intersecting:
                confluence_zones.append({
                    'price': level.price, 'zone_low': zone_low, 'zone_high': zone_high,
                    'type': level.type, 'strength': level.strength + sum(t.strength for t in intersecting),
                    'intersecting_trendlines': len(intersecting),
                    'horizontal_strength': level.strength,
                    'trendline_strength': sum(t.strength for t in intersecting),
                    'distance_percent': abs(current_price - level.price) / current_price * 100
                })
        confluence_zones.sort(key=lambda x: x['strength'], reverse=True)
        return confluence_zones
    
    def get_nearest_levels(self, current_price: float) -> Tuple[Optional[float], Optional[float]]:
        """Return nearest support and resistance levels"""
        levels = self.find_horizontal_levels()
        nearest_support = None
        nearest_resistance = None
        for level in levels:
            if level.type == 'support' and level.price < current_price:
                if nearest_support is None or level.price > nearest_support:
                    nearest_support = level.price
            elif level.type == 'resistance' and level.price > current_price:
                if nearest_resistance is None or level.price < nearest_resistance:
                    nearest_resistance = level.price
        return nearest_support, nearest_resistance

# =============================================================================
# ENHANCED REVERSAL TRADER WITH 11 CONFIRMATION INDICATORS
# =============================================================================

class EnhancedReversalTrader:
    """
    Complete reversal trading system with 11 confirmation indicators:
    1. Price Confirmation (retest + candle pattern)
    2. Volatility Filter
    3. Volume Confirmation
    4. Momentum Filter
    5. Support/Resistance
    6. News Filter
    7. Time Filter
    8. Multi-Timeframe Confirmation
    9. Pattern Recognition
    10. Fibonacci Levels
    11. Trendline/SR
    """
    
    def __init__(self, config: TradingConfig, indicator: CombinedICTandSMSIndicator, 
                 logger, callback_queue, news_manager=None):
        self.config = config
        self.indicator = indicator
        self.logger = logger
        self.callback_queue = callback_queue
        self.news_manager = news_manager
        
        self.market_analyzer = None

        self.last_reversal_time = None
        self.reversal_trades_executed = 0
        self.reversal_history = []
        
    def calculate_atr(self, period: int = 14) -> float:
        """Calculate Average True Range"""
        if len(self.indicator.highs) < period:
            return 0
            
        tr_values = []
        for i in range(-period, 0):
            if i == -period:
                tr = self.indicator.highs[i] - self.indicator.lows[i]
            else:
                tr = max(
                    self.indicator.highs[i] - self.indicator.lows[i],
                    abs(self.indicator.highs[i] - self.indicator.closes[i-1]),
                    abs(self.indicator.lows[i] - self.indicator.closes[i-1])
                )
            tr_values.append(tr)
        
        return sum(tr_values) / len(tr_values)
    
    def calculate_momentum(self, period: int = 5) -> float:
        """Calculate momentum in pips"""
        if len(self.indicator.closes) < period + 1:
            return 0
            
        current_close = self.indicator.closes[-1]
        past_close = self.indicator.closes[-period-1]
        
        point_size = self.get_point_size()
        momentum_pips = abs(current_close - past_close) / point_size / 10
        
        return momentum_pips
    
    def get_point_size(self) -> float:
        """Get point size from symbol info"""
        try:
            symbol_info = mt5.symbol_info(self.config.symbol)
            if symbol_info:
                return symbol_info.point
        except:
            pass
        return 0.0001
    
    def get_current_price(self) -> float:
        """Get current price"""
        try:
            tick = mt5.symbol_info_tick(self.config.symbol)
            if tick:
                return (tick.bid + tick.ask) / 2
        except:
            pass
        return 0.0

    def check_trendline_sr(self, new_signal: TradeSignal, current_price: float) -> Tuple[bool, str, float]:
        """Check if price is at a confluence zone (trendline + horizontal S/R)"""
        if not self.config.reversal_use_trendline_sr:
            return True, "Trendline/SR filter disabled", 100.0
        
        if len(self.indicator.highs) < 50:
            return True, "Not enough data for trendline analysis", 80.0
        
        # Create DataFrame for the last 100 bars
        data = pd.DataFrame({
            'high': self.indicator.highs[-100:],
            'low': self.indicator.lows[-100:],
            'close': self.indicator.closes[-100:]
        })
        
        analyzer = MarketAnalyzer(data, lookback_period=min(100, len(data)))
        levels = analyzer.find_horizontal_levels(min_touches=2)
        trendlines = analyzer.detect_trendlines(min_touches=self.config.reversal_trendline_min_strength)
        confluences = analyzer.find_confluence_zones(levels, trendlines, 
                                                    zone_width=self.config.reversal_confluence_zone_width)
        
        for zone in confluences:
            if zone['zone_low'] <= current_price <= zone['zone_high']:
                if new_signal == TradeSignal.BUY and zone['type'] == 'support':
                    score = min(100, 50 + (zone['strength'] * 10))
                    return True, f"Price at confluence support zone (strength {zone['strength']})", score
                elif new_signal == TradeSignal.SELL and zone['type'] == 'resistance':
                    score = min(100, 50 + (zone['strength'] * 10))
                    return True, f"Price at confluence resistance zone (strength {zone['strength']})", score
        
        nearest_support, nearest_resistance = analyzer.get_nearest_levels(current_price)
        point_size = self.get_point_size()
        tolerance_pips = self.config.reversal_sr_tolerance_pips
        
        if new_signal == TradeSignal.BUY and nearest_support:
            distance = abs(current_price - nearest_support) / point_size / 10
            if distance <= tolerance_pips:
                score = 100 - (distance / tolerance_pips * 30)
                return True, f"Near support at {nearest_support:.5f} ({distance:.1f} pips)", score
        
        if new_signal == TradeSignal.SELL and nearest_resistance:
            distance = abs(nearest_resistance - current_price) / point_size / 10
            if distance <= tolerance_pips:
                score = 100 - (distance / tolerance_pips * 30)
                return True, f"Near resistance at {nearest_resistance:.5f} ({distance:.1f} pips)", score
        
        return False, "No significant S/R or trendline confluence", 40.0

    def check_higher_timeframe(self, new_signal: TradeSignal) -> Tuple[bool, str, float]:
        """Check alignment with higher timeframe trend"""
        if not self.config.reversal_require_higher_tf_alignment:
            return True, "Higher TF filter disabled", 100.0
        
        try:
            if self.config.symbol:
                rates_h1 = mt5.copy_rates_from_pos(self.config.symbol, mt5.TIMEFRAME_H1, 0, 50)
                if rates_h1 is not None and len(rates_h1) > 20:
                    closes = [bar[4] for bar in rates_h1]
                    sma_fast = sum(closes[-10:]) / 10
                    sma_slow = sum(closes[-20:]) / 20
                    
                    current_close = closes[-1]
                    
                    if sma_fast > sma_slow and current_close > sma_fast:
                        h1_trend = TradeSignal.BUY
                    elif sma_fast < sma_slow and current_close < sma_fast:
                        h1_trend = TradeSignal.SELL
                    else:
                        h1_trend = TradeSignal.NEUTRAL
                    
                    if new_signal == h1_trend:
                        return True, f"Aligned with H1 trend ({h1_trend.value})", 100.0
                    else:
                        return False, f"Not aligned with H1 trend (H1: {h1_trend.value})", 50.0
        except Exception as e:
            self.logger.debug(f"Higher TF check error: {e}")
        
        return True, "Higher TF analysis incomplete", 70.0
    
    # ============================================================
    # CONFIRMATION INDICATOR 1: PRICE CONFIRMATION
    # ============================================================
    
    def check_price_confirmation(self, new_signal: TradeSignal, entry_price: float) -> Tuple[bool, str, float]:
        """Check if price confirms reversal with retest and candle pattern"""
        if not self.config.reversal_require_retest:
            return True, "Retest not required", 100.0
            
        if new_signal == TradeSignal.BUY:
            recent_lows = [sp for sp in self.indicator.swing_points[-20:] if sp.direction == -1]
            if not recent_lows:
                return False, "No recent low for retest", 0.0
            
            retest_level = max(sp.y for sp in recent_lows)
            current_price = self.get_current_price()
            distance_pips = abs(current_price - retest_level) / self.get_point_size() / 10
            
            if distance_pips <= self.config.reversal_retest_tolerance_pips:
                if self.config.reversal_require_confirmation_candle:
                    if self.is_bullish_confirmation_candle():
                        return True, f"Retest at {retest_level:.5f} with bullish candle", 100.0
                    else:
                        return False, f"Retest at {retest_level:.5f} but no bullish candle", 50.0
                return True, f"Clean retest at {retest_level:.5f}", 90.0
            else:
                return False, f"Price {distance_pips:.1f}pips from retest level", 30.0
                
        else:
            recent_highs = [sp for sp in self.indicator.swing_points[-20:] if sp.direction == 1]
            if not recent_highs:
                return False, "No recent high for retest", 0.0
            
            retest_level = min(sp.y for sp in recent_highs)
            current_price = self.get_current_price()
            distance_pips = abs(retest_level - current_price) / self.get_point_size() / 10
            
            if distance_pips <= self.config.reversal_retest_tolerance_pips:
                if self.config.reversal_require_confirmation_candle:
                    if self.is_bearish_confirmation_candle():
                        return True, f"Retest at {retest_level:.5f} with bearish candle", 100.0
                    else:
                        return False, f"Retest at {retest_level:.5f} but no bearish candle", 50.0
                return True, f"Clean retest at {retest_level:.5f}", 90.0
            else:
                return False, f"Price {distance_pips:.1f}pips from retest level", 30.0
    
    def is_bullish_confirmation_candle(self) -> bool:
        """Check if last candle is bullish confirmation"""
        if len(self.indicator.opens) < 2:
            return False
            
        open_price = self.indicator.opens[-1]
        close_price = self.indicator.closes[-1]
        high = self.indicator.highs[-1]
        low = self.indicator.lows[-1]
        
        candle_range = high - low
        body = abs(close_price - open_price)
        body_percent = (body / candle_range) * 100 if candle_range > 0 else 0
        
        if close_price > open_price and body_percent >= self.config.reversal_confirmation_candle_body_percent:
            if len(self.indicator.highs) > 1 and close_price > self.indicator.highs[-2]:
                return True
        return False
    
    def is_bearish_confirmation_candle(self) -> bool:
        """Check if last candle is bearish confirmation"""
        if len(self.indicator.opens) < 2:
            return False
            
        open_price = self.indicator.opens[-1]
        close_price = self.indicator.closes[-1]
        high = self.indicator.highs[-1]
        low = self.indicator.lows[-1]
        
        candle_range = high - low
        body = abs(close_price - open_price)
        body_percent = (body / candle_range) * 100 if candle_range > 0 else 0
        
        if close_price < open_price and body_percent >= self.config.reversal_confirmation_candle_body_percent:
            if len(self.indicator.lows) > 1 and close_price < self.indicator.lows[-2]:
                return True
        return False
    
    # ============================================================
    # CONFIRMATION INDICATOR 2: VOLATILITY FILTER
    # ============================================================
    
    def check_volatility(self) -> Tuple[bool, str, float]:
        """Check if volatility is within acceptable range"""
        if not self.config.reversal_use_volatility_filter:
            return True, "Volatility filter disabled", 100.0
            
        atr = self.calculate_atr(self.config.reversal_volatility_lookback)
        current_price = self.get_current_price()
        
        if atr == 0 or current_price == 0:
            return False, "Cannot calculate volatility", 0.0
            
        atr_percent = (atr / current_price) * 100
        
        if atr_percent < self.config.reversal_min_atr_percent:
            return False, f"Volatility too low: {atr_percent:.2f}%", 30.0
        elif atr_percent > self.config.reversal_max_atr_percent:
            return False, f"Volatility too high: {atr_percent:.2f}%", 30.0
        else:
            ideal_range = self.config.reversal_max_atr_percent - self.config.reversal_min_atr_percent
            current_position = atr_percent - self.config.reversal_min_atr_percent
            score = (current_position / ideal_range) * 100 if ideal_range > 0 else 100
            return True, f"Volatility OK: {atr_percent:.2f}%", score
    
    # ============================================================
    # CONFIRMATION INDICATOR 3: VOLUME CONFIRMATION
    # ============================================================
    
    def check_volume(self) -> Tuple[bool, str, float]:
        """Check for volume confirmation"""
        if not self.config.reversal_require_volume_spike:
            return True, "Volume filter disabled", 100.0
            
        if len(self.indicator.volumes) < self.config.reversal_volume_lookback + 1:
            return False, "Not enough volume data", 0.0
            
        current_volume = self.indicator.volumes[-1]
        avg_volume = sum(self.indicator.volumes[-self.config.reversal_volume_lookback:-1]) / self.config.reversal_volume_lookback
        
        if avg_volume == 0:
            return False, "Zero average volume", 0.0
            
        volume_ratio = current_volume / avg_volume
        
        if volume_ratio >= self.config.reversal_volume_multiplier:
            score = min(100, (volume_ratio / self.config.reversal_volume_multiplier) * 100)
            return True, f"Volume spike: {volume_ratio:.2f}x average", score
        else:
            return False, f"Volume too low: {volume_ratio:.2f}x average", 30.0
    
    # ============================================================
    # CONFIRMATION INDICATOR 4: MOMENTUM FILTER
    # ============================================================
    
    def check_momentum(self) -> Tuple[bool, str, float]:
        """Check momentum in the new direction"""
        if not self.config.reversal_use_momentum_filter:
            return True, "Momentum filter disabled", 100.0
            
        momentum_pips = self.calculate_momentum(self.config.reversal_momentum_period)
        
        if momentum_pips >= self.config.reversal_min_momentum_pips:
            score = min(100, (momentum_pips / self.config.reversal_min_momentum_pips) * 100)
            return True, f"Momentum OK: {momentum_pips:.1f} pips", score
        else:
            return False, f"Momentum too weak: {momentum_pips:.1f} pips", 30.0
    
    # ============================================================
    # CONFIRMATION INDICATOR 5: SUPPORT/RESISTANCE
    # ============================================================
    
    def check_support_resistance(self, new_signal: TradeSignal) -> Tuple[bool, str, float]:
        """Check if price is near support/resistance"""
        if not self.config.reversal_check_support_resistance:
            return True, "S/R filter disabled", 100.0
            
        highs = [sp for sp in self.indicator.swing_points[-self.config.reversal_sr_lookback_bars:] 
                 if sp.direction == 1]
        lows = [sp for sp in self.indicator.swing_points[-self.config.reversal_sr_lookback_bars:] 
                if sp.direction == -1]
        
        if not highs or not lows:
            return True, "Not enough swing points", 70.0
            
        current_price = self.get_current_price()
        point_size = self.get_point_size()
        
        if new_signal == TradeSignal.BUY:
            nearest_support = max([low.y for low in lows if low.y < current_price + (50 * point_size)], 
                                   default=None)
            if nearest_support:
                distance_pips = abs(current_price - nearest_support) / point_size / 10
                if distance_pips <= self.config.reversal_sr_tolerance_pips:
                    score = 100 - (distance_pips / self.config.reversal_sr_tolerance_pips * 30)
                    return True, f"Near support: {nearest_support:.5f}", score
                else:
                    return False, f"Too far from support: {distance_pips:.1f}pips", 30.0
            else:
                return False, "No nearby support found", 40.0
        else:
            nearest_resistance = min([high.y for high in highs if high.y > current_price - (50 * point_size)],
                                      default=None)
            if nearest_resistance:
                distance_pips = abs(nearest_resistance - current_price) / point_size / 10
                if distance_pips <= self.config.reversal_sr_tolerance_pips:
                    score = 100 - (distance_pips / self.config.reversal_sr_tolerance_pips * 30)
                    return True, f"Near resistance: {nearest_resistance:.5f}", score
                else:
                    return False, f"Too far from resistance: {distance_pips:.1f}pips", 30.0
            else:
                return False, "No nearby resistance found", 40.0
    
    # ============================================================
    # CONFIRMATION INDICATOR 6: NEWS FILTER
    # ============================================================
    
    def check_news(self) -> Tuple[bool, str, float]:
        """Check if there's high-impact news"""
        if not self.config.reversal_avoid_high_impact_news:
            return True, "News filter disabled", 100.0
            
        if not self.news_manager:
            return True, "No news manager available", 80.0
            
        news = self.news_manager.fetch_news()
        current_time = datetime.now()
        
        for event in news:
            if event.get('impact') == 'High':
                event_time_str = f"{event.get('date', '')} {event.get('time', '')}"
                try:
                    event_time = datetime.strptime(event_time_str, '%Y-%m-%d %H:%M')
                    time_diff = abs((event_time - current_time).total_seconds() / 60)
                    if time_diff <= self.config.reversal_news_buffer_minutes:
                        return False, f"High-impact news: {event.get('event')} in {time_diff:.0f}min", 20.0
                except:
                    continue
        
        return True, "No high-impact news near", 90.0
    
    # ============================================================
    # CONFIRMATION INDICATOR 7: TIME FILTER
    # ============================================================
    
    def check_time(self) -> Tuple[bool, str, float]:
        """
        Check if current time is good for trading.
        If the time filter is disabled (reversal_use_time_filter = False), always return True.
        """
        # If time filter is disabled, skip all checks
        if not getattr(self.config, 'reversal_use_time_filter', True):
            return True, "Time filter disabled", 100.0

        current_hour = datetime.now().hour
        current_weekday = datetime.now().weekday()

        # Weekend check
        if current_weekday >= 5:
            return False, "Weekend - market closed", 0.0

        # Preferred hours
        start = self.config.reversal_preferred_hours_start
        end = self.config.reversal_preferred_hours_end
        if start <= current_hour < end:
            score = 100.0
            time_ok = True
            reason = f"Within preferred hours ({start}-{end})"
        else:
            score = 50.0
            time_ok = True
            reason = f"Outside preferred hours ({start}-{end})"

        # Friday afternoon check (avoid if enabled)
        if self.config.reversal_avoid_friday_afternoon and current_weekday == 4 and current_hour >= 17:
            return False, "Friday afternoon - avoiding", 0.0

        # London close check (roughly 16-17 GMT) – reduces score but does not block completely
        if self.config.reversal_avoid_london_close and 16 <= current_hour < 17:
            score *= 0.5
            reason += " (London close)"

        return time_ok, reason, score
 
    # ============================================================
    # CONFIRMATION INDICATOR 9: PATTERN RECOGNITION
    # ============================================================
    
    def check_pattern(self) -> Tuple[bool, str, float]:
        """Check for specific reversal patterns"""
        if not self.config.reversal_require_pattern:
            return True, "Pattern filter disabled", 100.0
            
        if self.is_pin_bar():
            return True, "PIN BAR detected", 90.0
        if self.is_engulfing():
            return True, "ENGULFING pattern detected", 90.0
        if self.is_inside_bar():
            return True, "INSIDE BAR detected", 80.0
        if self.is_morning_star():
            return True, "MORNING STAR detected", 95.0
        if self.is_evening_star():
            return True, "EVENING STAR detected", 95.0
            
        return False, "No reversal pattern detected", 30.0
    
    def is_pin_bar(self) -> bool:
        if len(self.indicator.opens) < 1:
            return False
        open_price = self.indicator.opens[-1]
        close_price = self.indicator.closes[-1]
        high = self.indicator.highs[-1]
        low = self.indicator.lows[-1]
        candle_range = high - low
        body = abs(close_price - open_price)
        lower_wick = min(open_price, close_price) - low
        upper_wick = high - max(open_price, close_price)
        if body < candle_range / 3:
            if lower_wick > candle_range * 0.66:
                return True
            if upper_wick > candle_range * 0.66:
                return True
        return False
    
    def is_engulfing(self) -> bool:
        if len(self.indicator.opens) < 2:
            return False
        prev_open = self.indicator.opens[-2]
        prev_close = self.indicator.closes[-2]
        curr_open = self.indicator.opens[-1]
        curr_close = self.indicator.closes[-1]
        if (prev_close < prev_open and curr_close > curr_open and
            curr_open < prev_close and curr_close > prev_open):
            return True
        if (prev_close > prev_open and curr_close < curr_open and
            curr_open > prev_close and curr_close < prev_open):
            return True
        return False
    
    def is_inside_bar(self) -> bool:
        if len(self.indicator.opens) < 2:
            return False
        prev_high = self.indicator.highs[-2]
        prev_low = self.indicator.lows[-2]
        curr_high = self.indicator.highs[-1]
        curr_low = self.indicator.lows[-1]
        if curr_high <= prev_high and curr_low >= prev_low:
            return True
        return False
    
    def is_morning_star(self) -> bool:
        if len(self.indicator.opens) < 3:
            return False
        if self.indicator.closes[-3] >= self.indicator.opens[-3]:
            return False
        body2 = abs(self.indicator.closes[-2] - self.indicator.opens[-2])
        range2 = self.indicator.highs[-2] - self.indicator.lows[-2]
        if body2 / range2 > 0.3:
            return False
        if self.indicator.closes[-1] <= self.indicator.opens[-1]:
            return False
        midpoint1 = (self.indicator.highs[-3] + self.indicator.lows[-3]) / 2
        if self.indicator.closes[-1] <= midpoint1:
            return False
        return True
    
    def is_evening_star(self) -> bool:
        if len(self.indicator.opens) < 3:
            return False
        if self.indicator.closes[-3] <= self.indicator.opens[-3]:
            return False
        body2 = abs(self.indicator.closes[-2] - self.indicator.opens[-2])
        range2 = self.indicator.highs[-2] - self.indicator.lows[-2]
        if body2 / range2 > 0.3:
            return False
        if self.indicator.closes[-1] >= self.indicator.opens[-1]:
            return False
        midpoint1 = (self.indicator.highs[-3] + self.indicator.lows[-3]) / 2
        if self.indicator.closes[-1] >= midpoint1:
            return False
        return True
    
    # ============================================================
    # CONFIRMATION INDICATOR 10: FIBONACCI LEVELS
    # ============================================================
    
    def check_fibonacci(self, new_signal: TradeSignal, entry_price: float) -> Tuple[bool, str, float]:
        """Check if entry is at Fibonacci level"""
        if not self.config.reversal_use_fibonacci:
            return True, "Fibonacci filter disabled", 100.0
            
        recent_highs = [sp for sp in self.indicator.swing_points[-30:] if sp.direction == 1]
        recent_lows = [sp for sp in self.indicator.swing_points[-30:] if sp.direction == -1]
        
        if not recent_highs or not recent_lows:
            return True, "Not enough swing points for Fib", 70.0
            
        swing_high = max(sp.y for sp in recent_highs)
        swing_low = min(sp.y for sp in recent_lows)
        
        fib_range = swing_high - swing_low
        point_size = self.get_point_size()
        
        for level in self.config.reversal_fib_levels:
            if new_signal == TradeSignal.BUY:
                fib_price = swing_low + (fib_range * level)
            else:
                fib_price = swing_high - (fib_range * level)
                
            distance_pips = abs(entry_price - fib_price) / point_size / 10
            
            if distance_pips <= self.config.reversal_fib_tolerance_pips:
                score = 100 - (distance_pips / self.config.reversal_fib_tolerance_pips * 20)
                return True, f"Entry at Fib {level*100:.0f}%", score
                
        return False, f"No Fib level within {self.config.reversal_fib_tolerance_pips}pips", 40.0
    
    # ============================================================
    # MAIN CONFIDENCE CALCULATION
    # ============================================================
    
    def calculate_reversal_confidence(self, new_signal: TradeSignal, old_signal: TradeSignal) -> Dict:
        """
        Calculate confidence score for reversal setup using all 11 indicators
        """
        current_price = self.get_current_price()
        
        checks = [
            ("price", self.check_price_confirmation(new_signal, current_price)),
            ("volatility", self.check_volatility()),
            ("volume", self.check_volume()),
            ("momentum", self.check_momentum()),
            ("support_resistance", self.check_support_resistance(new_signal)),
            ("news", self.check_news()),
            ("time", self.check_time()),
            ("higher_tf", self.check_higher_timeframe(new_signal)),
            ("pattern", self.check_pattern()),
            ("fibonacci", self.check_fibonacci(new_signal, current_price)),
            ("trendline_sr", self.check_trendline_sr(new_signal, current_price)),
        ]
        
        total_score = 0
        total_weight = 0
        results = {}
        
        weights = {
            "price": 2.0,
            "pattern": 2.0,
            "volatility": 1.5,
            "volume": 1.5,
            "support_resistance": 1.5,
            "momentum": 1.2,
            "fibonacci": 1.2,
            "higher_tf": 1.2,
            "news": 1.0,
            "time": 1.0,
            "trendline_sr": 1.2,
        }
        
        for check_name, (passed, reason, score) in checks:
            weight = weights.get(check_name, 1.0)
            
            results[check_name] = {
                "passed": passed,
                "reason": reason,
                "score": score,
                "weight": weight
            }
            
            if passed:
                total_score += score * weight
            else:
                total_score += score * weight * 0.3
                
            total_weight += weight
        
        overall_confidence = total_score / total_weight if total_weight > 0 else 0
        
        if self.config.reversal_min_confidence_score <= 0:
            should_trade = True
        else:
            should_trade = overall_confidence >= self.config.reversal_min_confidence_score
        
        passed_count = sum(1 for r in results.values() if r["passed"])
        total_checks = len(checks)
        
        self.reversal_history.append({
            "timestamp": datetime.now().isoformat(),
            "old_signal": old_signal.value,
            "new_signal": new_signal.value,
            "confidence": overall_confidence,
            "should_trade": should_trade,
            "passed_checks": passed_count,
            "details": {k: v["reason"] for k, v in results.items()},
            "min_confidence": self.config.reversal_min_confidence_score
        })
        
        if len(self.reversal_history) > 50:
            self.reversal_history.pop(0)
        
        return {
            "overall_confidence": overall_confidence,
            "should_trade": should_trade,
            "passed_checks": passed_count,
            "total_checks": total_checks,
            "pass_rate": (passed_count / total_checks) * 100,
            "details": results,
            "timestamp": datetime.now().isoformat()
        }
    
    def should_execute_reversal(self, new_signal: TradeSignal, old_signal: TradeSignal) -> Tuple[bool, str, Dict]:
        """
        Main decision function - determines if reversal should be executed
        """
        confidence_data = self.calculate_reversal_confidence(new_signal, old_signal)
        
        if self.config.reversal_min_confidence_score <= 0:
            self.logger.info("=" * 70)
            self.logger.info(f"📊 REVERSAL EXECUTION (MIN CONFIDENCE = 0%)")
            self.logger.info(f"   Overall Confidence: {confidence_data['overall_confidence']:.1f}%")
            self.logger.info(f"   Passed Checks: {confidence_data['passed_checks']}/{confidence_data['total_checks']}")
            self.logger.info(f"✅ DECISION: EXECUTING ALL REVERSALS (min_confidence = 0%)")
            self.logger.info("=" * 70)
            confidence_data['should_trade'] = True
            return True, f"Reversal executed (min_confidence = 0%)", confidence_data
        
        self.logger.info("=" * 70)
        self.logger.info(f"📊 REVERSAL CONFIDENCE ANALYSIS")
        self.logger.info(f"   Overall Confidence: {confidence_data['overall_confidence']:.1f}%")
        self.logger.info(f"   Passed Checks: {confidence_data['passed_checks']}/{confidence_data['total_checks']}")
        
        for check, data in confidence_data['details'].items():
            status = "✅" if data['passed'] else "❌"
            self.logger.info(f"   {status} {check.upper()}: {data['reason']} (score: {data['score']:.1f})")
        
        if confidence_data['overall_confidence'] >= self.config.reversal_min_confidence_score:
            self.logger.info(f"✅ DECISION: EXECUTE REVERSAL with {confidence_data['overall_confidence']:.1f}% confidence")
            self.logger.info("=" * 70)
            return True, f"Reversal confirmed with {confidence_data['overall_confidence']:.1f}% confidence", confidence_data
        else:
            self.logger.info(f"❌ DECISION: SKIP REVERSAL - only {confidence_data['overall_confidence']:.1f}% confidence (need {self.config.reversal_min_confidence_score}%)")
            self.logger.info("=" * 70)
            return False, f"Reversal rejected - only {confidence_data['overall_confidence']:.1f}% confidence", confidence_data