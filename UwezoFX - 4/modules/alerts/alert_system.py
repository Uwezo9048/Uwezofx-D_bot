# modules/alerts/alert_system.py
import time
import platform
import subprocess
import queue
from datetime import datetime
from enum import Enum
from typing import Optional

class AlertPriority(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"

class AlertSystem:
    SOUNDS = {
        'buy_signal': {'freq': 800, 'duration': 200, 'repeat': 2, 'priority': AlertPriority.HIGH},
        'sell_signal': {'freq': 400, 'duration': 200, 'repeat': 2, 'priority': AlertPriority.HIGH},
        'signal_reversal': {'freq': 1000, 'duration': 300, 'repeat': 3, 'priority': AlertPriority.CRITICAL},
        'overbought': {'freq': 600, 'duration': 150, 'repeat': 2, 'priority': AlertPriority.MEDIUM},
        'oversold': {'freq': 600, 'duration': 150, 'repeat': 2, 'priority': AlertPriority.MEDIUM},
        'trade_execution': {'freq': 1200, 'duration': 50, 'repeat': 1, 'priority': AlertPriority.HIGH},
        'stop_loss_hit': {'freq': 200, 'duration': 500, 'repeat': 2, 'priority': AlertPriority.CRITICAL},
        'take_profit_hit': {'freq': 1500, 'duration': 200, 'repeat': 3, 'priority': AlertPriority.CRITICAL},
        'profit_locked': {'freq': 1000, 'duration': 100, 'repeat': 1, 'priority': AlertPriority.HIGH},
        'high_impact_news': {'freq': 900, 'duration': 400, 'repeat': 3, 'priority': AlertPriority.HIGH},
        'error': {'freq': 200, 'duration': 1000, 'repeat': 1, 'priority': AlertPriority.CRITICAL},
        'connection_lost': {'freq': 300, 'duration': 500, 'repeat': 3, 'priority': AlertPriority.CRITICAL},
        'connection_restored': {'freq': 800, 'duration': 200, 'repeat': 2, 'priority': AlertPriority.HIGH},
        'reversal_execution': {'freq': 1200, 'duration': 150, 'repeat': 5, 'priority': AlertPriority.CRITICAL},
        'reversal_skipped': {'freq': 600, 'duration': 100, 'repeat': 2, 'priority': AlertPriority.MEDIUM},
    }

    def __init__(self, logger, callback_queue):
        self.logger = logger
        self.callback_queue = callback_queue
        self.enabled = True
        self.last_alert_time = {}
        self.alert_cooldown = 2
        self.system = platform.system()
        self._init_platform_sounds()

    def _init_platform_sounds(self):
        if self.system == "Windows":
            try:
                import winsound
                self.winsound = winsound
                self.sound_available = True
            except:
                self.sound_available = False
        elif self.system == "Darwin":
            self.sound_available = True
        else:
            self.sound_available = self._check_linux_sound()
        if not self.sound_available:
            self.logger.warning("System sounds not available")

    def _check_linux_sound(self):
        for cmd in ['speaker-test', 'aplay', 'paplay']:
            try:
                subprocess.run(['which', cmd], capture_output=True, check=True)
                return True
            except:
                continue
        return False

    def _beep(self, frequency=800, duration=200):
        if not self.enabled:
            return
        try:
            if self.system == "Windows":
                self.winsound.Beep(frequency, duration)
            elif self.system == "Darwin":
                subprocess.run(['osascript', '-e', 'beep'], capture_output=True, check=False)
                print('\a', end='', flush=True)
            else:
                try:
                    subprocess.run(['speaker-test', '-t', 'sine', '-f', str(frequency), 
                                    '-l', '1', '-p', str(duration)], 
                                   timeout=0.5, capture_output=True, check=False)
                except:
                    print('\a', end='', flush=True)
        except Exception as e:
            self.logger.debug(f"Sound error: {e}")
            print('\a', end='', flush=True)

    def _play_pattern(self, sound_type):
        if sound_type not in self.SOUNDS:
            return
        config = self.SOUNDS[sound_type]
        freq = config['freq']
        duration = config['duration']
        repeat = config['repeat']
        for i in range(repeat):
            self._beep(freq, duration)
            if i < repeat - 1:
                time.sleep(0.05)

    def _can_alert(self, alert_type):
        now = time.time()
        if alert_type in self.last_alert_time:
            if now - self.last_alert_time[alert_type] < self.alert_cooldown:
                return False
        self.last_alert_time[alert_type] = now
        return True

    def alert(self, alert_type: str, title: str, message: str, priority: AlertPriority = AlertPriority.MEDIUM):
        if not self._can_alert(alert_type):
            return
        if alert_type in self.SOUNDS:
            self._play_pattern(alert_type)
        safe_message = message.replace('→', '->')
        safe_title = title.replace('→', '->')
        log_message = f"{safe_title}: {safe_message}"
        if priority == AlertPriority.CRITICAL:
            self.logger.error(log_message)
        elif priority == AlertPriority.HIGH:
            self.logger.warning(log_message)
        else:
            self.logger.info(log_message)
        try:
            self.callback_queue.put_nowait(('notification', {
                'type': alert_type,
                'title': title,
                'message': message,
                'priority': priority.value,
                'timestamp': datetime.now().isoformat()
            }))
        except queue.Full:
            self.logger.warning("Alert queue full, notification lost")

    def alert_buy_signal(self, price=None, reason=""):
        price_str = f" at {price:.2f}" if price else ""
        self.alert('buy_signal', 'BUY SIGNAL', f"{price_str} - {reason}", AlertPriority.HIGH)

    def alert_sell_signal(self, price=None, reason=""):
        price_str = f" at {price:.2f}" if price else ""
        self.alert('sell_signal', 'SELL SIGNAL', f"{price_str} - {reason}", AlertPriority.HIGH)

    def alert_signal_reversal(self, old_signal, new_signal, price=None):
        price_str = f" at {price:.2f}" if price else ""
        message = f"{old_signal} → {new_signal}{price_str}"
        safe_message = f"{old_signal} -> {new_signal}{price_str}"
        self.alert('signal_reversal', 'SIGNAL REVERSAL', message, AlertPriority.CRITICAL)
        self.logger.info(f"Signal reversal: {safe_message}")

    def alert_reversal_execution(self, count=5):
        self.alert('reversal_execution', '⚡ REVERSAL TRADES', 
                   f"Executing {count} reversal trades immediately!", AlertPriority.CRITICAL)

    def alert_reversal_skipped(self, reason, confidence):
        self.alert('reversal_skipped', '⏸️ REVERSAL SKIPPED', 
                   f"{reason} (Confidence: {confidence:.1f}%)", AlertPriority.MEDIUM)

    def alert_overbought(self, indicator, value, threshold):
        self.alert('overbought', 'OVERBOUGHT', 
                   f"{indicator} = {value:.1f} (threshold {threshold})", AlertPriority.MEDIUM)

    def alert_oversold(self, indicator, value, threshold):
        self.alert('oversold', 'OVERSOLD', 
                   f"{indicator} = {value:.1f} (threshold {threshold})", AlertPriority.MEDIUM)

    def alert_trade_execution(self, direction, volume, price):
        self.alert('trade_execution', 'TRADE EXECUTED', 
                   f"{direction} {volume} lots at {price:.2f}", AlertPriority.HIGH)

    def alert_stop_loss_hit(self, position):
        self.alert('stop_loss_hit', 'STOP LOSS HIT', 
                   f"{position.symbol} #{position.ticket} - Loss: ${abs(position.profit):.2f}", 
                   AlertPriority.CRITICAL)

    def alert_take_profit_hit(self, position):
        self.alert('take_profit_hit', 'TAKE PROFIT HIT', 
                   f"{position.symbol} #{position.ticket} - Profit: ${position.profit:.2f}", 
                   AlertPriority.CRITICAL)

    def alert_profit_locked(self, position, locked_amount):
        self.alert('profit_locked', 'PROFIT LOCKED', 
                   f"{position.symbol} #{position.ticket} - Locked: ${locked_amount:.2f}", 
                   AlertPriority.HIGH)

    def alert_high_impact_news(self, news_item):
        self.alert('high_impact_news', 'HIGH IMPACT NEWS', 
                   news_item.get('title', 'Economic Event'), AlertPriority.HIGH)

    def alert_error(self, error_message):
        self.alert('error', 'SYSTEM ERROR', error_message, AlertPriority.CRITICAL)

    def alert_connection_lost(self):
        self.alert('connection_lost', 'CONNECTION LOST', 
                   "MT5 connection lost - using simulated data", AlertPriority.CRITICAL)

    def alert_connection_restored(self):
        self.alert('connection_restored', 'CONNECTION RESTORED', 
                   "MT5 connection restored", AlertPriority.HIGH)

    def set_enabled(self, enabled):
        self.enabled = enabled
        status = "ENABLED" if enabled else "DISABLED"
        self.logger.info(f"Sound alerts {status}")