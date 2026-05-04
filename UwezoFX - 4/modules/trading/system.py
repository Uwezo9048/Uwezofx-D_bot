# modules/trading/system.py
import sys
import threading
import time
import queue
import signal
import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Optional, Dict, Any
import numpy as np
import MetaTrader5 as mt5
from config import TradingConfig
from modules.utils.logger import setup_logger
from modules.trading.indicator import (
    CombinedICTandSMSIndicator, TradeSignal, OrderType, PositionStatus, SignalDetail, Trade
)
from modules.trading.reversal import EnhancedReversalTrader
from modules.trading.trailing import TrailingStopLoss
from modules.alerts.alert_system import AlertSystem
from modules.news.myfxbook import MyfxbookNewsManager

def find_mt5_terminal():
    """Locate MetaTrader 5 terminal on Windows 7, 8, 10, 11"""
    import os
    import sys
    
    # Try to find via registry (works on all Windows versions)
    try:
        import winreg
        # Check both CurrentUser and LocalMachine
        registry_paths = [
            (winreg.HKEY_CURRENT_USER, r"Software\MetaQuotes\MT5"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\MetaQuotes\MT5"),
            (winreg.HKEY_CURRENT_USER, r"Software\MetaQuotes\Terminal"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\MetaQuotes\Terminal"),
        ]
        
        for hive, subkey in registry_paths:
            try:
                key = winreg.OpenKey(hive, subkey)
                path = winreg.QueryValueEx(key, "Path")[0]
                winreg.CloseKey(key)
                
                # Check for terminal executable
                for exe_name in ["terminal64.exe", "terminal.exe"]:
                    terminal_path = os.path.join(path, exe_name)
                    if os.path.exists(terminal_path):
                        return terminal_path
            except Exception:
                continue
    except ImportError:
        # winreg not available (shouldn't happen on Windows)
        pass
    
    # Common installation paths for all Windows versions
    common_paths = [
        # Standard Program Files
        r"C:\Program Files\MetaTrader 5\terminal64.exe",
        r"C:\Program Files\MetaTrader 5\terminal.exe",
        r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe",
        r"C:\Program Files (x86)\MetaTrader 5\terminal.exe",
        # User-specific installations
        os.path.expanduser(r"~\AppData\Local\Programs\MetaTrader 5\terminal64.exe"),
        os.path.expanduser(r"~\AppData\Roaming\MetaQuotes\Terminal\Common\terminal.exe"),
        # Windows 7/8 default paths
        r"C:\MT5\terminal64.exe",
        r"C:\MT5\terminal.exe",
        # Windows 10/11 paths
        os.path.expanduser(r"~\AppData\Roaming\MetaQuotes\WebTerminal\terminal64.exe"),
        # Desktop shortcuts (resolve to actual path)
        os.path.expanduser(r"~\Desktop\MetaTrader 5.lnk"),
    ]
    
    for path in common_paths:
        if os.path.exists(path):
            return path
    
    # If .lnk file found, resolve it
    lnk_path = os.path.expanduser(r"~\Desktop\MetaTrader 5.lnk")
    if os.path.exists(lnk_path):
        try:
            import comtypes.client
            shell = comtypes.client.CreateObject("WScript.Shell")
            shortcut = shell.CreateShortcut(lnk_path)
            target_path = shortcut.TargetPath
            if os.path.exists(target_path):
                return target_path
        except Exception:
            pass
    
    return None

class TradingSystem:
    """Complete trading system with ICT/SMS indicator, trailing stop, and enhanced reversal confirmation"""

    def __init__(self, config: TradingConfig = None, callback_queue=None):
        self.config = config or TradingConfig()
        self.callback_queue = callback_queue
        self.setup_logging()

        self._last_reset_date = datetime.now().date()

        self.alert_system = AlertSystem(self.logger, self.callback_queue)

        self.last_overbought_alert = False
        self.last_oversold_alert = False
        self.last_rsi_value = 50

        # Initialize indicators
        self.indicator_5min = CombinedICTandSMSIndicator(self._build_indicator_config(mode='normal_5min'))
        self.indicator_15min = CombinedICTandSMSIndicator(self._build_indicator_config(mode='normal_15min'))
        self.indicator_sts_1min = CombinedICTandSMSIndicator(self._build_indicator_config(mode='sts_1min'))
        self.indicator_sts_5min = CombinedICTandSMSIndicator(self._build_indicator_config(mode='sts_5min'))

        self.last_bar_time_5min = None
        self.last_bar_time_15min = None
        self.last_bar_time_1min = None

        self.trailing_stop = TrailingStopLoss(self.config, self.logger, self.callback_queue)
        self.trailing_stop.set_alert_system(self.alert_system)

        self.news_manager = MyfxbookNewsManager(self.config, self.logger, self.callback_queue)

        # Initialize Enhanced Reversal Trader
        self.reversal_trader = EnhancedReversalTrader(
            self.config,
            self.indicator_5min,
            self.logger,
            self.callback_queue,
            self.news_manager
        )

        self.setup_trailing_callbacks()

        self.running = False
        self.trading_enabled = True
        self.account_balance = 0.0
        self.account_equity = 0.0
        self.peak_equity = 0.0
        self.current_drawdown = 0.0
        self.mt5_connected = True

        self.aggressive_mode = False
        self.last_trade_time = None
        self.aggressive_trades_this_minute = 0
        self.minute_start_time = datetime.now()

        self.manual_pause = False
        self.last_signal_check = None

        self.current_signal = TradeSignal.NEUTRAL
        self.previous_signal = TradeSignal.NEUTRAL
        self.signal_start_time = None
        self.signal_trades = 0
        self.session_trades = 0

        self.use_sts = config.use_sts_signal
        self.current_signal_detail = None

        self.symbol_info = None
        self.symbol_properties = {}
        self.available_symbols: List[str] = []

        self.trade_history: List[Trade] = []
        self.open_positions: List[Trade] = []

        self.trading_lock = threading.RLock()
        self.last_mt5_check = {}

        self.trailing_sync_complete = False
        self.last_trailing_broadcast = datetime.now()

        self.last_pending_manage = datetime.now()

        # Add missing attributes
        self.session_market_trades = 0
        self.session_pending_orders = 0
        self.pending_trades = []

        self.manual_disconnect = False

        # Reversal tracking
        self.reversal_mode_enabled = config.enable_reversal_trading
        self.last_reversal_time = None
        self.reversal_trades_executed = 0
        self.max_reversal_trades = config.reversal_max_trades

        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        self.logger.info("=" * 70)
        self.logger.info("UWEZO-FX TRADING SYSTEM - PROFESSIONAL EDITION")
        self.logger.info(f"Mode: {'NORMAL' if not self.config.reversal_mode else 'REVERSED'}")
        self.logger.info(f"Auto Trading: {'ENABLED' if self.config.auto_trading else 'DISABLED'}")
        self.logger.info(f"STS Mode: {'ENABLED' if self.use_sts else 'DISABLED'}")
        self.logger.info(f"Trailing Stop: {'ENABLED' if self.config.enable_trailing_stop_loss else 'DISABLED'}")
        self.logger.info(f"News Sentiment: {'ENABLED' if self.config.use_news_sentiment else 'DISABLED'}")
        self.logger.info(f"Reversal Trading: {'ENABLED' if self.config.enable_reversal_trading else 'DISABLED'}")
        self.logger.info(f"Reversal Confirmation: 11 INDICATORS ACTIVE")
        self.logger.info(f"Max Trades/Session: 5")
        self.logger.info("=" * 70)

    def _build_indicator_config(self, mode='normal_5min') -> dict:
        base = {
            'use_ict_mss': self.config.use_ict_mss,
            'use_ict_bos': self.config.use_ict_bos,
            'use_ict_fvg': self.config.use_ict_fvg,
            'use_ict_ob': self.config.use_ict_ob,
            'use_ict_vi': self.config.use_ict_vi,
            'use_ict_displacement': self.config.use_ict_displacement,
            'use_sms_momentum_filter': self.config.use_sms_momentum_filter,
            'use_sms_trend_filter': self.config.use_sms_trend_filter,
            'use_sms_volume_filter': self.config.use_sms_volume_filter,
            'use_sms_breakout_filter': self.config.use_sms_breakout_filter,
            'use_sms_divergence': self.config.use_sms_divergence,
            'require_fvg_confirmation': self.config.require_fvg_confirmation,
            'require_ob_confirmation': self.config.require_ob_confirmation,
            'sms_pre_momentum_factor': self.config.sms_pre_momentum_factor,
            'rsi_period': self.config.rsi_period,
            'cci_period': self.config.cci_period,
            'williams_period': self.config.williams_period,
            'rsi_overbought': self.config.rsi_overbought,
            'rsi_oversold': self.config.rsi_oversold,
            'cci_overbought': self.config.cci_overbought,
            'cci_oversold': self.config.cci_oversold,
            'williams_overbought': self.config.williams_overbought,
            'williams_oversold': self.config.williams_oversold,
            'min_trades_per_signal': self.config.min_trades_per_signal,
            'max_trades_per_session': self.config.max_trades_per_session,
            'aggressive_trades_per_minute': self.config.aggressive_trades_per_minute,
            'min_signal_distance': self.config.min_signal_distance,
            'sms_volume_long_period': self.config.sms_volume_long_period,
            'sms_volume_short_period': self.config.sms_volume_short_period,
            'sms_breakout_period': self.config.sms_breakout_period,
            'max_vi': self.config.max_vi,
            'max_fvg': self.config.max_fvg,
            'max_obs': self.config.max_obs,
            'max_swing_points': self.config.max_swing_points,
            'fvg_type': self.config.fvg_type,
            'use_body_for_ob': self.config.use_body_for_ob,
            'use_news_sentiment': self.config.use_news_sentiment,
        }
        if mode == 'normal_5min':
            base.update({
                'length': self.config.normal_length,
                'atr_period': self.config.normal_atr_period,
                'momentum_threshold_base': self.config.normal_momentum_threshold_base,
            })
        elif mode == 'normal_15min':
            base.update({
                'length': self.config.normal_length + 2,
                'atr_period': self.config.normal_atr_period + 3,
                'momentum_threshold_base': self.config.normal_momentum_threshold_base * 0.8,
            })
        elif mode == 'sts_1min':
            base.update({
                'length': 2,
                'atr_period': 5,
                'momentum_threshold_base': self.config.sts_momentum_threshold_base * 1.5,
            })
        else:  # sts_5min
            base.update({
                'length': self.config.sts_length,
                'atr_period': self.config.sts_atr_period,
                'momentum_threshold_base': self.config.sts_momentum_threshold_base,
            })
        return base

    def setup_logging(self):
        self.logger = setup_logger(
            name="UWEZO_X_Trading",
            log_level=getattr(logging, self.config.log_level),
            log_file=self.config.log_file
        )

    def setup_trailing_callbacks(self):
        def on_position_closed(position):
            self.logger.info(f"Trailing stop: Position {position.ticket} closed, P&L: ${position.profit:.2f}")
            if self.callback_queue:
                try:
                    self.callback_queue.put_nowait(('trailing_stats_update', {
                        'position_closed': position.ticket,
                        'profit': position.profit
                    }))
                except:
                    pass

        def on_stop_loss_triggered(position):
            self.logger.warning(f"Trailing stop loss triggered for position {position.ticket}")
            if self.callback_queue:
                try:
                    self.callback_queue.put_nowait(('trailing_stop_loss', {
                        'ticket': position.ticket,
                        'profit': position.profit
                    }))
                except:
                    pass

        def on_take_profit_triggered(position):
            self.logger.info(f"Trailing take profit triggered for position {position.ticket}")
            if self.callback_queue:
                try:
                    self.callback_queue.put_nowait(('trailing_take_profit', {
                        'ticket': position.ticket,
                        'profit': position.profit
                    }))
                except:
                    pass

        self.trailing_stop.set_callback('on_position_closed', on_position_closed)
        self.trailing_stop.set_callback('on_stop_loss_triggered', on_stop_loss_triggered)
        self.trailing_stop.set_callback('on_take_profit_triggered', on_take_profit_triggered)
    
    def _attempt_reconnect(self) -> bool:
        if self.manual_disconnect:
            self.logger.info("Manual disconnect – not attempting auto‑reconnect")
            return False
        try:
            mt5.shutdown()
            time.sleep(1)
            if mt5.initialize():
                if self.config.symbol:
                    mt5.symbol_select(self.config.symbol, True)
                    self.get_symbol_properties()
                self.mt5_connected = True
                self.logger.info("MT5 reconnection successful")
                self.alert_system.alert_connection_restored()
                if self.config.enable_trailing_stop_loss:
                    self.sync_existing_positions_with_trailing()
                return True
            else:
                self.logger.error(f"MT5 reconnection failed: {mt5.last_error()}")
                return False
        except Exception as e:
            self.logger.error(f"Reconnection error: {e}")
            return False

    # ========== Initialization and MT5 Connection ==========

    def initialize(self) -> bool:
        try:
            self.logger.info("Initializing MetaTrader 5 connection...")
            
            # Detect Windows version
            from modules.utils.helpers import get_windows_version, is_windows_7_or_8
            win_version = get_windows_version()
            self.logger.info(f"Detected Windows version: {win_version}")
            
            # Find MT5 terminal
            terminal_path = find_mt5_terminal()
            self.logger.info(f"MT5 terminal path: {terminal_path}")
            
            # Windows 7/8 may need special handling
            if is_windows_7_or_8():
                self.logger.info("Applying Windows 7/8 compatibility settings")
                # On Windows 7/8, try without path first, then with path
                initialized = mt5.initialize()
                if not initialized and terminal_path:
                    initialized = mt5.initialize(path=terminal_path)
            else:
                # Windows 10/11: use path if found
                if terminal_path:
                    initialized = mt5.initialize(path=terminal_path)
                else:
                    initialized = mt5.initialize()
            
            if not initialized:
                error_msg = f"MT5 initialization failed: {mt5.last_error()}"
                self.logger.error(error_msg)
                self.mt5_connected = False
                self.alert_system.alert_connection_lost()
                if self.callback_queue:
                    try:
                        self.callback_queue.put_nowait(('error', "MT5 not connected"))
                    except:
                        pass
                return False
            else:
                self.mt5_connected = True
                self.alert_system.alert_connection_restored()

            self.scan_available_symbols()

            if self.config.symbol is not None:
                self.logger.info(f"Selecting symbol {self.config.symbol}...")
                selected = False
                for attempt in range(3):
                    if mt5.symbol_select(self.config.symbol, True):
                        selected = True
                        break
                    self.logger.warning(f"Attempt {attempt+1} to select {self.config.symbol} failed, retrying...")
                    time.sleep(2)
                if not selected:
                    self.logger.warning(f"Failed to select symbol {self.config.symbol}")
                else:
                    symbol_info = mt5.symbol_info(self.config.symbol)
                    if symbol_info is None:
                        self.logger.warning(f"Symbol {self.config.symbol} not found after selection")
                    elif symbol_info.trade_mode == 0:
                        self.logger.warning(f"Symbol {self.config.symbol} is not tradeable")
                    else:
                        self.logger.info(f"Symbol {self.config.symbol} selected and is tradeable.")
                        self.get_symbol_properties()
            else:
                self.logger.info("No symbol selected – user must choose one from the interface.")

            account_info = mt5.account_info()
            if account_info:
                self.account_balance = account_info.balance
                self.account_equity = account_info.equity
                self.peak_equity = self.account_equity
                self.logger.info(f"Account Balance: ${self.account_balance:.2f} | Equity: ${self.account_equity:.2f}")
            else:
                self.account_balance = 10000.0
                self.account_equity = 10000.0
                self.peak_equity = 10000.0
                self.logger.info("Using simulated account data - MT5 not connected")

            self._preload_indicators()

            if self.config.enable_trailing_stop_loss:
                self.logger.info("Initializing Advanced Trailing Stop-Loss System...")
                self.trailing_stop.enable_trailing(True)
                self.logger.info("Syncing existing positions with trailing stop manager...")
                self.sync_existing_positions_with_trailing()
                self.force_trailing_stats_update()

            self.reversal_mode_enabled = self.config.enable_reversal_trading

            self.running = True
            mode = "NORMAL" if not self.config.reversal_mode else "REVERSED"
            self.logger.info(f"System started successfully in {mode} mode")

            if self.callback_queue:
                try:
                    self.callback_queue.put_nowait(('system_ready', {
                        'mode': mode,
                        'connected': self.mt5_connected
                    }))
                except:
                    pass

            return True
        except Exception as e:
            self.logger.error(f"Initialization failed: {str(e)}", exc_info=True)
            return False

    def scan_available_symbols(self) -> List[str]:
        try:
            symbols = mt5.symbols_get()
            if not symbols:
                self.logger.warning("No symbols returned from MT5")
                return []
            tradeable = []
            for s in symbols:
                if s.trade_mode != 0:
                    tradeable.append(s.name)
            tradeable.sort()
            self.available_symbols = tradeable
            self.logger.info(f"Scanned {len(tradeable)} tradeable symbols")
            return tradeable
        except Exception as e:
            self.logger.error(f"Error scanning symbols: {e}")
            return []

    def search_symbols(self, query: str) -> List[str]:
        try:
            if not query or len(query) < 1:
                return []
            symbols = mt5.symbols_get()
            if not symbols:
                return []
            query_upper = query.upper()
            matches = []
            for s in symbols:
                if s.trade_mode != 0 and query_upper in s.name:
                    matches.append(s.name)
            return matches[:20]
        except Exception as e:
            self.logger.error(f"Error searching symbols: {e}")
            return []

    def _preload_indicators(self, bars: int = 100):
        if self.config.symbol is None:
            return

        rates_5min = mt5.copy_rates_from_pos(self.config.symbol, mt5.TIMEFRAME_M5, 0, bars)
        if rates_5min is not None and len(rates_5min) > 0:
            for bar in rates_5min:
                self.indicator_5min.update(bar[1], bar[2], bar[3], bar[4], bar[5])
                self.last_bar_time_5min = bar[0]

        rates_15min = mt5.copy_rates_from_pos(self.config.symbol, mt5.TIMEFRAME_M15, 0, bars)
        if rates_15min is not None and len(rates_15min) > 0:
            for bar in rates_15min:
                self.indicator_15min.update(bar[1], bar[2], bar[3], bar[4], bar[5])
                self.last_bar_time_15min = bar[0]

        rates_1min = mt5.copy_rates_from_pos(self.config.symbol, mt5.TIMEFRAME_M1, 0, bars)
        if rates_1min is not None and len(rates_1min) > 0:
            for bar in rates_1min:
                self.indicator_sts_1min.update(bar[1], bar[2], bar[3], bar[4], bar[5])
                self.last_bar_time_1min = bar[0]

        if rates_5min is not None and len(rates_5min) > 0:
            for bar in rates_5min:
                self.indicator_sts_5min.update(bar[1], bar[2], bar[3], bar[4], bar[5])

    def get_point_value(self) -> float:
        if self.symbol_properties:
            tick_value = self.symbol_properties.get('trade_tick_value', 0.01)
            tick_size = self.symbol_properties.get('trade_tick_size', 0.00001)
            point_size = 10 * tick_size
            return tick_value * (point_size / tick_size)
        return 0.01

    def get_point_size(self) -> float:
        if self.symbol_info:
            return self.symbol_info.point
        return 0.0001

    def set_sts_mode(self, enabled: bool):
        self.use_sts = enabled
        self.config.use_sts_signal = enabled
        self.logger.info(f"STS mode {'ENABLED' if enabled else 'DISABLED'}")

    def reset_session_counter(self):
        with self.trading_lock:
            self.session_trades = 0
            self.session_market_trades = 0
            self.session_pending_orders = 0
            self.config.trades_taken_current_session = 0
            self.aggressive_trades_this_minute = 0
            self.minute_start_time = datetime.now()
            self.signal_trades = 0
            self.config.trades_taken_current_signal = 0
            self.pending_trades = []
            self._last_reset_date = datetime.now().date()
            self.logger.info("Session counters reset - ready for {} market trades and {} pending orders".format(
                self.config.max_trades_per_session, self.config.max_trades_per_session))

    def reset_signal_counter(self):
        with self.trading_lock:
            self.signal_trades = 0
            self.config.trades_taken_current_signal = 0
            self.aggressive_mode = False
            self.logger.info("Signal trade counter reset")
            return True, "Signal trade counter has been reset"

    def update_signal_tracking(self, new_signal: TradeSignal):
        if new_signal != self.current_signal:
            self.previous_signal = self.current_signal
            self.current_signal = new_signal
            self.signal_start_time = datetime.now()
            self.signal_trades = 0
            self.config.trades_taken_current_signal = 0
            if new_signal != TradeSignal.NEUTRAL:
                self.logger.info(f"Signal changed from {self.previous_signal.value} to {new_signal.value}")

    def close_positions_opposite_to_signal(self, new_signal: TradeSignal):
        if new_signal == TradeSignal.NEUTRAL or self.config.symbol is None:
            return
        opposite_type = "SELL" if new_signal == TradeSignal.BUY else "BUY"
        positions_to_close = []
        with self.trading_lock:
            positions = mt5.positions_get()
            if positions:
                for pos in positions:
                    pos_type = "BUY" if pos.type == 0 else "SELL"
                    if pos_type == opposite_type:
                        positions_to_close.append(pos.ticket)
            for ticket in positions_to_close:
                self.close_position(ticket)
        if positions_to_close:
            self.logger.info(f"Closed {len(positions_to_close)} positions opposite to new signal {new_signal.value}")

    def can_trade_auto(self) -> bool:
        if not self.config.auto_trading:
            return False
        if self.manual_pause:
            return False
        if self.session_market_trades >= self.config.max_trades_per_session:
            self.logger.warning("Maximum 5 market trades per session reached")
            self.aggressive_mode = False
            return False
        if self.session_pending_orders >= self.config.max_trades_per_session:
            self.logger.warning("Maximum 5 pending orders per session reached")
            self.aggressive_mode = False
            return False
        if self.session_trades >= self.config.max_trades_per_session:
            self.logger.warning("Maximum 5 trades per session reached")
            self.aggressive_mode = False
            return False
        orders = mt5.orders_get(symbol=self.config.symbol) if self.config.symbol else []
        if orders and len(orders) >= 5:
            self.logger.warning("Maximum 5 orders per session reached")
            return False
        if self.config.symbol is None:
            self.logger.warning("No symbol selected – cannot auto trade")
            return False
        return True

    def should_trade_aggressively(self) -> bool:
        current_time = datetime.now()
        if (current_time - self.minute_start_time).seconds >= 60:
            self.minute_start_time = current_time
            self.aggressive_trades_this_minute = 0
        return (self.signal_trades < self.config.min_trades_per_signal and
                self.session_trades < self.config.max_trades_per_session and
                self.aggressive_trades_this_minute < self.config.aggressive_trades_per_minute)

    def check_trading_conditions(self) -> bool:
        if not self.can_trade_auto():
            return False
        current_date = datetime.now().date()
        if current_date > self._last_reset_date:
            self.logger.info("New day detected - resetting session counters")
            self.reset_session_counter()
            self._last_reset_date = current_date
        current_hour = datetime.utcnow().hour
        if not (self.config.trading_start_hour <= current_hour < self.config.trading_end_hour):
            return False
        trade_mode = self.symbol_properties.get('trade_mode', 0)
        if trade_mode == 0:
            return False
        positions = mt5.positions_get(symbol=self.config.symbol)
        if positions and len(positions) >= self.config.max_concurrent_positions:
            return False
        return True

    def get_symbol_properties(self):
        if self.config.symbol is None:
            self.logger.warning("Cannot get symbol properties: No symbol selected")
            return False
        try:
            symbol_info = mt5.symbol_info(self.config.symbol)
            if symbol_info:
                self.symbol_info = symbol_info
                self.symbol_properties = {
                    'volume_min': symbol_info.volume_min,
                    'volume_max': symbol_info.volume_max,
                    'volume_step': symbol_info.volume_step,
                    'trade_contract_size': symbol_info.trade_contract_size,
                    'trade_tick_size': symbol_info.trade_tick_size,
                    'trade_tick_value': symbol_info.trade_tick_value,
                    'trade_mode': symbol_info.trade_mode,
                    'trade_exemode': symbol_info.trade_exemode,
                    'digits': symbol_info.digits
                }
                self.logger.info(f"Symbol Properties for {self.config.symbol}:")
                self.logger.info(f"  Min Volume: {self.symbol_properties['volume_min']}")
                self.logger.info(f"  Max Volume: {self.symbol_properties['volume_max']}")
                self.logger.info(f"  Volume Step: {self.symbol_properties['volume_step']}")
                self.logger.info(f"  Digits: {self.symbol_properties['digits']}")
                return True
            else:
                self.logger.error(f"Failed to get symbol info for {self.config.symbol}")
                return False
        except Exception as e:
            self.logger.error(f"Error getting symbol properties: {e}")
            return False

    def validate_volume(self, volume: float) -> Tuple[bool, float, str]:
        if not self.symbol_properties:
            return False, volume, "Symbol properties not loaded"
        try:
            min_volume = self.symbol_properties.get('volume_min', 0.01)
            max_volume = self.symbol_properties.get('volume_max', 100.0)
            volume_step = self.symbol_properties.get('volume_step', 0.01)
            if volume < min_volume:
                return False, volume, f"Volume {volume} is less than minimum {min_volume}"
            if volume > max_volume:
                return False, volume, f"Volume {volume} exceeds maximum {max_volume}"
            if volume_step > 0:
                steps = round(volume / volume_step)
                adjusted_volume = steps * volume_step
                adjusted_volume = max(min_volume, min(max_volume, adjusted_volume))
                if abs(adjusted_volume - volume) > 0.0001:
                    volume = adjusted_volume
            if volume_step >= 0.1:
                volume = round(volume, 1)
            elif volume_step >= 0.01:
                volume = round(volume, 2)
            else:
                volume = round(volume, 3)
            if volume < min_volume:
                volume = min_volume
            elif volume > max_volume:
                volume = max_volume
            return True, volume, "Volume validated successfully"
        except Exception as e:
            return False, volume, f"Error validating volume: {str(e)}"

    def change_symbol(self, new_symbol: str) -> Tuple[bool, str]:
        with self.trading_lock:
            symbol_info = mt5.symbol_info(new_symbol)
            if symbol_info is None:
                return False, f"Symbol {new_symbol} not found in MetaTrader 5."
            if not mt5.symbol_select(new_symbol, True):
                return False, f"Could not select symbol {new_symbol}. It may not be enabled in Market Watch."
            if symbol_info.trade_mode == 0:
                return False, f"Symbol {new_symbol} is not tradeable (trade_mode=0)."
            old_symbol = self.config.symbol
            self.config.symbol = new_symbol
            if not self.get_symbol_properties():
                self.config.symbol = old_symbol
                return False, f"Could not load properties for {new_symbol}."
            self.logger.info(f"Symbol changed to {new_symbol} (previous: {old_symbol})")
            self._preload_indicators()
            try:
                self.callback_queue.put_nowait(('symbol_changed', {
                    'symbol': new_symbol,
                    'old_symbol': old_symbol
                }))
            except:
                pass
            return True, f"Symbol changed to {new_symbol}"

    def reset_session_counters(self):
        with self.trading_lock:
            self.session_market_trades = 0
            self.session_pending_orders = 0
            self.session_trades = 0
            self.aggressive_trades_this_minute = 0
            self.minute_start_time = datetime.now()
            self.config.trades_taken_current_session = 0
            self.logger.info("Session counters reset - ready for {} market trades and {} pending orders".format(
                self.config.max_trades_per_session, self.config.max_trades_per_session))

    def sync_existing_positions_with_trailing(self):
        try:
            if not self.config.enable_trailing_stop_loss:
                self.logger.info("Trailing stop disabled - skipping position sync")
                return
            positions = mt5.positions_get()
            if not positions:
                self.logger.info("No existing positions to sync with trailing stop")
                return
            added_count = 0
            skipped_count = 0
            for mt5_position in positions:
                existing = self.trailing_stop.get_position(mt5_position.ticket)
                if existing:
                    skipped_count += 1
                    continue
                order_type = OrderType.LONG if mt5_position.type == 0 else OrderType.SHORT
                success = self.trailing_stop.add_position(
                    ticket=mt5_position.ticket,
                    symbol=mt5_position.symbol,
                    order_type=order_type,
                    volume=mt5_position.volume,
                    entry_price=mt5_position.price_open,
                    stop_loss=mt5_position.sl,
                    take_profit=mt5_position.tp,
                    comment=f"Existing position synced on startup"
                )
                if success:
                    added_count += 1
                    self.logger.info(f"✅ Added position {mt5_position.ticket} to trailing stop manager")
            if added_count > 0:
                self.logger.info(f"✅ Synced {added_count} existing positions with trailing stop manager (skipped {skipped_count} already managed)")
                if self.callback_queue:
                    try:
                        self.callback_queue.put_nowait(('trailing_sync_complete', {
                            'count': added_count,
                            'skipped': skipped_count,
                            'total': len(positions)
                        }))
                    except:
                        pass
            else:
                self.logger.info(f"No new positions to sync - {skipped_count} already managed")
            self.trailing_sync_complete = True
        except Exception as e:
            self.logger.error(f"Error syncing positions: {e}")
            import traceback
            traceback.print_exc()

    def force_trailing_stats_update(self):
        try:
            if not self.trailing_stop:
                return
            stats = self.trailing_stop.get_performance_summary()
            if self.callback_queue:
                try:
                    self.callback_queue.put_nowait(('trailing_stats_update', {
                        'stats': stats,
                        'timestamp': datetime.now().isoformat()
                    }))
                except queue.Full:
                    pass
                except Exception as e:
                    self.logger.error(f"Error sending trailing stats update: {e}")
        except Exception as e:
            self.logger.error(f"Error forcing trailing stats update: {e}")

    def check_pending_orders(self):
        if not hasattr(self, 'pending_trades') or not self.pending_trades:
            return
        active_pending = []
        for trade in self.pending_trades:
            try:
                order = mt5.orders_get(ticket=trade.ticket)
                if order:
                    active_pending.append(trade)
                else:
                    self.logger.info(f"Pending order {trade.ticket} filled/removed from tracking")
                    self.session_pending_orders = max(0, self.session_pending_orders - 1)
            except Exception as e:
                self.logger.error(f"Error checking pending order {trade.ticket}: {e}")
                active_pending.append(trade)
        self.pending_trades = active_pending

    def manage_pending_orders(self):
        """Cancel pending orders that are too old."""
        self.logger.info(f"manage_pending_orders called, pending_trades count: {len(self.pending_trades)}")
        if not self.pending_trades:
            return

        now = datetime.now()
        orders_to_cancel = []

        for trade in self.pending_trades[:]:
            age = (now - trade.entry_time).total_seconds()
            self.logger.info(f"Order {trade.ticket} age: {age:.1f}s, timeout: {self.config.pending_order_timeout_seconds}s")

            if age > self.config.pending_order_timeout_seconds:
                self.logger.info(f"Order {trade.ticket} is stale, cancelling...")

                # First, verify the order still exists in MT5
                order = mt5.orders_get(ticket=trade.ticket)
                if not order:
                    self.logger.info(f"Order {trade.ticket} already removed from MT5 (filled or cancelled externally)")
                    orders_to_cancel.append(trade)
                    self.session_pending_orders = max(0, self.session_pending_orders - 1)
                    if self.callback_queue:
                        try:
                            self.callback_queue.put_nowait(('pending_order_cancelled', {
                                'ticket': trade.ticket,
                                'symbol': trade.symbol,
                                'age': age,
                                'reason': 'already_removed'
                            }))
                        except:
                            pass
                    continue

                # Cancel the order
                try:
                    request = {
                        "action": mt5.TRADE_ACTION_REMOVE,
                        "order": trade.ticket,
                        "comment": "Stale order auto-cancelled"
                    }
                    result = mt5.order_send(request)

                    # ----- ADD THIS LINE RIGHT HERE -----
                    self.logger.info(f"Cancel result: retcode={result.retcode}, comment={result.comment}")

                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        self.logger.info(f"✅ Cancelled stale pending order {trade.ticket} (age {age:.0f}s)")
                        orders_to_cancel.append(trade)
                        self.session_pending_orders = max(0, self.session_pending_orders - 1)

                        # Send notification to UI
                        if self.callback_queue:
                            try:
                                self.callback_queue.put_nowait(('pending_order_cancelled', {
                                    'ticket': trade.ticket,
                                    'symbol': trade.symbol,
                                    'age': age,
                                    'reason': 'stale'
                                }))
                            except:
                                pass
                    else:
                        error_msg = result.comment if result else "No result"
                        retcode = result.retcode if result else "None"
                        self.logger.error(f"❌ Failed to cancel stale order {trade.ticket}: {error_msg} (retcode {retcode})")

                except Exception as e:
                    self.logger.error(f"❌ Error cancelling stale order {trade.ticket}: {e}")

        # Remove cancelled orders from tracking
        for trade in orders_to_cancel:
            self.pending_trades.remove(trade)

        self.logger.info(f"manage_pending_orders finished, {len(orders_to_cancel)} orders cancelled, {len(self.pending_trades)} remain")
        
    def toggle_reversal_mode(self, enabled: bool):
        self.reversal_mode_enabled = enabled
        self.config.enable_reversal_trading = enabled
        status = "ENABLED" if enabled else "DISABLED"
        self.logger.info(f"Reversal trading mode {status}")
        if self.callback_queue:
            try:
                self.callback_queue.put_nowait(('reversal_mode_toggled', {
                    'enabled': enabled
                }))
            except:
                pass

    def execute_reversal_trades(self, new_signal: TradeSignal, old_signal: TradeSignal) -> Tuple[bool, str]:
        self.reversal_trades_executed = 0
        self.logger.info(f"🔍 EXECUTE_REVERSAL_TRADES CALLED with {old_signal.value} -> {new_signal.value}")
        self.logger.info(f"   Reversal enabled: {self.reversal_mode_enabled}")
        self.logger.info(f"   Min confidence: {self.config.reversal_min_confidence_score}%")

        if not self.reversal_mode_enabled:
            self.logger.warning("   ❌ Reversal trading not enabled")
            return False, "Reversal trading not enabled"
        if new_signal == TradeSignal.NEUTRAL or old_signal == TradeSignal.NEUTRAL:
            self.logger.warning("   ❌ Cannot execute reversal trades from/to NEUTRAL signal")
            return False, "Cannot execute reversal trades from/to NEUTRAL signal"

        current_time = datetime.now()
        if self.last_reversal_time:
            time_since_last = (current_time - self.last_reversal_time).seconds
            if time_since_last < self.config.reversal_cooldown_seconds:
                return False, f"Reversal cooldown active ({self.config.reversal_cooldown_seconds - time_since_last}s remaining)"

        should_execute, reason, confidence_data = self.reversal_trader.should_execute_reversal(new_signal, old_signal)

        if not should_execute:
            self.logger.info(f"🚫 Reversal SKIPPED: {reason}")
            self.alert_system.alert_reversal_skipped(reason, confidence_data['overall_confidence'])
            if self.callback_queue:
                try:
                    self.callback_queue.put_nowait(('reversal_skipped', {
                        'reason': reason,
                        'confidence': confidence_data['overall_confidence'],
                        'passed_checks': confidence_data['passed_checks'],
                        'total_checks': confidence_data['total_checks']
                    }))
                except:
                    pass
            return False, f"Reversal skipped: {reason}"

        self.logger.info(f"✅ Reversal CONFIRMED: {reason}")
        self.logger.info(f"🎯 Executing {self.max_reversal_trades} reversal trades...")
        self.alert_system.alert_reversal_execution(self.max_reversal_trades)

        tick = mt5.symbol_info_tick(self.config.symbol)
        if not tick:
            return False, "Failed to get tick data"

        current_price = tick.ask if new_signal == TradeSignal.BUY else tick.bid

        if self.config.reversal_require_retest:
            self.logger.info(f"⏳ Waiting {self.config.reversal_retest_wait_seconds}s for retest...")
            time.sleep(self.config.reversal_retest_wait_seconds)
            tick = mt5.symbol_info_tick(self.config.symbol)
            if not tick:
                return False, "Failed to get tick data after wait"
            entry_price = tick.ask if new_signal == TradeSignal.BUY else tick.bid
            price_move_pips = abs(entry_price - current_price) / self.get_point_size() / 10
            if price_move_pips > self.config.reversal_max_price_move_pips:
                self.logger.warning(f"Price moved {price_move_pips:.1f} pips during wait - skipping")
                return False, f"Price moved too far ({price_move_pips:.1f} pips)"
        else:
            entry_price = current_price

        atr = self.reversal_trader.calculate_atr()
        point_size = self.get_point_size()
        sl_pips = self.config.stop_loss_pips if self.config.enable_stop_loss else 0
        tp_pips = self.config.take_profit_pips if self.config.enable_take_profit else 0

        if atr > 0 and self.config.reversal_use_dynamic_sl:
            atr_pips = atr / point_size / 10
            dynamic_sl_pips = min(atr_pips * 1.5, self.config.reversal_max_sl_pips)
            dynamic_sl_pips = max(dynamic_sl_pips, self.config.reversal_min_sl_pips)
            sl_pips = dynamic_sl_pips
            self.logger.info(f"Using dynamic SL: {sl_pips:.1f} pips (ATR: {atr_pips:.1f} pips)")

        success_count = 0
        failed_trades = []

        for i in range(self.max_reversal_trades):
            try:
                volume = self.config.reversal_trade_volume
                if new_signal == TradeSignal.BUY:
                    direction = "BUY"
                    order_type = mt5.ORDER_TYPE_BUY
                else:
                    direction = "SELL"
                    order_type = mt5.ORDER_TYPE_SELL

                sl, tp, calc_msg = self.calculate_stop_levels(
                    direction, entry_price, volume,
                    sl_pips, tp_pips
                )

                is_valid, validated_volume, msg = self.validate_volume(volume)
                if not is_valid:
                    failed_trades.append(f"Trade {i+1}: {msg}")
                    continue

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": self.config.symbol,
                    "volume": validated_volume,
                    "type": order_type,
                    "price": entry_price,
                    "sl": sl if sl > 0 else 0.0,
                    "tp": tp if tp > 0 else 0.0,
                    "deviation": self.config.slippage,
                    "magic": self.config.magic_number,
                    "comment": f"REV{confidence_data['passed_checks']}/{confidence_data['total_checks']} {old_signal.value}→{new_signal.value}",
                    "type_time": mt5.ORDER_TIME_GTC,
                }

                result = mt5.order_send(request)

                if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                    success_count += 1
                    if self.config.enable_trailing_stop_loss:
                        self.trailing_stop.add_position(
                            ticket=result.order,
                            symbol=self.config.symbol,
                            order_type=OrderType.LONG if new_signal == TradeSignal.BUY else OrderType.SHORT,
                            volume=validated_volume,
                            entry_price=entry_price,
                            stop_loss=sl,
                            take_profit=tp,
                            comment=f"Reversal {i+1}/5"
                        )
                    self.logger.info(f"✅ Reversal trade {i+1}/{self.max_reversal_trades} executed: {direction} {validated_volume} lots at {entry_price:.2f}")
                    if self.callback_queue:
                        try:
                            self.callback_queue.put_nowait(('reversal_trade_executed', {
                                'trade_number': i+1,
                                'total': self.max_reversal_trades,
                                'ticket': result.order,
                                'direction': direction,
                                'volume': validated_volume,
                                'price': entry_price,
                                'sl_pips': sl_pips,
                                'tp_pips': tp_pips,
                                'confidence': confidence_data['overall_confidence']
                            }))
                        except:
                            pass
                    time.sleep(2)
                else:
                    error_msg = result.comment if result else "Unknown error"
                    failed_trades.append(f"Trade {i+1}: {error_msg}")
                    self.logger.error(f"❌ Reversal trade {i+1} failed: {error_msg}")
                 
                    if self.callback_queue:
                        try:
                            self.callback_queue.put_nowait(('reversal_trade_failed', {
                                'trade_number': i+1,
                                'total': self.max_reversal_trades,
                                'direction': direction,
                                'volume': validated_volume,
                                'price': entry_price,
                                'reason': error_msg,
                                'confidence': confidence_data['overall_confidence'],
                                'timestamp': datetime.now().isoformat()
                            }))
                        except:
                            pass
                   
            except Exception as e:
                error_msg = str(e)
                failed_trades.append(f"Trade {i+1}: {error_msg}")
                self.logger.error(f"❌ Error in reversal trade {i+1}: {e}")

                if self.callback_queue:
                    try:
                        self.callback_queue.put_nowait(('reversal_trade_failed', {
                            'trade_number': i+1,
                            'total': self.max_reversal_trades,
                            'direction': direction,
                            'volume': volume,
                            'price': entry_price,
                            'reason': error_msg,
                            'confidence': confidence_data['overall_confidence'],
                            'timestamp': datetime.now().isoformat()
                        }))
                    except:
                        pass

        self.last_reversal_time = datetime.now()
        self.reversal_trades_executed = success_count

        result_msg = f"Reversal {success_count}/{self.max_reversal_trades} trades (Confidence: {confidence_data['overall_confidence']:.1f}%)"

        if self.callback_queue:
            try:
                self.callback_queue.put_nowait(('reversal_complete', {
                    'success_count': success_count,
                    'total': self.max_reversal_trades,
                    'message': result_msg,
                    'type': 'success' if success_count > 0 else 'error',
                    'confidence': confidence_data['overall_confidence'],
                    'passed_checks': confidence_data['passed_checks'],
                    'total_checks': confidence_data['total_checks']
                }))
            except:
                pass

        return success_count > 0, result_msg

    # ========== Signal Calculation ==========

    def calculate_signal(self) -> TradeSignal:
        news_sentiment = 0.0
        if self.config.use_news_sentiment:
            news_sentiment = self.news_manager.get_sentiment_score()

        old_signal = self.current_signal

        if self.use_sts:
            detail_1min = self.indicator_sts_1min.get_signal_detail(news_sentiment)
            detail_5min = self.indicator_sts_5min.get_signal_detail(news_sentiment)

            def signal_value(sig):
                return 1 if sig == TradeSignal.BUY else (-1 if sig == TradeSignal.SELL else 0)

            val_1 = signal_value(detail_1min.direction)
            val_5 = signal_value(detail_5min.direction)

            weighted_sum = self.config.sts_1min_weight * val_1 + self.config.sts_5min_weight * val_5
            threshold = self.config.sts_alignment_threshold

            if weighted_sum >= threshold:
                signal = TradeSignal.BUY
                self.current_signal_detail = detail_1min
            elif weighted_sum <= -threshold:
                signal = TradeSignal.SELL
                self.current_signal_detail = detail_1min
            else:
                signal = TradeSignal.NEUTRAL
                self.current_signal_detail = SignalDetail(
                    direction=TradeSignal.NEUTRAL,
                    entry_price=None,
                    trade_count=0,
                    aggressive=False,
                    signal_start_bar=-1,
                    trades_taken=0,
                    entry_type='',
                    comment=f'STS weighted sum {weighted_sum:.2f} below threshold'
                )
        else:
            detail_5 = self.indicator_5min.get_signal_detail(news_sentiment)
            detail_15 = self.indicator_15min.get_signal_detail(news_sentiment)

            def signal_value(sig):
                return 1 if sig == TradeSignal.BUY else (-1 if sig == TradeSignal.SELL else 0)

            val_5 = signal_value(detail_5.direction)
            val_15 = signal_value(detail_15.direction)

            weighted_sum = self.config.weight_5min * val_5 + self.config.weight_15min * val_15
            threshold = self.config.alignment_threshold

            if weighted_sum >= threshold:
                signal = TradeSignal.BUY
                self.current_signal_detail = detail_5
            elif weighted_sum <= -threshold:
                signal = TradeSignal.SELL
                self.current_signal_detail = detail_5
            else:
                signal = TradeSignal.NEUTRAL
                self.current_signal_detail = SignalDetail(
                    direction=TradeSignal.NEUTRAL,
                    entry_price=None,
                    trade_count=0,
                    aggressive=False,
                    signal_start_bar=-1,
                    trades_taken=0,
                    entry_type='',
                    comment=f'Normal weighted sum {weighted_sum:.2f} below threshold'
                )

            if signal != old_signal:
                if (old_signal in [TradeSignal.BUY, TradeSignal.SELL] and
                    signal in [TradeSignal.BUY, TradeSignal.SELL] and
                    old_signal != signal):
                    self.logger.info(f"🚨 SIGNAL REVERSAL DETECTED: {old_signal.value} → {signal.value}")
                    min_conf = self.config.reversal_min_confidence_score
                    conf_mode = "EXECUTING ALL (0%)" if min_conf <= 0 else f"Min Confidence: {min_conf}%"
                    self.logger.info(f"📊 Reversal Mode: {conf_mode}")
                    if self.reversal_mode_enabled:
                        self.logger.info(f"🎯 Reversal mode ENABLED - executing trades immediately")
                        reversal_thread = threading.Thread(
                            target=self.execute_reversal_trades,
                            args=(signal, old_signal),
                            daemon=True
                        )
                        reversal_thread.start()
                    else:
                        self.logger.info(f"⏸️ Reversal mode DISABLED - not executing trades")

            if signal == TradeSignal.BUY:
                self.alert_system.alert_buy_signal(
                    price=self.current_signal_detail.entry_price if self.current_signal_detail else None,
                    reason=self.current_signal_detail.comment if self.current_signal_detail else ""
                )
            elif signal == TradeSignal.SELL:
                self.alert_system.alert_sell_signal(
                    price=self.current_signal_detail.entry_price if self.current_signal_detail else None,
                    reason=self.current_signal_detail.comment if self.current_signal_detail else ""
                )

            try:
                self.callback_queue.put_nowait(('signal_changed', {
                    'old': old_signal.value if old_signal else 'NEUTRAL',
                    'new': signal.value,
                    'entry_price': self.current_signal_detail.entry_price if self.current_signal_detail else None,
                    'entry_type': self.current_signal_detail.entry_type if self.current_signal_detail else '',
                    'comment': self.current_signal_detail.comment if self.current_signal_detail else '',
                    'is_reversal': (old_signal in [TradeSignal.BUY, TradeSignal.SELL] and
                                   signal in [TradeSignal.BUY, TradeSignal.SELL] and
                                   old_signal != signal)
                }))
            except:
                pass

        self._check_extreme_conditions()
        self.update_signal_tracking(signal)
        return signal

    def _check_extreme_conditions(self):
        try:
            if hasattr(self, 'indicator_5min') and len(self.indicator_5min.closes) > 14:
                closes = self.indicator_5min.closes[-14:]
                gains = []
                losses = []
                for i in range(1, len(closes)):
                    change = closes[i] - closes[i-1]
                    if change > 0:
                        gains.append(change)
                    else:
                        losses.append(abs(change))
                avg_gain = sum(gains) / len(gains) if gains else 0
                avg_loss = sum(losses) / len(losses) if losses else 1
                rs = avg_gain / avg_loss if avg_loss != 0 else 0
                rsi = 100 - (100 / (1 + rs))
                if rsi > 70:
                    if not self.last_overbought_alert:
                        self.alert_system.alert_overbought("RSI", rsi, 70)
                        self.last_overbought_alert = True
                        self.last_oversold_alert = False
                elif rsi < 30:
                    if not self.last_oversold_alert:
                        self.alert_system.alert_oversold("RSI", rsi, 30)
                        self.last_oversold_alert = True
                        self.last_overbought_alert = False
                else:
                    self.last_overbought_alert = False
                    self.last_oversold_alert = False
                self.last_rsi_value = rsi
        except Exception as e:
            self.logger.debug(f"Error checking extreme conditions: {e}")

    # ========== Trade Execution Helpers ==========

    def _price_to_pips(self, direction: str, entry: float, price: float) -> int:
        if price <= 0:
            return 0
        point = self.get_point_size()
        pips_per_point = 10
        if direction.upper() == "BUY":
            diff = abs(price - entry)
        else:
            diff = abs(entry - price)
        points = diff / point
        pips = int(points / pips_per_point)
        return pips

    def calculate_stop_levels(self, direction: str, entry_price: float, volume: float,
                              sl_pips: float = None, tp_pips: float = None) -> Tuple[float, float, str]:
        try:
            point_value = self.get_point_value()
            symbol_info = mt5.symbol_info(self.config.symbol)
            if not symbol_info:
                return 0.0, 0.0, "❌ Cannot get symbol info"
            stop_level_points = symbol_info.trade_stops_level
            point = symbol_info.point
            min_stop_distance_price = stop_level_points * point
            pips_to_price = 10 * point

            if sl_pips is None or sl_pips <= 0:
                if direction.upper() == "BUY":
                    return 0.0, 0.0, "✅ No stop loss (pips = 0)"
                else:
                    return 0.0, 0.0, "✅ No stop loss (pips = 0)"

            if tp_pips is None or tp_pips <= 0:
                sl_distance_price = sl_pips * pips_to_price
                if direction.upper() == "BUY":
                    sl_price = entry_price - sl_distance_price
                    if sl_distance_price < min_stop_distance_price:
                        sl_distance_price = min_stop_distance_price
                        sl_price = entry_price - sl_distance_price
                        self.logger.warning(f"SL distance increased to minimum {min_stop_distance_price:.5f} price units")
                    return sl_price, 0.0, f"✅ Stop loss only: {sl_pips} pips"
                else:
                    sl_distance_price = sl_pips * pips_to_price
                    sl_price = entry_price + sl_distance_price
                    if sl_distance_price < min_stop_distance_price:
                        sl_distance_price = min_stop_distance_price
                        sl_price = entry_price + sl_distance_price
                        self.logger.warning(f"SL distance increased to minimum {min_stop_distance_price:.5f} price units")
                    return sl_price, 0.0, f"✅ Stop loss only: {sl_pips} pips"

            sl_distance_price = sl_pips * pips_to_price
            tp_distance_price = tp_pips * pips_to_price

            if direction.upper() == "BUY":
                sl_price = entry_price - sl_distance_price
                tp_price = entry_price + tp_distance_price
                if sl_distance_price < min_stop_distance_price:
                    sl_distance_price = min_stop_distance_price
                    sl_price = entry_price - sl_distance_price
                    self.logger.warning(f"SL distance increased to minimum {min_stop_distance_price:.5f} price units")
                if tp_distance_price < min_stop_distance_price:
                    tp_distance_price = min_stop_distance_price
                    tp_price = entry_price + tp_distance_price
                    self.logger.warning(f"TP distance increased to minimum {min_stop_distance_price:.5f} price units")
            else:
                sl_price = entry_price + sl_distance_price
                tp_price = entry_price - tp_distance_price
                if sl_distance_price < min_stop_distance_price:
                    sl_distance_price = min_stop_distance_price
                    sl_price = entry_price + sl_distance_price
                    self.logger.warning(f"SL distance increased to minimum {min_stop_distance_price:.5f} price units")
                if tp_distance_price < min_stop_distance_price:
                    tp_distance_price = min_stop_distance_price
                    tp_price = entry_price - tp_distance_price
                    self.logger.warning(f"TP distance increased to minimum {min_stop_distance_price:.5f} price units")

            digits = symbol_info.digits
            sl_price = round(sl_price, digits) if sl_price > 0 else 0.0
            tp_price = round(tp_price, digits) if tp_price > 0 else 0.0

            message = (f"Stop levels calculated in PIPS:\n"
                       f"• Entry: {entry_price:.{digits}f}\n"
                       f"• SL: {sl_price:.{digits}f} ({sl_pips} pips)\n"
                       f"• TP: {tp_price:.{digits}f} ({tp_pips} pips)\n"
                       f"• Min distance: {stop_level_points} points")
            return sl_price, tp_price, message
        except Exception as e:
            self.logger.error(f"Error calculating stop levels: {e}")
            return 0.0, 0.0, f"❌ Error calculating stops: {str(e)}"

    def validate_stop_levels(self, direction: str, entry_price: float,
                             sl_price: float, tp_price: float) -> Tuple[bool, str]:
        try:
            symbol_info = mt5.symbol_info(self.config.symbol)
            if not symbol_info:
                return False, "❌ Cannot get symbol info"
            stop_level_points = symbol_info.trade_stops_level
            point = symbol_info.point
            min_distance = stop_level_points * point
            if sl_price <= 0 or tp_price <= 0:
                return True, "✅ No stops to validate"
            if direction.upper() == "BUY":
                sl_distance = entry_price - sl_price
                tp_distance = tp_price - entry_price
                if sl_distance < min_distance:
                    return False, (f"❌ Stop loss too close: {sl_distance:.5f} < {min_distance:.5f} "
                                   f"({stop_level_points} points minimum)")
                if tp_distance < min_distance:
                    return False, (f"❌ Take profit too close: {tp_distance:.5f} < {min_distance:.5f} "
                                   f"({stop_level_points} points minimum)")
            else:
                sl_distance = sl_price - entry_price
                tp_distance = entry_price - tp_price
                if sl_distance < min_distance:
                    return False, (f"❌ Stop loss too close: {sl_distance:.5f} < {min_distance:.5f} "
                                   f"({stop_level_points} points minimum)")
                if tp_distance < min_distance:
                    return False, (f"❌ Take profit too close: {tp_distance:.5f} < {min_distance:.5f} "
                                   f"({stop_level_points} points minimum)")
            return True, "✅ Stop levels valid"
        except Exception as e:
            return False, f"❌ Validation error: {str(e)}"

    def execute_trade(self, signal: TradeSignal, is_manual: bool = False,
                      manual_volume: float = None,
                      manual_sl_pips: float = None,
                      manual_tp_pips: float = None,
                      manual_sl: float = None, manual_tp: float = None) -> Tuple[bool, str]:
        with self.trading_lock:
            try:
                if self.config.symbol is None:
                    return False, "❌ No symbol selected"

                tick = mt5.symbol_info_tick(self.config.symbol)
                if not tick:
                    return False, "❌ Failed to get tick data"

                current_market_positions = mt5.positions_get(symbol=self.config.symbol)
                current_pending_orders = mt5.orders_get(symbol=self.config.symbol)
                market_count = len(current_market_positions) if current_market_positions else 0
                pending_count = len(current_pending_orders) if current_pending_orders else 0

                if not hasattr(self, 'session_market_trades'):
                    self.session_market_trades = 0
                if not hasattr(self, 'session_pending_orders'):
                    self.session_pending_orders = 0

                if is_manual:
                    order_type_to_use = 'market'
                else:
                    if (hasattr(self, 'current_signal_detail') and self.current_signal_detail and
                        self.current_signal_detail.entry_type == 'limit' and
                        self.current_signal_detail.limit_price and
                        self.session_pending_orders < 5 and
                        pending_count < 5):
                        order_type_to_use = 'pending'
                    else:
                        order_type_to_use = 'market'

                max_trades = self.config.max_trades_per_session
                if not is_manual:
                    if order_type_to_use == 'market':
                        if market_count >= max_trades:
                            return False, f"❌ Maximum {max_trades} market positions reached ({market_count}/{max_trades})"
                        if self.session_market_trades >= max_trades:
                            return False, f"❌ Maximum {max_trades} market trades per session reached ({self.session_market_trades}/{max_trades})"
                    else:
                        if pending_count >= max_trades:
                            return False, f"❌ Maximum {max_trades} pending orders reached ({pending_count}/{max_trades})"
                        if self.session_pending_orders >= max_trades:
                            return False, f"❌ Maximum {max_trades} pending orders per session reached ({self.session_pending_orders}/{max_trades})"

                if is_manual:
                    if signal == TradeSignal.BUY:
                        direction = "BUY"
                        order_type = mt5.ORDER_TYPE_BUY
                        entry_price = tick.ask
                    else:
                        direction = "SELL"
                        order_type = mt5.ORDER_TYPE_SELL
                        entry_price = tick.bid
                    entry_type = 'market'
                else:
                    if order_type_to_use == 'pending' and hasattr(self, 'current_signal_detail'):
                        direction = "BUY" if signal == TradeSignal.BUY else "SELL"
                        if signal == TradeSignal.BUY:
                            order_type = mt5.ORDER_TYPE_BUY_LIMIT
                            entry_price = self.current_signal_detail.limit_price
                            self.logger.info(f"Creating BUY LIMIT order at {entry_price:.5f} (current: {tick.ask:.5f})")
                        else:
                            order_type = mt5.ORDER_TYPE_SELL_LIMIT
                            entry_price = self.current_signal_detail.limit_price
                            self.logger.info(f"Creating SELL LIMIT order at {entry_price:.5f} (current: {tick.bid:.5f})")
                        entry_type = 'limit'
                    else:
                        direction = "BUY" if signal == TradeSignal.BUY else "SELL"
                        if signal == TradeSignal.BUY:
                            order_type = mt5.ORDER_TYPE_BUY
                            entry_price = tick.ask
                        else:
                            order_type = mt5.ORDER_TYPE_SELL
                            entry_price = tick.bid
                        entry_type = 'market'
                        self.logger.info(f"Creating MARKET {direction} order at {entry_price:.5f}")

                if manual_volume is not None:
                    volume = manual_volume
                else:
                    volume = self.calculate_position_size()

                is_valid, validated_volume, msg = self.validate_volume(volume)
                if not is_valid:
                    return False, msg
                volume = validated_volume

                if is_manual:
                    if manual_sl is not None or manual_tp is not None:
                        sl = manual_sl or 0.0
                        tp = manual_tp or 0.0
                        if sl > 0 and tp > 0:
                            is_valid, val_msg = self.validate_stop_levels(direction, entry_price, sl, tp)
                            if not is_valid:
                                return False, val_msg
                    else:
                        sl_pips = manual_sl_pips if manual_sl_pips is not None else (self.config.stop_loss_pips if self.config.enable_stop_loss else 0)
                        tp_pips = manual_tp_pips if manual_tp_pips is not None else (self.config.take_profit_pips if self.config.enable_take_profit else 0)
                        sl, tp, calc_msg = self.calculate_stop_levels(direction, entry_price, volume, sl_pips, tp_pips)
                        self.logger.info(f"Stop calculation: {calc_msg}")
                        if sl > 0 and tp > 0:
                            is_valid, val_msg = self.validate_stop_levels(direction, entry_price, sl, tp)
                            if not is_valid:
                                return False, val_msg
                else:
                    sl_pips = self.config.stop_loss_pips if self.config.enable_stop_loss else 0
                    tp_pips = self.config.take_profit_pips if self.config.enable_take_profit else 0
                    sl, tp, calc_msg = self.calculate_stop_levels(direction, entry_price, volume, sl_pips, tp_pips)
                    self.logger.info(f"Stop calculation: {calc_msg}")
                    if (self.config.enable_stop_loss or self.config.enable_take_profit) and (sl > 0 or tp > 0):
                        is_valid, val_msg = self.validate_stop_levels(direction, entry_price, sl, tp)
                        if not is_valid:
                            return False, val_msg

                if entry_type == 'market':
                    request = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": self.config.symbol,
                        "volume": volume,
                        "type": order_type,
                        "price": entry_price,
                        "sl": sl if sl > 0 else 0.0,
                        "tp": tp if tp > 0 else 0.0,
                        "deviation": self.config.slippage,
                        "magic": self.config.magic_number,
                        "comment": f"{'Manual' if is_manual else 'Auto'} {signal.value}",
                        "type_time": mt5.ORDER_TIME_GTC,
                    }
                else:
                    request = {
                        "action": mt5.TRADE_ACTION_PENDING,
                        "symbol": self.config.symbol,
                        "volume": volume,
                        "type": order_type,
                        "price": entry_price,
                        "sl": sl if sl > 0 else 0.0,
                        "tp": tp if tp > 0 else 0.0,
                        "deviation": self.config.slippage,
                        "magic": self.config.magic_number,
                        "comment": f"Auto LIMIT {signal.value}",
                        "type_time": mt5.ORDER_TIME_GTC,
                    }

                sl_pips_display = "None" if sl == 0 else f"{self._price_to_pips(direction, entry_price, sl)} pips"
                tp_pips_display = "None" if tp == 0 else f"{self._price_to_pips(direction, entry_price, tp)} pips"

                self.logger.info(f"Placing {entry_type.upper()} order: {direction} {volume} lots at {entry_price:.2f}")
                self.logger.info(f"SL: {sl_pips_display} | TP: {tp_pips_display}")

                result = mt5.order_send(request)

                if result is None:
                    last_error = mt5.last_error()
                    error_msg = f"❌ Trade failed: mt5.order_send returned None. Last error: {last_error}"
                    self.logger.error(error_msg)
                    return False, error_msg

                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    if not is_manual:
                        if entry_type == 'market':
                            self.session_market_trades += 1
                            self.logger.info(f"Market trade count: {self.session_market_trades}/5")
                        else:
                            self.session_pending_orders += 1
                            self.logger.info(f"Pending order count: {self.session_pending_orders}/5")

                    trade = Trade(
                        ticket=result.order,
                        symbol=self.config.symbol,
                        type=direction,
                        volume=volume,
                        entry_price=entry_price,
                        sl=sl,
                        tp=tp,
                        entry_time=datetime.now(),
                        comment=f"{'Manual' if is_manual else 'Auto'} {signal.value} ({entry_type})"
                    )

                    if entry_type == 'market':
                        self.open_positions.append(trade)
                    else:
                        if not hasattr(self, 'pending_trades'):
                            self.pending_trades = []
                        self.pending_trades.append(trade)
                    self.logger.info(f"manage_pending_orders called, pending_trades count: {len(self.pending_trades)}")

                    self.alert_system.alert_trade_execution(direction, volume, entry_price)

                    if entry_type == 'market' and self.config.enable_trailing_stop_loss:
                        success = self.trailing_stop.add_position(
                            ticket=result.order,
                            symbol=self.config.symbol,
                            order_type=OrderType.LONG if signal == TradeSignal.BUY else OrderType.SHORT,
                            volume=volume,
                            entry_price=entry_price,
                            stop_loss=sl,
                            take_profit=tp,
                            comment=f"{'Manual' if is_manual else 'Auto'} {signal.value}"
                        )
                        if success:
                            self.logger.info(f"✅ Position {result.order} added to trailing stop management")

                    if not is_manual and entry_type == 'market':
                        if self.use_sts:
                            self.indicator_sts_1min.confirm_trade_placed()
                        else:
                            self.indicator_5min.confirm_trade_placed()
                        self.signal_trades += 1
                        self.session_trades += 1
                        self.aggressive_trades_this_minute += 1
                        self.config.trades_taken_current_signal = self.signal_trades
                        self.config.trades_taken_current_session = self.session_trades
                        self.logger.info(f"Signal trades: {self.signal_trades}/{self.config.min_trades_per_signal}")

                    digits = self.symbol_properties.get('digits', 2)
                    sl_display = f"{sl:.{digits}f}" if sl > 0 else "None"
                    tp_display = f"{tp:.{digits}f}" if tp > 0 else "None"
                    sl_pips_display = f"{self._price_to_pips(direction, entry_price, sl)} pips" if sl > 0 else "None"
                    tp_pips_display = f"{self._price_to_pips(direction, entry_price, tp)} pips" if tp > 0 else "None"

                    msg = (f"✅ {entry_type.upper()} {direction} {volume} lots at {entry_price:.{digits}f}\n"
                           f"• SL: {sl_display} ({sl_pips_display})\n"
                           f"• TP: {tp_display} ({tp_pips_display})")

                    self.logger.info(f"Order placed: {msg}")
                    self.last_trade_time = datetime.now()

                    try:
                        self.callback_queue.put_nowait(('trade_executed', {
                            'ticket': result.order,
                            'direction': direction,
                            'volume': volume,
                            'price': entry_price,
                            'type': entry_type,
                            'sl_pips': self._price_to_pips(direction, entry_price, sl) if sl > 0 else 0,
                            'tp_pips': self._price_to_pips(direction, entry_price, tp) if tp > 0 else 0,
                            'sl_price': sl,
                            'tp_price': tp
                        }))
                    except:
                        pass

                    return True, msg
                else:
                    error_msg = f"❌ Order failed: {result.comment} (retcode: {result.retcode})"
                    if result.retcode == 10016:
                        error_msg = ("❌ INVALID STOPS ERROR (10016)\n"
                                     "Your stop loss or take profit is too close to current price.\n"
                                     "Please increase the distance or check symbol properties.")
                    elif result.retcode == 10014:
                        error_msg = f"❌ INVALID VOLUME ERROR (10014): Volume {volume} is invalid for this symbol."
                    elif result.retcode == 10013:
                        error_msg = "❌ INVALID PRICE ERROR (10013): The order price is invalid."
                    elif result.retcode == 10015:
                        error_msg = "❌ INVALID TICKET ERROR (10015)"
                    elif result.retcode == 10021:
                        error_msg = "❌ MARKET CLOSED ERROR (10021): Cannot trade - market is closed."

                    self.logger.error(error_msg)
                    return False, error_msg
            except Exception as e:
                error_msg = f"❌ Order execution error: {str(e)}"
                self.logger.error(error_msg, exc_info=True)
                return False, error_msg

    def execute_manual_trade(self, direction: str, volume: float,
                             stop_loss_pips: float = None,
                             take_profit_pips: float = None) -> Tuple[bool, str]:
        try:
            if direction.upper() not in ["BUY", "SELL"]:
                return False, "❌ Invalid direction. Use 'BUY' or 'SELL'"
            if volume <= 0:
                return False, "❌ Volume must be greater than 0"
            signal = TradeSignal.BUY if direction.upper() == "BUY" else TradeSignal.SELL
            success, message = self.execute_trade(
                signal=signal,
                is_manual=True,
                manual_volume=volume,
                manual_sl_pips=stop_loss_pips,
                manual_tp_pips=take_profit_pips
            )
            return success, message
        except Exception as e:
            return False, f"❌ Error in manual trade: {str(e)}"

    def calculate_position_size(self) -> float:
        try:
            if self.config.position_sizing_method == "fixed":
                volume = self.config.fixed_lot_size
            elif self.config.position_sizing_method == "percentage":
                risk_amount = self.account_balance * self.config.risk_per_trade
                tick_value = self.symbol_properties.get('trade_tick_value', 0.01)
                stop_loss_points = self.config.stop_loss_pips * 10
                if stop_loss_points > 0 and tick_value > 0:
                    volume = risk_amount / (stop_loss_points * tick_value)
                else:
                    volume = self.config.fixed_lot_size
            else:
                volume = self.config.fixed_lot_size
            volume = max(self.config.min_position_size, min(volume, self.config.max_position_size))
            is_valid, validated_volume, message = self.validate_volume(volume)
            if not is_valid:
                self.logger.warning(f"Volume validation failed: {message}. Using minimum volume.")
                validated_volume = self.config.min_position_size
            return validated_volume
        except Exception as e:
            self.logger.error(f"Error calculating position size: {e}")
            return self.config.min_position_size

    def close_position(self, ticket: int) -> Tuple[bool, str]:
        with self.trading_lock:
            try:
                positions = mt5.positions_get(ticket=ticket)
                if not positions:
                    self.logger.error(f"Close position {ticket} failed: position not found")
                    return False, f"Position {ticket} not found"
                position = positions[0]
                tick = mt5.symbol_info_tick(position.symbol)
                if not tick:
                    self.logger.error(f"Close position {ticket} failed: cannot get tick for {position.symbol}")
                    return False, "Failed to get tick data"
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": position.symbol,
                    "volume": position.volume,
                    "type": mt5.ORDER_TYPE_BUY if position.type == 1 else mt5.ORDER_TYPE_SELL,
                    "position": position.ticket,
                    "price": tick.ask if position.type == 1 else tick.bid,
                    "deviation": self.config.slippage,
                    "magic": self.config.magic_number,
                    "comment": "Manual Close",
                    "type_time": mt5.ORDER_TIME_GTC,
                }
                result = mt5.order_send(request)
                if result is None:
                    last_error = mt5.last_error()
                    return False, f"Close failed: mt5.order_send returned None. Last error: {last_error}"
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    self.open_positions = [p for p in self.open_positions if p.ticket != ticket]
                    self.trailing_stop.close_position(ticket)
                    self.logger.info(f"Position {ticket} closed successfully")
                    try:
                        self.callback_queue.put_nowait(('position_closed', {
                            'ticket': ticket,
                            'profit': position.profit
                        }))
                    except:
                        pass
                    return True, f"Position {ticket} closed successfully"
                else:
                    self.logger.error(f"Close position {ticket} failed: {result.comment} (retcode: {result.retcode})")
                    return False, f"Close failed: {result.comment}"
            except Exception as e:
                self.logger.error(f"Error closing position {ticket}: {e}")
                return False, str(e)

    def close_all_positions(self) -> Tuple[bool, str]:
        with self.trading_lock:
            try:
                positions = mt5.positions_get()
                if not positions:
                    return True, "No open positions"
                closed_count = 0
                for position in positions:
                    tick = mt5.symbol_info_tick(position.symbol)
                    if not tick:
                        continue
                    request = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": position.symbol,
                        "volume": position.volume,
                        "type": mt5.ORDER_TYPE_BUY if position.type == 1 else mt5.ORDER_TYPE_SELL,
                        "position": position.ticket,
                        "price": tick.ask if position.type == 1 else tick.bid,
                        "deviation": self.config.slippage,
                        "magic": self.config.magic_number,
                        "comment": "Close All",
                        "type_time": mt5.ORDER_TIME_GTC,
                    }
                    result = mt5.order_send(request)
                    if result is None:
                        self.logger.warning(f"Close all: order_send returned None for position {position.ticket}")
                        continue
                    if result.retcode == mt5.TRADE_RETCODE_DONE:
                        closed_count += 1
                        self.trailing_stop.close_position(position.ticket)
                self.open_positions.clear()
                try:
                    self.callback_queue.put_nowait(('all_positions_closed', closed_count))
                except:
                    pass
                return True, f"Closed {closed_count} positions"
            except Exception as e:
                self.logger.error(f"Error in close_all_positions: {e}")
                return False, str(e)

    def modify_position(self, ticket: int, stop_loss: Optional[float] = None, take_profit: Optional[float] = None) -> Tuple[bool, str]:
        with self.trading_lock:
            try:
                positions = mt5.positions_get(ticket=ticket)
                if not positions:
                    return False, f"Position {ticket} not found"
                position = positions[0]
                new_sl = stop_loss if stop_loss is not None else position.sl
                new_tp = take_profit if take_profit is not None else position.tp
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "symbol": position.symbol,
                    "position": position.ticket,
                    "sl": new_sl,
                    "tp": new_tp,
                    "magic": self.config.magic_number,
                    "comment": "Modified via Interface",
                }
                result = mt5.order_send(request)
                if result is None:
                    last_error = mt5.last_error()
                    return False, f"Modify failed: mt5.order_send returned None. Last error: {last_error}"
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    for pos in self.open_positions:
                        if pos.ticket == ticket:
                            pos.sl = new_sl
                            pos.tp = new_tp
                            break
                    self.trailing_stop.modify_position_sl_tp(ticket, new_sl, new_tp)
                    return True, f"Position {ticket} modified successfully"
                else:
                    return False, f"Modify failed: {result.comment}"
            except Exception as e:
                return False, str(e)

    def apply_trailing_to_all_positions(self) -> Tuple[bool, str]:
        try:
            if self.config.symbol is None:
                return False, "No symbol selected"
            positions = mt5.positions_get(symbol=self.config.symbol)
            if not positions:
                return False, "No open positions"
            added_count = 0
            for mt5_position in positions:
                order_type = OrderType.LONG if mt5_position.type == 0 else OrderType.SHORT
                existing_position = self.trailing_stop.get_position(mt5_position.ticket)
                if existing_position:
                    continue
                success = self.trailing_stop.add_position(
                    ticket=mt5_position.ticket,
                    symbol=mt5_position.symbol,
                    order_type=order_type,
                    volume=mt5_position.volume,
                    entry_price=mt5_position.price_open,
                    stop_loss=mt5_position.sl,
                    take_profit=mt5_position.tp,
                    comment="Existing position added to trailing"
                )
                if success:
                    added_count += 1
            if added_count > 0:
                self.logger.info(f"Added {added_count} existing positions to trailing stop management")
                self.force_trailing_stats_update()
                return True, f"Added {added_count} positions to trailing stop management"
            else:
                return True, "All positions already managed by trailing stop"
        except Exception as e:
            self.logger.error(f"Error applying trailing to all positions: {e}")
            return False, str(e)

    def manage_positions(self):
        if not self.open_positions:
            return
        if self.config.enable_trailing_stop_loss:
            self.trailing_stop.update_position_prices()
        current_price = self.get_current_price()
        if not current_price:
            return
        for position in self.open_positions[:]:
            try:
                mt5_position = mt5.positions_get(ticket=position.ticket)
                if not mt5_position:
                    position.exit_price = current_price
                    position.exit_time = datetime.now()
                    position.profit = mt5_position.profit if mt5_position else 0.0
                    self.trade_history.append(position)
                    self.open_positions.remove(position)
                    pnl_sign = "🟢" if position.profit > 0 else "🔴"
                    self.logger.info(f"Position closed: {position.type} #{position.ticket} | P&L: {pnl_sign} ${position.profit:.2f}")
            except Exception as e:
                self.logger.error(f"Error managing position {position.ticket}: {e}")

    def update_account_info(self):
        try:
            account_info = mt5.account_info()
            if account_info:
                self.account_balance = account_info.balance
                self.account_equity = account_info.equity
                if self.account_equity > self.peak_equity:
                    self.peak_equity = self.account_equity
                if self.peak_equity > 0:
                    self.current_drawdown = ((self.peak_equity - self.account_equity) / self.peak_equity) * 100
        except Exception as e:
            self.logger.error(f"Error updating account info: {e}")

    def check_risk_limits(self) -> bool:
        if self.current_drawdown > self.config.max_drawdown:
            self.logger.warning(f"Drawdown limit exceeded: {self.current_drawdown:.2f}% > {self.config.max_drawdown}%")
            return False
        return True

    def update_metrics(self, trade: Trade):
        pass

    def get_current_price(self) -> Optional[float]:
        if self.config.symbol is None:
            return None
        tick = mt5.symbol_info_tick(self.config.symbol)
        if tick:
            return (tick.bid + tick.ask) / 2
        return None

    def get_dashboard_data(self) -> Dict:
        with self.trading_lock:
            try:
                current_price = self.get_current_price()
                point_value = self.get_point_value()

                bot_status = "STOPPED"
                bot_status_detailed = "MANUALLY STOPPED"
                if self.config.auto_trading:
                    bot_status = "RUNNING"
                    bot_status_detailed = "ACTIVE"
                elif self.manual_pause:
                    bot_status = "PAUSED"
                    bot_status_detailed = "MANUALLY PAUSED"
                elif self.session_trades >= self.config.max_trades_per_session:
                    bot_status = "SESSION LIMIT REACHED"
                    bot_status_detailed = f"MAX 5 TRADES REACHED"
                elif not self.trading_enabled:
                    bot_status = "RISK PAUSED"
                    bot_status_detailed = "RISK LIMITS PAUSED"

                current_positions = mt5.positions_get(symbol=self.config.symbol) if self.config.symbol else None
                open_positions_count = len(current_positions) if current_positions else 0
                orders = mt5.orders_get(symbol=self.config.symbol) if self.config.symbol else None
                pending_orders_count = len(orders) if orders else 0

                trailing_stop_data = None
                try:
                    if self.config.enable_trailing_stop_loss and self.trailing_stop:
                        trailing_stop_data = self.trailing_stop.get_performance_summary()
                        if trailing_stop_data:
                            trailing_stop_data['trailing_config'] = {
                                'enabled': self.config.enable_trailing_stop_loss,
                                'lock_amount_dollars': self.config.lock_amount_dollars,
                                'step_amount_dollars': self.config.step_amount_dollars
                            }
                    else:
                        trailing_stop_data = {
                            'enabled': False,
                            'open_positions_count': 0,
                            'performance_metrics': {
                                'total_trades': 0,
                                'winning_trades': 0,
                                'total_profit': 0.0,
                                'profit_factor': 0.0
                            },
                            'trailing_config': {
                                'enabled': False,
                                'lock_amount_dollars': self.config.lock_amount_dollars,
                                'step_amount_dollars': self.config.step_amount_dollars
                            }
                        }
                except Exception as e:
                    self.logger.error(f"Error getting trailing stop data: {e}")
                    trailing_stop_data = {
                        'enabled': False,
                        'open_positions_count': 0,
                        'session_trades': self.session_trades,
                        'session_orders': 0,
                        'performance_metrics': {
                            'total_trades': 0,
                            'winning_trades': 0,
                            'total_profit': 0.0,
                            'profit_factor': 0.0
                        }
                    }

                market_sentiment = self.news_manager.get_market_sentiment() if self.config.use_news_sentiment else {}

                reversal_history = getattr(self.reversal_trader, 'reversal_history', [])
                reversal_stats = {
                    'total_reversals_detected': len(reversal_history),
                    'executed_reversals': sum(1 for r in reversal_history if r.get('should_trade', False)),
                    'skipped_reversals': sum(1 for r in reversal_history if not r.get('should_trade', False)),
                    'average_confidence': np.mean([r.get('confidence', 0) for r in reversal_history]) if reversal_history else 0,
                    'last_reversal': reversal_history[-1] if reversal_history else None
                }

                data = {
                    'status': bot_status,
                    'status_detail': bot_status_detailed,
                    'symbol': self.config.symbol if self.config.symbol else "Not selected",
                    'balance': float(self.account_balance),
                    'equity': float(self.account_equity),
                    'drawdown': float(self.current_drawdown),
                    'open_positions': open_positions_count,
                    'pending_orders': pending_orders_count,
                    'today_trades': len([t for t in self.trade_history if t.entry_time.date() == datetime.now().date()]),
                    'today_pnl': float(sum(t.profit for t in self.trade_history if t.entry_time.date() == datetime.now().date())),
                    'current_signal': self.current_signal.value,
                    'reversal_mode': self.config.reversal_mode,
                    'auto_trading': self.config.auto_trading,
                    'trades_taken_current_signal': self.signal_trades,
                    'trades_taken_current_session': self.session_trades,
                    'aggressive_trades_this_minute': self.aggressive_trades_this_minute,
                    'min_trades_per_signal': self.config.min_trades_per_signal,
                    'max_trades_per_session': 5,
                    'aggressive_mode': self.aggressive_mode,
                    'max_concurrent_positions': 5,
                    'idle_timeout_minutes': self.config.idle_timeout_minutes,
                    'trailing_stop_data': trailing_stop_data,
                    'use_sts': self.use_sts,
                    'close_opposite': self.config.close_opposite_on_signal_change,
                    'use_news': self.config.use_news_sentiment,
                    'point_value': point_value,
                    'alerts_enabled': self.alert_system.enabled,
                    'mt5_connected': self.mt5_connected,
                    'market_sentiment': market_sentiment,
                    'reversal_trading_enabled': self.reversal_mode_enabled,
                    'last_reversal_time': self.last_reversal_time.isoformat() if self.last_reversal_time else None,
                    'reversal_trades_executed': self.reversal_trades_executed,
                    'max_reversal_trades': self.max_reversal_trades,
                    'reversal_cooldown': self.config.reversal_cooldown_seconds,
                    'reversal_trade_volume': self.config.reversal_trade_volume,
                    'reversal_sl_pips': self.config.stop_loss_pips,
                    'reversal_tp_pips': self.config.take_profit_pips,
                    'reversal_min_confidence': self.config.reversal_min_confidence_score,
                    'reversal_stats': reversal_stats,
                    'current_price': current_price,
                }

                if hasattr(self, 'current_signal_detail') and self.current_signal_detail:
                    data['current_entry_price'] = self.current_signal_detail.entry_price
                    data['current_entry_type'] = self.current_signal_detail.entry_type
                    data['trades_remaining'] = self.current_signal_detail.trade_count
                    data['aggressive_mode'] = self.current_signal_detail.aggressive
                    data['signal_comment'] = self.current_signal_detail.comment
                    data['trades_taken_in_signal'] = self.current_signal_detail.trades_taken
                else:
                    data['current_entry_price'] = None
                    data['current_entry_type'] = ''
                    data['trades_remaining'] = 0
                    data['aggressive_mode'] = False
                    data['signal_comment'] = ''
                    data['trades_taken_in_signal'] = 0

                return data
            except Exception as e:
                self.logger.error(f"Error getting dashboard data: {e}")
                return {
                    'status': 'ERROR',
                    'symbol': 'ERROR',
                    'balance': 0.0,
                    'equity': 0.0,
                    'drawdown': 0.0,
                    'open_positions': 0,
                    'pending_orders': 0,
                    'current_signal': 'ERROR',
                    'auto_trading': self.config.auto_trading,
                    'point_value': 0.01,
                    'alerts_enabled': True,
                    'mt5_connected': self.mt5_connected,
                    'trailing_stop_data': {
                        'enabled': self.config.enable_trailing_stop_loss,
                        'open_positions_count': 0,
                        'session_trades': 0,
                        'session_orders': 0,
                        'performance_metrics': {
                            'total_trades': 0,
                            'winning_trades': 0,
                            'total_profit': 0.0,
                            'profit_factor': 0.0
                        }
                    },
                    'reversal_trading_enabled': self.reversal_mode_enabled,
                    'current_price': None,
                }

    def get_trailing_stop_stats(self) -> Dict[str, Any]:
        try:
            if self.trailing_stop:
                return self.trailing_stop.get_performance_summary()
            return {}
        except Exception as e:
            self.logger.error(f"Error getting trailing stop stats: {e}")
            return {}

    def get_recent_trades(self) -> List[Dict]:
        try:
            from_date = datetime.now() - timedelta(days=30)
            to_date = datetime.now()
            history_deals = mt5.history_deals_get(from_date, to_date)
            if history_deals and len(history_deals) > 0:
                trades = []
                for deal in sorted(history_deals, key=lambda x: x.time, reverse=True)[:50]:
                    trades.append({
                        'ticket': deal.ticket,
                        'symbol': deal.symbol,
                        'type': "BUY" if deal.type == 0 else "SELL",
                        'volume': deal.volume,
                        'entry_price': deal.price,
                        'profit': deal.profit,
                        'entry_time': datetime.fromtimestamp(deal.time).isoformat(),
                        'comment': deal.comment
                    })
                return trades
        except Exception as e:
            self.logger.error(f"Error getting trade history: {e}")
        return [t.to_dict() for t in self.trade_history[-50:]]

    def get_open_positions(self) -> List[Dict]:
        with self.trading_lock:
            positions = []
            try:
                mt5_positions = mt5.positions_get()
                if mt5_positions is None:
                    self.logger.error(f"Failed to get positions: {mt5.last_error()}")
                    return positions
                for mt5_position in mt5_positions:
                    profit = mt5_position.profit
                    trailing_position = self.trailing_stop.get_position(mt5_position.ticket)
                    locked_profit = None
                    if trailing_position and trailing_position.trailing_stop is not None:
                        point_value = self.get_point_value()
                        if mt5_position.type == 0:
                            locked_profit = (mt5_position.price_current - trailing_position.trailing_stop) * mt5_position.volume * point_value
                        else:
                            locked_profit = (trailing_position.trailing_stop - mt5_position.price_current) * mt5_position.volume * point_value
                    positions.append({
                        'ticket': mt5_position.ticket,
                        'symbol': mt5_position.symbol,
                        'type': "BUY" if mt5_position.type == 0 else "SELL",
                        'volume': mt5_position.volume,
                        'entry': mt5_position.price_open,
                        'current': mt5_position.price_current,
                        'profit': profit,
                        'sl': mt5_position.sl,
                        'tp': mt5_position.tp,
                        'breakeven_reached': trailing_position.breakeven_reached if trailing_position else False,
                        'trailing_managed': trailing_position is not None,
                        'trailing_stop': trailing_position.trailing_stop if trailing_position else None,
                        'locked_profit': locked_profit,
                        'comment': mt5_position.comment
                    })
            except Exception as e:
                self.logger.error(f"Error getting open positions: {e}", exc_info=True)
            return positions

    def get_pending_orders(self) -> List[Dict]:
        try:
            orders = mt5.orders_get(symbol=self.config.symbol)
            if orders:
                return [{
                    'ticket': order.ticket,
                    'symbol': order.symbol,
                    'type': "BUY LIMIT" if order.type == 2 else "SELL LIMIT" if order.type == 3 else "BUY STOP" if order.type == 4 else "SELL STOP",
                    'volume': order.volume_current,
                    'price': order.price_open,
                    'sl': order.sl,
                    'tp': order.tp,
                    'expiration': datetime.fromtimestamp(order.time_expiration).strftime('%Y-%m-%d %H:%M') if order.time_expiration > 0 else 'GTC',
                    'comment': order.comment
                } for order in orders]
        except Exception as e:
            self.logger.error(f"Error getting pending orders: {e}")
        return []

    def run(self):
        """Main trading loop"""
        try:
            last_update = datetime.now() - timedelta(seconds=10)
            last_signal_check = datetime.now() - timedelta(minutes=1)
            last_trade_attempt = datetime.now() - timedelta(minutes=1)
            last_trailing_update = datetime.now() - timedelta(seconds=5)
            last_broadcast = datetime.now() - timedelta(seconds=1)
            last_mt5_check = datetime.now() - timedelta(seconds=30)
            last_trailing_stats_broadcast = datetime.now() - timedelta(seconds=2)

            previous_auto_state = self.config.auto_trading
            previous_sts_state = self.use_sts
            previous_reversal_state = self.reversal_mode_enabled

            self.logger.info("Starting main trading loop...")

            while self.running:
                current_time = datetime.now()

                if (current_time - last_mt5_check).seconds >= 30:
                    was_connected = self.mt5_connected
                    try:
                        if mt5.terminal_info():
                            if not was_connected:
                                self.mt5_connected = True
                                self.logger.info("MT5 connection restored")
                                self.alert_system.alert_connection_restored()
                                # Resync trailing stop if enabled
                                if self.config.enable_trailing_stop_loss:
                                    self.sync_existing_positions_with_trailing()
                        else:
                            if was_connected:
                                self.mt5_connected = False
                                self.logger.warning("MT5 connection lost")
                                self.alert_system.alert_connection_lost()
                            else:
                                # Already disconnected – attempt reconnect
                                self._attempt_reconnect()
                    except Exception as e:
                        self.logger.error(f"MT5 check error: {e}")
                        if was_connected:
                            self.mt5_connected = False
                            self.logger.warning("MT5 connection lost")
                            self.alert_system.alert_connection_lost()
                        else:
                            self._attempt_reconnect()
                    last_mt5_check = current_time

                if (current_time - last_update).seconds >= 10:
                    self.update_account_info()
                    last_update = current_time

                if self.config.enable_trailing_stop_loss and (current_time - last_trailing_update).total_seconds() >= 0.2:
                    try:
                        with self.trading_lock:
                            self.trailing_stop.update_position_prices()
                    except RuntimeError as e:
                        self.logger.error(f"Trailing stop update error (will retry): {e}")
                    except Exception as e:
                        self.logger.error(f"Unexpected error in trailing stop: {e}")
                    finally:
                        last_trailing_update = current_time

                if previous_auto_state != self.config.auto_trading:
                    if self.config.auto_trading:
                        self.logger.info("Auto trading ENABLED")
                        self.manual_pause = False
                    else:
                        self.logger.info("Auto trading DISABLED")
                        self.manual_pause = True
                    previous_auto_state = self.config.auto_trading

                if previous_sts_state != self.use_sts:
                    self.set_sts_mode(self.use_sts)
                    previous_sts_state = self.use_sts

                if not self.check_risk_limits():
                    if self.trading_enabled:
                        self.logger.warning("Risk limits exceeded - trading suspended")
                        self.trading_enabled = False
                    time.sleep(5)
                    continue
                elif not self.trading_enabled:
                    self.trading_enabled = True
                    self.logger.info("Risk limits OK - trading resumed")

                if self.config.symbol is not None:
                    rates_1min = mt5.copy_rates_from_pos(self.config.symbol, mt5.TIMEFRAME_M1, 0, 1)
                    if rates_1min is not None and len(rates_1min) > 0:
                        bar = rates_1min[0]
                        bar_time = bar[0]
                        if bar_time != self.last_bar_time_1min:
                            self.indicator_sts_1min.update(bar[1], bar[2], bar[3], bar[4], bar[5])
                            self.last_bar_time_1min = bar_time

                    rates_5min = mt5.copy_rates_from_pos(self.config.symbol, mt5.TIMEFRAME_M5, 0, 1)
                    if rates_5min is not None and len(rates_5min) > 0:
                        bar = rates_5min[0]
                        bar_time = bar[0]
                        if bar_time != self.last_bar_time_5min:
                            self.indicator_5min.update(bar[1], bar[2], bar[3], bar[4], bar[5])
                            self.indicator_sts_5min.update(bar[1], bar[2], bar[3], bar[4], bar[5])
                            self.last_bar_time_5min = bar_time

                    rates_15min = mt5.copy_rates_from_pos(self.config.symbol, mt5.TIMEFRAME_M15, 0, 1)
                    if rates_15min is not None and len(rates_15min) > 0:
                        bar = rates_15min[0]
                        bar_time = bar[0]
                        if bar_time != self.last_bar_time_15min:
                            self.indicator_15min.update(bar[1], bar[2], bar[3], bar[4], bar[5])
                            self.last_bar_time_15min = bar_time

                    signal = self.calculate_signal()

                    if self.config.close_opposite_on_signal_change and signal != self.previous_signal and signal != TradeSignal.NEUTRAL:
                        self.logger.info(f"Signal changed from {self.previous_signal.value} to {signal.value} – closing opposite positions")
                        self.close_positions_opposite_to_signal(signal)

                    if self.can_trade_auto() and signal != TradeSignal.NEUTRAL:
                        time_since_last_trade = (current_time - last_trade_attempt).seconds
                        should_trade = False
                        trade_interval = self.config.normal_trade_interval
                        trade_message = f"Normal {signal.value}"

                        if self.should_trade_aggressively():
                            trade_interval = self.config.aggressive_trade_interval
                            trade_message = f"AGGRESSIVE {signal.value}"
                            self.aggressive_mode = True
                            should_trade = True
                            if self.aggressive_trades_this_minute >= self.config.aggressive_trades_per_minute:
                                self.logger.info(f"Already reached {self.aggressive_trades_this_minute} trades this minute")
                                should_trade = False
                        else:
                            trade_interval = self.config.normal_trade_interval
                            trade_message = f"Normal {signal.value}"
                            self.aggressive_mode = False
                            should_trade = True

                        if self.session_trades >= self.config.max_trades_per_session:
                            self.logger.info(f"Session limit reached: {self.session_trades}/5")
                            self.aggressive_mode = False
                            should_trade = False

                        if should_trade and time_since_last_trade >= trade_interval:
                            current_positions = mt5.positions_get(symbol=self.config.symbol)
                            open_positions = len(current_positions) if current_positions else 0

                            self.logger.info(f"{trade_message} "
                                           f"(Signal: {self.signal_trades}/{self.config.min_trades_per_signal}) "
                                           f"(Session: {self.session_trades}/5) "
                                           f"(This minute: {self.aggressive_trades_this_minute}/{self.config.aggressive_trades_per_minute}) "
                                           f"(Positions: {open_positions}/5)")

                            if self.trading_enabled and self.check_trading_conditions():
                                success, message = self.execute_trade(signal, is_manual=False)
                                if success:
                                    last_trade_attempt = current_time
                                    self.logger.info(f"Auto trade #{self.session_trades} executed")

                self.manage_positions()
                self.check_pending_orders()
                # Manage stale pending orders every configured interval
                
                self.logger.info(f"Checking pending orders: interval={self.config.pending_order_check_interval}, last={self.last_pending_manage}, now={current_time}")
                if (current_time - self.last_pending_manage).seconds >= self.config.pending_order_check_interval:
                    self.logger.info("Calling manage_pending_orders")
                    self.manage_pending_orders()
                    self.last_pending_manage = current_time

                if self.callback_queue:
                    if (current_time - last_broadcast).seconds >= 1:
                        try:
                            dashboard_data = self.get_dashboard_data()
                            positions = self.get_open_positions()
                            if 'trailing_stop_data' not in dashboard_data:
                                dashboard_data['trailing_stop_data'] = {
                                    'enabled': self.config.enable_trailing_stop_loss,
                                    'open_positions_count': 0
                                }
                            self.callback_queue.put_nowait(('data_update', {
                                'dashboard': dashboard_data,
                                'positions': positions
                            }))
                            last_broadcast = current_time
                        except queue.Full:
                            pass
                        except Exception as e:
                            self.logger.error(f"Error broadcasting updates: {e}")

                    if (current_time - last_trailing_stats_broadcast).seconds >= 2 and self.config.enable_trailing_stop_loss:
                        try:
                            self.force_trailing_stats_update()
                            last_trailing_stats_broadcast = current_time
                        except Exception as e:
                            self.logger.error(f"Error broadcasting trailing stats: {e}")

                time.sleep(0.5)

        except KeyboardInterrupt:
            self.logger.info("Shutting down by user request...")
        except Exception as e:
            self.logger.error(f"Error in main loop: {str(e)}", exc_info=True)
            if self.callback_queue:
                try:
                    self.callback_queue.put_nowait(('error', f"Main loop error: {str(e)}"))
                except:
                    pass
        finally:
            self.shutdown()

    def signal_handler(self, signum, frame):
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def shutdown(self):
        self.logger.info("Shutting down trading system...")
        self.running = False
        if hasattr(self, 'news_manager'):
            try:
                self.news_manager.logout()
            except Exception as e:
                self.logger.error(f"Error logging out from news manager: {e}")
        if self.callback_queue:
            try:
                self.callback_queue.put_nowait(('system_shutdown', None))
            except:
                pass
        try:
            mt5.shutdown()
        except:
            pass
        self.logger.info("Trading system shut down successfully")