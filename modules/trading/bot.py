import asyncio
import contextlib
import json
import math
import os
import time
import platform
import sys
import websockets
from typing import Optional, List, Dict, Any
from datetime import datetime
from config import BotConfig, Settings
from modules.trading.indicator import CombinedICTandSMSIndicator, TradeSignal
from modules.trading.analyzer import MarketAnalyzer
from modules.trading.strategies import DigitAnalyzer, StrategySignals

class DerivBot:
    def __init__(self, api_token: str, config: BotConfig, log_callback=None,
                 balance_callback=None, stake_callback=None, signal_callback=None,
                 confidence_callback=None, digit_stats_callback=None, strategy_update_callback=None,
                 positions_callback=None, trade_history_callback=None):
        self.token = api_token
        self.config = config
        self.app_id = config.app_id or Settings.DERIV_APP_ID
        self.log = log_callback or print
        self.update_balance = balance_callback
        self.update_stake = stake_callback
        self.signal_callback = signal_callback
        self.confidence_callback = confidence_callback
        self.digit_stats_callback = digit_stats_callback
        self.strategy_update_callback = strategy_update_callback
        self.positions_callback = positions_callback
        self.trade_history_callback = trade_history_callback

        self.ws = None
        self.req_id = 0
        self.pending = {}
        self._loop = None

        self.ignore_next_result = False  # Flag to skip martingale update after manual reset

        self.indicator = CombinedICTandSMSIndicator()
        self.digit_analyzer = DigitAnalyzer(window_size=100)
        self.account_currency = "USD"
        self.balance = 0.0
        self.daily_pnl = 0.0
        self.last_trade_time = 0
        self.signal_queue = asyncio.Queue()
        self.running = True
        self._message_loop_task = None
        self._trade_executor_task = None
        self._ping_task = None
        self._trade_history_task = None
        self._last_candle_minute = None
        self.consecutive = 0
        self.current_stake = config.base_stake
        self._reconnect_attempts = 0

        self.price_highs = []
        self.price_lows = []
        self.price_closes = []
        self.nearest_support = None
        self.nearest_resistance = None
        self.trendline_slope = None
        self.rsi = 50.0
        self.ma_cross = 0

        self.signal_counter = 0
        self.current_confirmed_signal = TradeSignal.NEUTRAL
        self.last_signal_stored = TradeSignal.NEUTRAL

        self.digit_setup_active = None
        self.digit_trigger_state = {}
        self.tick_history_digits = []
        self.last_strategy_check = 0

        self.auto_trade = False
        self.adaptive_mode = False
        self.latest_confidence = 0

        self.open_positions = []

    def _is_ws_open(self) -> bool:
        if self.ws is None:
            return False
        closed_attr = getattr(self.ws, "closed", None)
        if isinstance(closed_attr, bool):
            return not closed_attr
        # Some websockets versions don't expose `.closed` as a bool.
        # In that case, treat the connection as open and let send/recv raise if it is not.
        return True

    def _fail_pending(self, exc: Exception):
        for fut in list(self.pending.values()):
            if not fut.done():
                fut.set_exception(exc)
        self.pending.clear()

    def _resolve_profit_loss(self, buy_price: float, sell_price: float, profit_value):
        if profit_value not in (None, ""):
            return float(profit_value)
        if buy_price > 0:
            return sell_price - buy_price
        return 0.0

    def _safe_float(self, value, default: float = 0.0) -> float:
        try:
            if value in (None, ""):
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def _extract_trade_amounts(self, txn: Dict[str, Any]) -> tuple[float, float, float]:
        buy_price = abs(self._safe_float(
            txn.get(
                'buy_price',
                txn.get(
                    'buy',
                    txn.get(
                        'amount',
                        txn.get('stake', txn.get('purchase_price', 0))
                    )
                )
            )
        ))
        sell_price = max(0.0, self._safe_float(
            txn.get('sell_price', txn.get('sell', txn.get('sell_amount', 0)))
        ))
        payout = max(0.0, self._safe_float(txn.get('payout', txn.get('payout_price', sell_price))))
        return buy_price, sell_price, payout

    def _resolve_history_profit_loss(self, txn: Dict[str, Any]) -> float:
        profit_value = txn.get('profit_loss')
        if profit_value not in (None, ""):
            return self._safe_float(profit_value)

        buy_price, sell_price, payout = self._extract_trade_amounts(txn)
        if buy_price > 0 and sell_price > 0:
            return sell_price - buy_price
        if buy_price > 0 and payout > 0:
            return payout - buy_price
        if buy_price > 0:
            return -buy_price
        return 0.0

    def _parse_trade_time(self, value) -> str:
        timestamp = int(self._safe_float(value, 0))
        if timestamp <= 0:
            return ""
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

    def _format_report_time(self, value) -> str:
        timestamp = int(self._safe_float(value, 0))
        if timestamp <= 0:
            return ""
        return datetime.utcfromtimestamp(timestamp).strftime('%d %b %Y %H:%M:%S GMT')

    def _derive_statement_market(self, txn: Dict[str, Any]) -> str:
        market = (
            txn.get('symbol')
            or txn.get('underlying')
            or txn.get('display_name')
            or txn.get('contract_type')
            or txn.get('shortcode')
            or txn.get('longcode')
            or txn.get('description')
            or ""
        )
        market = str(market).strip()
        if len(market) > 48:
            market = market[:45] + "..."
        return market

    def _derive_statement_profit_loss(self, txn: Dict[str, Any], amount: float) -> str:
        profit_value = txn.get('profit_loss')
        if profit_value not in (None, ""):
            return f"{self._safe_float(profit_value):.2f}"

        action = str(txn.get('action_type', txn.get('action', txn.get('transaction_type', '')))).lower()
        if any(word in action for word in ('buy', 'purchase', 'sell', 'payout', 'settlement', 'expire')):
            return f"{amount:.2f}"

        payout = self._safe_float(txn.get('payout', txn.get('payout_price', 0)))
        buy_price = self._safe_float(
            txn.get('buy_price', txn.get('buy', txn.get('amount', txn.get('stake', 0))))
        )
        if payout > 0 and buy_price > 0:
            return f"{(payout - buy_price):.2f}"
        return ""

    def _build_report_rows_from_statement(self, transactions: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        rows = []

        for txn in transactions:
            action = str(txn.get('action_type', txn.get('action', txn.get('transaction_type', ''))))
            amount = self._safe_float(txn.get('amount', txn.get('amount_for_display', 0)))
            balance = self._safe_float(txn.get('balance_after', txn.get('balance', 0)))
            profit_loss = self._derive_statement_profit_loss(txn, amount)

            timestamp = int(self._safe_float(
                txn.get('transaction_time', txn.get('time', txn.get('date_start', 0))),
                0
            ))

            rows.append({
                'ref': txn.get('contract_id') or txn.get('reference_id') or txn.get('transaction_id') or '',
                'action': action or '',
                'market': self._derive_statement_market(txn),
                'amount': amount,
                'profit_loss': profit_loss,
                'balance': balance,
                'time': self._parse_trade_time(timestamp),
                'details': txn.get('longcode') or txn.get('description') or txn.get('display_name') or '',
                '_sort_ts': timestamp,
            })

        rows.sort(key=lambda row: row.get('_sort_ts', 0), reverse=True)
        return rows[:limit]

    def _build_trade_history_from_statement(self, transactions: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
        """Build trade history in format matching Deriv report."""
        grouped: Dict[Any, Dict[str, Any]] = {}

        for txn in transactions:
            contract_id = txn.get('contract_id') or txn.get('reference_id') or txn.get('contract_reference')
            if not contract_id:
                continue

            entry = grouped.setdefault(contract_id, {
                'contract_id': contract_id,
                'contract_type': txn.get('contract_type') or txn.get('display_name') or '',
                'currency': txn.get('currency') or self.account_currency,
                'buy_price': 0.0,
                'sell_price': 0.0,
                'profit_loss': 0.0,
                'start_ts': 0,
                'end_ts': 0,
                'has_buy': False,
                'has_sell': False,
            })

            if not entry['contract_type']:
                entry['contract_type'] = txn.get('contract_type') or txn.get('display_name') or ''
            if not entry['currency']:
                entry['currency'] = txn.get('currency') or self.account_currency

            action = str(txn.get('action_type', txn.get('action', txn.get('transaction_type', '')))).lower()
            amount = self._safe_float(txn.get('amount', txn.get('amount_for_display', 0)))
            buy_price_raw, sell_price_raw, payout = self._extract_trade_amounts(txn)
            transaction_time = int(self._safe_float(
                txn.get('transaction_time', txn.get('time', txn.get('date_start', 0))),
                0
            ))

            is_buy = 'buy' in action or 'purchase' in action
            is_sell = any(word in action for word in ('sell', 'payout', 'settlement', 'expire'))

            if is_buy:
                if buy_price_raw > 0:
                    entry['buy_price'] = buy_price_raw
                elif amount != 0:
                    entry['buy_price'] = abs(amount)
                entry['has_buy'] = True
                if transaction_time:
                    entry['start_ts'] = transaction_time

            if is_sell:
                if sell_price_raw > 0:
                    entry['sell_price'] = sell_price_raw
                elif payout > 0:
                    entry['sell_price'] = payout
                elif amount > 0:
                    entry['sell_price'] = amount
                entry['has_sell'] = True
                if transaction_time:
                    entry['end_ts'] = transaction_time

            profit_value = txn.get('profit_loss')
            if profit_value not in (None, ""):
                entry['profit_loss'] = self._safe_float(profit_value)

        trades = []
        for entry in grouped.values():
            if not entry['has_buy']:
                continue

            if entry['profit_loss'] == 0.0:
                if entry['has_sell'] and entry['sell_price'] > 0:
                    entry['profit_loss'] = entry['sell_price'] - entry['buy_price']
                else:
                    entry['profit_loss'] = -entry['buy_price']

            trades.append({
                'type': entry['contract_type'],           # For compatibility
                'contract_type': entry['contract_type'],  # For type formatting
                'ref_id': entry['contract_id'],           # Match Deriv report field name
                'contract_id': entry['contract_id'],      # Keep for backward compatibility
                'currency': entry['currency'] or self.account_currency,
                'buy_time': self._format_report_time(entry['start_ts']),
                'start_time': self._format_report_time(entry['start_ts']),  # Keep both
                'stake': entry['buy_price'],
                'buy_price': entry['buy_price'],          # Keep for backward compatibility
                'sell_time': self._format_report_time(entry['end_ts']),
                'end_time': self._format_report_time(entry['end_ts']),      # Keep both
                'contract_value': entry['sell_price'],
                'payout': entry['sell_price'],            # Keep for backward compatibility
                'sell_price': entry['sell_price'],        # Keep for backward compatibility
                'profit_loss': entry['profit_loss'],
                '_sort_ts': entry['end_ts'] or entry['start_ts'],
            })

        trades.sort(key=lambda trade: trade.get('_sort_ts', 0), reverse=True)
        return trades[:limit]

    def _digit_win_rate(self, signal: str) -> float:
        stats = self.digit_analyzer.digits
        if signal == TradeSignal.OVER:
            win_digits = [4, 5, 6, 7, 8, 9]
        elif signal == TradeSignal.UNDER:
            win_digits = [0, 1, 2, 3, 4, 5]
        elif signal == TradeSignal.EVEN:
            win_digits = [0, 2, 4, 6, 8]
        elif signal == TradeSignal.ODD:
            win_digits = [1, 3, 5, 7, 9]
        else:
            return 0.0
        return sum(stats[d].percentage for d in win_digits)

    def _minimum_trade_confidence(self) -> float:
        try:
            return float(getattr(self.config, "min_digit_confidence", 62))
        except (TypeError, ValueError):
            return 62.0

    def _choose_tick_duration(self, signal: str) -> int:
        if not self.config.auto_ticks:
            return max(1, int(self.config.ticks_duration))

        stats = self.digit_analyzer.digits
        if signal == TradeSignal.OVER:
            favorable_digits = [4, 5, 6, 7, 8, 9]
            unfavorable_digits = [0, 1, 2, 3]
        elif signal == TradeSignal.UNDER:
            favorable_digits = [0, 1, 2, 3, 4, 5]
            unfavorable_digits = [6, 7, 8, 9]
        else:
            return max(1, int(self.config.ticks_duration))

        favorable_pct = sum(stats[d].percentage for d in favorable_digits)
        unfavorable_pct = sum(stats[d].percentage for d in unfavorable_digits)
        strength = favorable_pct - unfavorable_pct

        if strength >= 20:
            return 1
        if strength >= 12:
            return 2
        if strength >= 6:
            return 3
        return max(1, int(self.config.ticks_duration))

    def _update_martingale_after_trade(self, profit: float):
        mode = (self.config.martingale_mode or "Classic").strip().lower()

        if profit > 0:
            if mode == "reverse":
                self.consecutive += 1
                if self.consecutive <= self.config.max_martingale_steps:
                    self.current_stake *= self.config.martingale_mult
                    self.log_message(
                        f"Winning trade. Reverse martingale next stake: {self.current_stake:.2f} (level {self.consecutive})"
                    )
                else:
                    self.log_message("Max reverse martingale steps reached. Resetting to base stake.")
                    self.consecutive = 0
                    self.current_stake = self.config.base_stake
            else:
                self.consecutive = 0
                self.current_stake = self.config.base_stake
                self.log_message("Winning trade. Classic martingale reset to base stake.")
            return

        if profit < 0:
            if mode == "reverse":
                self.consecutive = 0
                self.current_stake = self.config.base_stake
                self.log_message("Losing trade. Reverse martingale reset to base stake.")
            else:
                self.consecutive += 1
                if self.consecutive <= self.config.max_martingale_steps:
                    self.current_stake *= self.config.martingale_mult
                    self.log_message(
                        f"Losing trade. Classic martingale next stake: {self.current_stake:.2f} (level {self.consecutive})"
                    )
                else:
                    self.log_message("Max martingale steps reached. Resetting to base stake.")
                    self.consecutive = 0
                    self.current_stake = self.config.base_stake
            return

        self.log_message("Trade settled at break-even. Stake unchanged.")

    def set_event_loop(self, loop):
        self._loop = loop

    def set_mode(self, mode: str):
        self.auto_trade = mode in ["Auto-Trade", "Adaptive"]
        self.adaptive_mode = (mode == "Adaptive")
        if self.log:
            self.log_message(f"Mode changed to: {mode} (AutoTrade: {self.auto_trade}, Adaptive: {self.adaptive_mode})")

    async def reset_martingale(self):
        """Reset martingale state and ignore the result of the current in‑progress trade."""
        self.consecutive = 0
        self.current_stake = self.config.base_stake
        self.ignore_next_result = True
        self.log_message("🔄 Martingale reset manually: stake reset to base. Next trade result will be ignored.")
        if self.update_stake:
            self.update_stake(self.current_stake, self.consecutive)

    def log_message(self, msg, level="INFO"):
        if self.log:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log(f"[{timestamp}] {msg}")

    def update_confidence_display(self, confidence):
        if self.confidence_callback:
            self.confidence_callback(confidence)

    async def _send(self, msg):
        if not self._is_ws_open():
            raise ConnectionError("WebSocket is not connected")
        self.req_id += 1
        msg['req_id'] = self.req_id
        fut = asyncio.get_running_loop().create_future()
        self.pending[self.req_id] = fut
        try:
            await self.ws.send(json.dumps(msg))
            return await fut
        except Exception:
            self.pending.pop(msg['req_id'], None)
            raise

    def _calculate_confidence(self, signal: str) -> int:
        if signal == TradeSignal.NEUTRAL:
            return 0
        current_price = self.price_closes[-1] if self.price_closes else 0
        score = 50

        if signal == TradeSignal.BUY and self.nearest_support:
            dist_pct = abs(current_price - self.nearest_support) / current_price
            if dist_pct < 0.005:
                score += 20
            elif dist_pct < 0.01:
                score += 10
        elif signal == TradeSignal.SELL and self.nearest_resistance:
            dist_pct = abs(self.nearest_resistance - current_price) / current_price
            if dist_pct < 0.005:
                score += 20
            elif dist_pct < 0.01:
                score += 10

        if self.trendline_slope is not None:
            if (signal == TradeSignal.BUY and self.trendline_slope > 0) or (signal == TradeSignal.SELL and self.trendline_slope < 0):
                score += 15
            else:
                score -= 5

        if signal == TradeSignal.BUY and self.rsi < 40:
            score += 15
        elif signal == TradeSignal.SELL and self.rsi > 60:
            score += 15
        elif signal == TradeSignal.BUY and self.rsi > 60:
            score -= 5
        elif signal == TradeSignal.SELL and self.rsi < 40:
            score -= 5

        if (signal == TradeSignal.BUY and self.ma_cross == 1) or (signal == TradeSignal.SELL and self.ma_cross == -1):
            score += 10
        elif (signal == TradeSignal.BUY and self.ma_cross == -1) or (signal == TradeSignal.SELL and self.ma_cross == 1):
            score -= 5

        return max(0, min(100, score))

    async def _check_digit_strategy_entry(self, current_digit: int, strategy: str) -> Optional[str]:
        stats = self.digit_analyzer.digits
        if strategy == "OVER":
            weak_digits = [d for d in range(4) if stats[d].color in ['red', 'yellow'] and stats[d].percentage < 10.0]
            if weak_digits:
                target = min(weak_digits, key=lambda d: stats[d].percentage)
                if 'step1_hit' not in self.digit_trigger_state:
                    if current_digit == target:
                        self.digit_trigger_state['step1_hit'] = True
                        self.digit_trigger_state['ticks_waited'] = 0
                        self.log_message(f"OVER Step 1: Pointer hit target digit {target}")
                else:
                    self.digit_trigger_state['ticks_waited'] += 1
                    if self.digit_trigger_state['ticks_waited'] > 3:
                        self.digit_setup_active = None
                        self.digit_trigger_state.clear()
                        self.log_message("OVER: Timeout")
                    elif current_digit in [4,5,6,7,8,9]:
                        self.digit_setup_active = None
                        self.digit_trigger_state.clear()
                        return TradeSignal.OVER
        elif strategy == "UNDER":
            weak_digits = [d for d in [6,7,8,9] if stats[d].color in ['red', 'yellow'] and stats[d].percentage < 10.0]
            if weak_digits:
                target = min(weak_digits, key=lambda d: stats[d].percentage)
                if 'step1_hit' not in self.digit_trigger_state:
                    if current_digit == target:
                        self.digit_trigger_state['step1_hit'] = True
                        self.digit_trigger_state['ticks_waited'] = 0
                        self.log_message(f"UNDER Step 1: Pointer hit target digit {target}")
                else:
                    self.digit_trigger_state['ticks_waited'] += 1
                    if self.digit_trigger_state['ticks_waited'] > 3:
                        self.digit_setup_active = None
                        self.digit_trigger_state.clear()
                        self.log_message("UNDER: Timeout")
                    elif current_digit in [0,1,2,3,4]:
                        self.digit_setup_active = None
                        self.digit_trigger_state.clear()
                        return TradeSignal.UNDER
        elif strategy == "EVEN":
            weak_digits = [d for d in [1,3,5,7,9] if stats[d].color in ['red', 'yellow'] and stats[d].percentage <= 9.5]
            if weak_digits:
                target = min(weak_digits, key=lambda d: stats[d].percentage)
                if 'step1_hit' not in self.digit_trigger_state:
                    if current_digit == target:
                        self.digit_trigger_state['step1_hit'] = True
                        self.digit_trigger_state['ticks_waited'] = 0
                else:
                    self.digit_trigger_state['ticks_waited'] += 1
                    if self.digit_trigger_state['ticks_waited'] > 3:
                        self.digit_setup_active = None
                        self.digit_trigger_state.clear()
                    elif current_digit in [0,2,4,6,8]:
                        self.digit_setup_active = None
                        self.digit_trigger_state.clear()
                        return TradeSignal.EVEN
        elif strategy == "ODD":
            weak_digits = [d for d in [0,2,4,6,8] if stats[d].color in ['red', 'yellow'] and stats[d].percentage <= 9.5]
            if weak_digits:
                target = min(weak_digits, key=lambda d: stats[d].percentage)
                if 'step1_hit' not in self.digit_trigger_state:
                    if current_digit == target:
                        self.digit_trigger_state['step1_hit'] = True
                        self.digit_trigger_state['ticks_waited'] = 0
                        self.digit_trigger_state['consecutive_odds'] = 0
                else:
                    self.digit_trigger_state['ticks_waited'] += 1
                    if self.digit_trigger_state['ticks_waited'] > 5:
                        self.digit_setup_active = None
                        self.digit_trigger_state.clear()
                    elif current_digit in [1,3,5,7,9]:
                        self.digit_trigger_state['consecutive_odds'] = self.digit_trigger_state.get('consecutive_odds', 0) + 1
                        if self.digit_trigger_state['consecutive_odds'] >= 2:
                            self.digit_setup_active = None
                            self.digit_trigger_state.clear()
                            return TradeSignal.ODD
                    else:
                        self.digit_trigger_state['consecutive_odds'] = 0
        return None

    async def _send_pings(self):
        """Send a manual ping every 10 seconds to keep connection alive (fallback)."""
        while self.ws and not self.ws.closed:
            await asyncio.sleep(10)
            try:
                await self._send({"ping": 1})
                self.log_message("Sent manual ping", "DEBUG")
            except Exception as e:
                self.log_message(f"Ping failed: {e}", "WARN")
                break

    # Background refresh disabled to avoid rate limits – we refresh after each trade instead
    async def _refresh_trade_history(self):
        """Placeholder – not used. We use refresh_trade_history_once after trades."""
        pass

    async def refresh_trade_history_once(self):
        """Fetch trade history once and update the UI."""
        await self.get_trade_history(limit=50)

    async def _delayed_refresh(self, delay_seconds: int):
        """Wait and then refresh trade history once."""
        await asyncio.sleep(delay_seconds)
        await self.refresh_trade_history_once()

    async def _message_loop(self):
        try:
            async for raw in self.ws:
                try:
                    data = json.loads(raw)
                except:
                    continue

                if 'req_id' in data and data['req_id'] in self.pending:
                    fut = self.pending.pop(data['req_id'])
                    if not fut.done():
                        fut.set_result(data)

                elif 'tick' in data:
                    tick = data['tick']
                    price = float(tick['quote'])
                    self.digit_analyzer.add_tick(price)
                    current_digit = self.digit_analyzer.get_last_digit()
                    if current_digit is not None:
                        self.tick_history_digits.append(current_digit)
                        if len(self.tick_history_digits) > 20:
                            self.tick_history_digits.pop(0)

                        if self.digit_stats_callback:
                            stats_copy = {d: (self.digit_analyzer.digits[d].percentage, self.digit_analyzer.digits[d].color) for d in range(10)}
                            self.digit_stats_callback(stats_copy)

                        if self.adaptive_mode:
                            now = time.time()
                            if now - self.last_strategy_check >= 2:
                                self.last_strategy_check = now
                                best = StrategySignals.get_best_strategy(self.digit_analyzer)
                                if best != TradeSignal.NEUTRAL and best != self.config.selected_strategy:
                                    self.config.selected_strategy = best
                                    self.digit_setup_active = best
                                    self.digit_trigger_state.clear()
                                    if self.strategy_update_callback:
                                        self.strategy_update_callback(best)
                                    self.log_message(f"🔄 Adaptive switch to: {best}")

                        active_strategy = self.config.selected_strategy
                        if active_strategy in ["Over 1-3", "Under 6-8", "Even", "Odd"]:
                            strategy_code = {"Over 1-3": "OVER", "Under 6-8": "UNDER"}.get(active_strategy, active_strategy.upper())
                            if len(self.tick_history_digits) % 10 == 0:
                                if strategy_code in ["OVER", "UNDER"]:
                                    setup_signal, _ = StrategySignals.over_under_signal(self.digit_analyzer)
                                else:
                                    setup_signal, _ = StrategySignals.even_odd_signal(self.digit_analyzer)
                                if setup_signal != TradeSignal.NEUTRAL:
                                    self.digit_setup_active = setup_signal
                                    self.log_message(f"{setup_signal} Setup Detected")
                                    if self.signal_callback:
                                        self.signal_callback(f"{setup_signal} SETUP")
                            trade_signal = await self._check_digit_strategy_entry(current_digit, strategy_code)
                            if trade_signal:
                                if self.signal_callback:
                                    self.signal_callback(trade_signal)
                                self.log_message(f"🎯 SIGNAL: {trade_signal}")
                                if self.auto_trade:
                                    now = time.time()
                                    if now - self.last_trade_time >= self.config.cooldown:
                                        win_rate = self._digit_win_rate(trade_signal)
                                        min_confidence = self._minimum_trade_confidence()
                                        if win_rate >= min_confidence:
                                            await self.signal_queue.put(trade_signal)
                                            self.log_message(
                                                f"✅ Signal queued for trading: {trade_signal} "
                                                f"(win-rate {win_rate:.1f}% >= {min_confidence:.1f}%)"
                                            )
                                        else:
                                            self.log_message(
                                                f"⚠️ Signal skipped: {trade_signal} win-rate {win_rate:.1f}% "
                                                f"below minimum {min_confidence:.1f}%"
                                            )
                                    else:
                                        self.log_message(f"Signal suppressed by cooldown", "DEBUG")

                elif 'ohlc' in data and self.config.selected_strategy == "ICT/SMS":
                    ohlc = data['ohlc']
                    candle_minute = int(ohlc['epoch']) // 60
                    if self._last_candle_minute is None or candle_minute != self._last_candle_minute:
                        self._last_candle_minute = candle_minute
                        candle = {'open': ohlc['open'], 'high': ohlc['high'],
                                  'low': ohlc['low'], 'close': ohlc['close']}
                        self.indicator.update(float(candle['open']), float(candle['high']),
                                              float(candle['low']), float(candle['close']), 0)
                        self.price_highs.append(float(ohlc['high']))
                        self.price_lows.append(float(ohlc['low']))
                        self.price_closes.append(float(ohlc['close']))
                        if len(self.price_highs) > 200:
                            self.price_highs.pop(0)
                            self.price_lows.pop(0)
                            self.price_closes.pop(0)

                        if len(self.price_closes) >= 30 and len(self.price_closes) % 10 == 0:
                            analyzer = MarketAnalyzer(self.price_closes, self.price_highs, self.price_lows, lookback=100)
                            levels = analyzer.find_support_resistance()
                            current_price = self.price_closes[-1]
                            self.nearest_support = None
                            self.nearest_resistance = None
                            for lvl in levels:
                                if lvl.type == 'support' and lvl.price < current_price:
                                    if self.nearest_support is None or lvl.price > self.nearest_support:
                                        self.nearest_support = lvl.price
                                elif lvl.type == 'resistance' and lvl.price > current_price:
                                    if self.nearest_resistance is None or lvl.price < self.nearest_resistance:
                                        self.nearest_resistance = lvl.price
                            slope, _ = analyzer.find_trendline()
                            self.trendline_slope = slope
                            self.rsi = MarketAnalyzer.calculate_rsi(self.price_closes, 14)
                            self.ma_cross = MarketAnalyzer.moving_average_cross(self.price_closes, 5, 10)

                        signal = self.indicator.get_signal_detail().direction
                        confidence = self._calculate_confidence(signal) if signal != TradeSignal.NEUTRAL else 0
                        self.latest_confidence = confidence
                        self.update_confidence_display(confidence)
                        if self.signal_callback:
                            self.signal_callback(signal)
                        if signal != TradeSignal.NEUTRAL:
                            self.log_message(f"📊 ICT/SMS Signal: {signal} (Confidence: {confidence}%)")

                        if self.auto_trade:
                            if signal == self.current_confirmed_signal:
                                pass
                            elif signal == TradeSignal.NEUTRAL:
                                if self.signal_counter > 0 or self.current_confirmed_signal != TradeSignal.NEUTRAL:
                                    self.signal_counter = 0
                                    self.current_confirmed_signal = TradeSignal.NEUTRAL
                            else:
                                if signal == self.last_signal_stored:
                                    self.signal_counter += 1
                                    self.log_message(f"Signal {signal} repeated {self.signal_counter}/{self.config.confirmations_required}")
                                else:
                                    self.signal_counter = 1
                                    self.log_message(f"Signal changed to {signal} – new confirmation counter")
                                    self.current_confirmed_signal = TradeSignal.NEUTRAL
                                self.last_signal_stored = signal
                                if self.signal_counter >= self.config.confirmations_required and self.current_confirmed_signal == TradeSignal.NEUTRAL:
                                    self.current_confirmed_signal = signal
                                    self.signal_counter = 0
                                    self.log_message(f"Signal CONFIRMED: {signal} – ready to trade")

                            if self.current_confirmed_signal != TradeSignal.NEUTRAL and self.current_confirmed_signal == signal:
                                now = time.time()
                                if now - self.last_trade_time >= self.config.cooldown:
                                    min_confidence = self._minimum_trade_confidence()
                                    if self.latest_confidence >= min_confidence:
                                        await self.signal_queue.put(self.current_confirmed_signal)
                                        self.log_message(
                                            f"✅ Signal queued for trading: {self.current_confirmed_signal} "
                                            f"(confidence {self.latest_confidence:.0f}% >= {min_confidence:.0f}%)"
                                        )
                                    else:
                                        self.log_message(
                                            f"⚠️ Confirmed signal skipped: confidence {self.latest_confidence:.0f}% "
                                            f"below minimum {min_confidence:.0f}%"
                                        )
                                else:
                                    self.log_message(f"Confirmed signal suppressed by cooldown", "DEBUG")

                elif 'candles' in data:
                    candles = data['candles']
                    self.log_message(f"Loaded {len(candles)} historical candles")
                    for candle in candles:
                        self.indicator.update(float(candle['open']), float(candle['high']),
                                              float(candle['low']), float(candle['close']), 0)
                    if self.config.selected_strategy == "ICT/SMS":
                        signal = self.indicator.get_signal_detail().direction
                        if signal != TradeSignal.NEUTRAL:
                            self.log_message(f"📊 Initial ICT/SMS Signal: {signal}")
                            if self.signal_callback:
                                self.signal_callback(signal)

                elif 'ping' in data:
                    # Response to our manual ping – ignore
                    pass

                elif 'balance' in data:
                    self.balance = float(data['balance']['balance'])
                    if self.update_balance:
                        self.update_balance(self.balance, self.account_currency)

                elif 'error' in data:
                    self.log_message(f"Server error: {data['error']['message']}", "ERROR")

                elif 'portfolio' in data:
                    positions = []
                    for contract in data['portfolio'].get('contracts', []):
                        pos = {
                            'contract_id': contract['contract_id'],
                            'buy_price': float(contract['buy_price']),
                            'sell_price': float(contract.get('sell_price', 0)),
                            'current_price': float(contract.get('current_price', 0)),
                            'payout': float(contract.get('payout', 0)),
                            'profit_loss': float(contract.get('profit_loss', 0)),
                            'contract_type': contract.get('contract_type', ''),
                            'status': contract.get('status', 'open'),
                            'expiry_time': contract.get('expiry_time', 0),
                            'entry_tick': contract.get('entry_tick', 0),
                            'entry_time': contract.get('entry_time', 0),
                        }
                        positions.append(pos)
                    self.open_positions = positions
                    if self.positions_callback:
                        self.positions_callback(positions)

        except asyncio.CancelledError:
            self._fail_pending(asyncio.CancelledError())
            self.log_message("Message loop cancelled")
            raise
        except (OSError, asyncio.TimeoutError, websockets.ConnectionClosedError) as e:
            self._fail_pending(e)
            self.log_message(f"WebSocket error: {e}, reconnecting...", "WARN")
            raise   # Let run_bot handle reconnection
        except Exception as e:
            self._fail_pending(e)
            self.log_message(f"Message loop error: {e}", "ERROR")
        finally:
            if self._ping_task:
                self._ping_task.cancel()
            if self._trade_history_task:
                self._trade_history_task.cancel()
            if self.ws:
                with contextlib.suppress(Exception):
                    if self._is_ws_open():
                        await self.ws.close()
                with contextlib.suppress(Exception):
                    await self.ws.wait_closed()
                self.ws = None

    async def _trade_executor(self):
        while self.running:
            try:
                signal = await asyncio.wait_for(self.signal_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            try:
                await self._place_trade(signal)
            except Exception as e:
                self.log_message(f"Trade error: {e}", "ERROR")

    async def _place_trade(self, signal: str):
        if not self.auto_trade:
            return
        if self.config.max_daily_loss > 0 and self.daily_pnl <= -self.config.max_daily_loss:
            self.log_message("Daily loss limit reached", "WARN")
            return

        contract_map = {
            TradeSignal.BUY: "CALL",
            TradeSignal.SELL: "PUT",
            TradeSignal.OVER: "DIGITOVER",
            TradeSignal.UNDER: "DIGITUNDER",
            TradeSignal.EVEN: "DIGITEVEN",
            TradeSignal.ODD: "DIGITODD"
        }
        contract_type = contract_map.get(signal, "CALL")

        stake = round(self.current_stake, 2)
        if stake < 1.0:
            stake = self.config.base_stake
            self.current_stake = self.config.base_stake
            self.consecutive = 0
        if stake > self.balance:
            stake = math.floor(self.balance * 100) / 100
            if stake < 1.0:
                self.log_message("Insufficient balance", "ERROR")
                return

        if self.config.selected_strategy in ["Over 1-3", "Under 6-8", "Even", "Odd"]:
            duration_unit = "t"
            duration_value = self._choose_tick_duration(signal)
        else:
            duration_unit = "m"
            duration_value = self.config.duration

        self.log_message(f"Placing {signal} stake {stake:.2f} for {duration_value}{duration_unit} (level {self.consecutive})")
        if self.update_stake:
            self.update_stake(stake, self.consecutive)

        proposal_msg = {
            "proposal": 1,
            "amount": stake,
            "basis": "stake",
            "contract_type": contract_type,
            "currency": self.account_currency,
            "duration": duration_value,
            "duration_unit": duration_unit,
            "symbol": self.config.symbol
        }
        if contract_type in ["DIGITOVER", "DIGITUNDER"]:
            proposal_msg["barrier"] = "3" if signal == TradeSignal.OVER else "6"

        prop = await self._send(proposal_msg)
        if 'error' in prop:
            self.log_message(f"Proposal error: {prop['error']['message']}", "ERROR")
            return
        contract_id = prop['proposal']['id']
        ask_price = prop['proposal']['ask_price']
        buy = await self._send({"buy": contract_id, "price": ask_price})
        if 'error' in buy:
            self.log_message(f"Buy error: {buy['error']['message']}", "ERROR")
            return
        trade_id = buy['buy']['contract_id']
        self.log_message(f"Trade opened: {signal} {trade_id}")
        self.last_trade_time = time.time()

        # --- Play beep sound ---
        try:
            if platform.system() == 'Windows':
                import winsound
                winsound.Beep(1000, 200)   # 1000 Hz, 200 ms
            else:
                # For macOS/Linux – simple console bell
                print('\a', end='', flush=True)
        except Exception as e:
            self.log_message(f"Beep error: {e}", "DEBUG")

        # Wait for contract to finish
        if duration_unit == "t":
            wait_seconds = duration_value * 2 + 30
        else:
            wait_seconds = duration_value * 60 + 45
        self.log_message(f"Waiting {wait_seconds}s for contract to finish...")
        await asyncio.sleep(wait_seconds)

        # Poll profit_table every 10 seconds (slower to avoid rate limits)
        profit = 0.0
        found = False
        for attempt in range(15):  # 15 * 10 = 150 seconds
            profit_table = await self._send({"profit_table": 1, "limit": 20})
            if 'error' in profit_table:
                self.log_message(f"Profit table error: {profit_table['error']['message']}", "WARN")
            elif 'profit_table' in profit_table and 'transactions' in profit_table['profit_table']:
                for txn in profit_table['profit_table']['transactions']:
                    if txn.get('contract_id') == trade_id:
                        sell_price = float(txn.get('sell_price', 0) or 0)
                        buy_price = float(txn.get('buy_price', stake) or stake)
                        profit_value = txn.get('profit_loss')
                        profit = self._resolve_profit_loss(buy_price, sell_price, profit_value)
                        found = True

                        if found:
                            self.log_message(f"Trade result from profit_table: {signal} {trade_id} profit={profit:.2f}")
                            break
                if found:
                    break
            await asyncio.sleep(10)  # wait 10 seconds between polls
        else:
            # Fallback: try portfolio (if contract still open)
            port = await self._send({"portfolio": 1, "contract_id": trade_id})
            if 'portfolio' in port and port['portfolio'].get('contracts'):
                contract = port['portfolio']['contracts'][0]
                sell_price = float(contract.get('sell_price', 0))
                buy_price = float(contract.get('buy_price', stake) or stake)
                profit = self._resolve_profit_loss(buy_price, sell_price, contract.get('profit_loss'))
                self.log_message(f"Trade result from portfolio (fallback): {signal} {trade_id} profit={profit:.2f}")
            else:
                self.log_message(f"Could not retrieve profit for {trade_id}, assuming loss", "ERROR")
                profit = -stake

        self.daily_pnl += profit
        self.log_message(f"Daily P&L: {self.daily_pnl:.2f}")

        # Update balance
        bal = await self._send({"balance": 1})
        if 'balance' in bal:
            self.balance = float(bal['balance']['balance'])
            if self.update_balance:
                self.update_balance(self.balance, self.account_currency)

        # If a manual reset was requested, ignore this trade result and do NOT update martingale
        if self.ignore_next_result:
            self.log_message("Ignoring trade result due to manual reset.")
            self.ignore_next_result = False
            if self.update_stake:
                self.update_stake(self.current_stake, self.consecutive)
            # Refresh trade history in the UI once
            asyncio.create_task(self.refresh_trade_history_once())
            await self._send({"portfolio": 1, "subscribe": 1})
            return

        self._update_martingale_after_trade(profit)

        if self.update_stake:
            self.update_stake(self.current_stake, self.consecutive)

        # Refresh trade history in the UI once
        asyncio.create_task(self.refresh_trade_history_once())

        await self._send({"portfolio": 1, "subscribe": 1})

    async def get_open_positions(self):
        resp = await self._send({"portfolio": 1, "subscribe": 1})
        if 'portfolio' in resp:
            return resp['portfolio'].get('contracts', [])
        return []

    async def close_position(self, contract_id: int):
        sell = await self._send({"sell": contract_id})
        if 'error' in sell:
            self.log_message(f"Close error for {contract_id}: {sell['error']['message']}", "ERROR")
            return False
        self.log_message(f"Position {contract_id} closed successfully")
        await self._send({"portfolio": 1, "subscribe": 1})
        return True

    async def get_trade_history(self, limit=50):
        """Retrieve contract-style history that looks closer to Deriv's website report."""
        statement_resp = await self._send({
            "statement": 1,
            "limit": max(limit * 4, 100),
            "description": 1
        })
        if 'statement' in statement_resp and 'transactions' in statement_resp['statement']:
            rows = self._build_trade_history_from_statement(
                statement_resp['statement']['transactions'],
                limit
            )
            if rows:
                if self.trade_history_callback:
                    self.trade_history_callback(rows)
                return rows
            self.log_message("Statement history returned no contracts, falling back to profit_table", "WARN")
        elif 'error' in statement_resp:
            self.log_message(f"Statement history error: {statement_resp['error']['message']}", "WARN")

        resp = await self._send({"profit_table": 1, "limit": limit})
        if 'error' in resp:
            self.log_message(f"Profit table error: {resp['error']['message']}", "ERROR")
            return []
        if 'profit_table' in resp and 'transactions' in resp['profit_table']:
            rows = []
            for txn in resp['profit_table']['transactions']:
                contract_id = txn.get('contract_id')
                contract_type = txn.get('contract_type')
                buy_price, sell_price, payout = self._extract_trade_amounts(txn)
                profit_loss = self._resolve_history_profit_loss(txn)
                display_sell_price = sell_price if sell_price > 0 else payout
                rows.append({
                    'type': contract_type or '',
                    'contract_type': contract_type or '',
                    'ref_id': contract_id,
                    'contract_id': contract_id,
                    'currency': self.account_currency,
                    'buy_time': self._format_report_time(txn.get('start_time', 0)),
                    'start_time': self._format_report_time(txn.get('start_time', 0)),
                    'stake': buy_price,
                    'buy_price': buy_price,
                    'sell_time': self._format_report_time(txn.get('end_time', txn.get('start_time', 0))),
                    'end_time': self._format_report_time(txn.get('end_time', txn.get('start_time', 0))),
                    'contract_value': display_sell_price,
                    'payout': display_sell_price,
                    'sell_price': display_sell_price,
                    'profit_loss': profit_loss,
                    '_sort_ts': int(self._safe_float(txn.get('end_time', txn.get('start_time', 0)), 0)),
                })
            rows.sort(key=lambda row: row.get('_sort_ts', 0), reverse=True)
            if self.trade_history_callback:
                self.trade_history_callback(rows)
            return rows
        else:
            if self.trade_history_callback:
                self.trade_history_callback([])
            return []

    async def manual_trade_generic(self, contract_type: str, stake: float, duration_value: int, duration_unit: str, barrier: str = None):
        proposal_msg = {
            "proposal": 1,
            "amount": stake,
            "basis": "stake",
            "contract_type": contract_type,
            "currency": self.account_currency,
            "duration": duration_value,
            "duration_unit": duration_unit,
            "symbol": self.config.symbol
        }
        if barrier:
            proposal_msg["barrier"] = barrier
        self.log_message(f"Manual trade: {contract_type} stake {stake:.2f}")
        try:
            prop = await self._send(proposal_msg)
            if 'error' in prop:
                self.log_message(f"Manual proposal error: {prop['error']['message']}", "ERROR")
                return
            contract_id = prop['proposal']['id']
            ask_price = prop['proposal']['ask_price']
            buy = await self._send({"buy": contract_id, "price": ask_price})
            if 'error' in buy:
                self.log_message(f"Manual buy error: {buy['error']['message']}", "ERROR")
                return
            trade_id = buy['buy']['contract_id']
            self.log_message(f"Manual trade opened: {trade_id}")
            
            # --- Play beep sound for manual trade as well ---
            try:
                if platform.system() == 'Windows':
                    import winsound
                    winsound.Beep(1000, 200)
                else:
                    print('\a', end='', flush=True)
            except Exception:
                pass

            await self._send({"portfolio": 1, "subscribe": 1})

            # Schedule a refresh of trade history after 10 seconds (to let the trade settle)
            asyncio.create_task(self._delayed_refresh(10))
        except Exception as e:
            self.log_message(f"Manual trade exception: {e}", "ERROR")

    async def _connect_and_setup(self) -> bool:
        url = f"wss://ws.binaryws.com/websockets/v3?app_id={self.app_id}"
        try:
            self.ws = await websockets.connect(
                url,
                ping_interval=None,        # Use API-level ping requests instead of protocol pings
                ping_timeout=None,
                close_timeout=10,
                max_size=2**23,
                open_timeout=30
            )
            self.log_message("WebSocket connected")
            self._message_loop_task = asyncio.create_task(self._message_loop())
            self._ping_task = asyncio.create_task(self._send_pings())
            # Disabled background refresh to avoid rate limits – we refresh after each trade
            # self._trade_history_task = asyncio.create_task(self._refresh_trade_history())

            auth = await self._send({"authorize": self.token})
            if 'error' in auth:
                self.log_message(f"Auth failed: {auth['error']['message']}", "ERROR")
                return False
            self.log_message(f"Authorized as {auth['authorize']['loginid']}")

            bal = await self._send({"balance": 1, "subscribe": 1})
            if 'balance' in bal:
                self.balance = float(bal['balance']['balance'])
                self.account_currency = bal['balance']['currency']
                if self.update_balance:
                    self.update_balance(self.balance, self.account_currency)

            await self._send({"portfolio": 1, "subscribe": 1})

            if self.config.selected_strategy in ["Over 1-3", "Under 6-8", "Even", "Odd"]:
                tick_sub = await self._send({"ticks": self.config.symbol, "subscribe": 1})
                if 'error' in tick_sub:
                    self.log_message(f"Tick subscription failed: {tick_sub['error']['message']}", "ERROR")
                    return False
                self.log_message(f"Subscribed to {self.config.symbol} ticks")
            else:
                granularity = self.config.granularity_seconds
                sub = await self._send({
                    "ticks_history": self.config.symbol,
                    "granularity": granularity,
                    "style": "candles",
                    "subscribe": 1,
                    "count": 100,
                    "end": "latest"
                })
                if 'error' in sub:
                    self.log_message(f"Candle subscription failed: {sub['error']['message']}", "ERROR")
                    return False
                self.log_message(f"Subscribed to {self.config.symbol} {granularity}s candles")

            self._reconnect_attempts = 0
            return True
        except Exception as e:
            self.log_message(f"Connection error: {e}", "ERROR")
            return False

    async def _connect_and_setup_render(self) -> bool:
        configured_url = (os.getenv("DERIV_WS_URL") or "").strip()
        endpoints = []
        if configured_url:
            endpoints.append(configured_url)
        endpoints.append(f"wss://ws.derivws.com/websockets/v3?app_id={self.app_id}")
        endpoints.append(f"wss://ws.binaryws.com/websockets/v3?app_id={self.app_id}")

        unique_endpoints = []
        seen = set()
        for endpoint in endpoints:
            if endpoint and endpoint not in seen:
                unique_endpoints.append(endpoint)
                seen.add(endpoint)

        last_error = None
        for url in unique_endpoints:
            try:
                self.ws = await websockets.connect(
                    url,
                    ping_interval=None,
                    ping_timeout=None,
                    close_timeout=10,
                    max_size=2**23,
                    open_timeout=30
                )
                self.log_message(f"WebSocket connected ({url})")
                self._message_loop_task = asyncio.create_task(self._message_loop())
                self._ping_task = asyncio.create_task(self._send_pings())

                auth = await self._send({"authorize": self.token})
                if 'error' in auth:
                    self.log_message(f"Auth failed: {auth['error']['message']}", "ERROR")
                    return False
                self.log_message(f"Authorized as {auth['authorize']['loginid']}")

                bal = await self._send({"balance": 1, "subscribe": 1})
                if 'balance' in bal:
                    self.balance = float(bal['balance']['balance'])
                    self.account_currency = bal['balance']['currency']
                    if self.update_balance:
                        self.update_balance(self.balance, self.account_currency)

                await self._send({"portfolio": 1, "subscribe": 1})

                if self.config.selected_strategy in ["Over 1-3", "Under 6-8", "Even", "Odd"]:
                    tick_sub = await self._send({"ticks": self.config.symbol, "subscribe": 1})
                    if 'error' in tick_sub:
                        self.log_message(f"Tick subscription failed: {tick_sub['error']['message']}", "ERROR")
                        return False
                    self.log_message(f"Subscribed to {self.config.symbol} ticks")
                else:
                    granularity = self.config.granularity_seconds
                    sub = await self._send({
                        "ticks_history": self.config.symbol,
                        "granularity": granularity,
                        "style": "candles",
                        "subscribe": 1,
                        "count": 100,
                        "end": "latest"
                    })
                    if 'error' in sub:
                        self.log_message(f"Candle subscription failed: {sub['error']['message']}", "ERROR")
                        return False
                    self.log_message(f"Subscribed to {self.config.symbol} {granularity}s candles")

                self._reconnect_attempts = 0
                return True
            except Exception as e:
                last_error = e
                self.log_message(f"Connection attempt failed ({url}): {e}", "WARN")
                if self.ws:
                    with contextlib.suppress(Exception):
                        if self._is_ws_open():
                            await self.ws.close()
                    with contextlib.suppress(Exception):
                        await self.ws.wait_closed()
                    self.ws = None
                if self._message_loop_task:
                    self._message_loop_task.cancel()
                    self._message_loop_task = None
                if self._ping_task:
                    self._ping_task.cancel()
                    self._ping_task = None

        self.log_message(f"Connection error: {last_error}", "ERROR")
        return False

    async def run_bot(self):
        self.running = True
        while self.running:
            connected = await self._connect_and_setup_render()
            if not connected:
                self._reconnect_attempts += 1
                wait = min(60, 5 * self._reconnect_attempts)
                self.log_message(f"Connection failed. Reconnecting in {wait}s...", "WARN")
                await asyncio.sleep(wait)
                continue

            self._trade_executor_task = asyncio.create_task(self._trade_executor())

            try:
                await self._message_loop_task
            except asyncio.CancelledError:
                self.log_message("Message loop cancelled, stopping bot")
                break
            except (OSError, asyncio.TimeoutError, websockets.ConnectionClosedError) as e:
                self.log_message(f"Connection lost: {e}, reconnecting...")
                # Loop will reconnect after the finally block
            except Exception as e:
                self.log_message(f"Message loop ended with exception: {e}", "WARN")
            finally:
                if self._trade_executor_task:
                    self._trade_executor_task.cancel()
                    try:
                        await self._trade_executor_task
                    except asyncio.CancelledError:
                        pass
                self._message_loop_task = None
                self._trade_executor_task = None

            if not self.running:
                break

            self._reconnect_attempts += 1
            wait = min(60, 5 * self._reconnect_attempts)
            self.log_message(f"Disconnected. Reconnecting in {wait}s...", "WARN")
            await asyncio.sleep(wait)

    async def stop(self):
        self.running = False
        self._fail_pending(asyncio.CancelledError())
        if self._message_loop_task:
            self._message_loop_task.cancel()
        if self._trade_executor_task:
            self._trade_executor_task.cancel()
        if self._ping_task:
            self._ping_task.cancel()
        if self._trade_history_task:
            self._trade_history_task.cancel()
        if self.ws:
            with contextlib.suppress(Exception):
                if self._is_ws_open():
                    await self.ws.close()
            with contextlib.suppress(Exception):
                await self.ws.wait_closed()
            self.ws = None
        self.consecutive = 0
        self.current_stake = self.config.base_stake
        if self.update_stake:
            self.update_stake(self.current_stake, self.consecutive)
        self.log_message("Bot stopped – martingale reset")
