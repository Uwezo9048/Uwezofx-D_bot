# modules/trading/bot.py
import asyncio
import json
import math
import time
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
        self.app_id = Settings.DERIV_APP_ID
        self.log = log_callback or print
        self.update_balance = balance_callback
        self.update_stake = stake_callback
        self.signal_callback = signal_callback
        self.confidence_callback = confidence_callback
        self.digit_stats_callback = digit_stats_callback
        self.strategy_update_callback = strategy_update_callback
        self.positions_callback = positions_callback
        self.trade_history_callback = trade_history_callback

        # WebSocket and async state
        self.ws = None
        self.req_id = 0
        self.pending = {}
        self._loop = None

        # Trading state
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
        self._last_candle_minute = None
        self.consecutive = 0
        self.current_stake = config.base_stake
        self._reconnect_attempts = 0

        # Price history for analysis
        self.price_highs = []
        self.price_lows = []
        self.price_closes = []
        self.nearest_support = None
        self.nearest_resistance = None
        self.trendline_slope = None
        self.rsi = 50.0
        self.ma_cross = 0

        # Signal confirmation
        self.signal_counter = 0
        self.current_confirmed_signal = TradeSignal.NEUTRAL
        self.last_signal_stored = TradeSignal.NEUTRAL

        # Digit strategy tracking
        self.digit_setup_active = None
        self.digit_trigger_state = {}
        self.tick_history_digits = []
        self.last_strategy_check = 0

        # Mode flags
        self.auto_trade = False
        self.adaptive_mode = False

        # Open positions tracking
        self.open_positions = []

        self._ping_task = None

    def set_event_loop(self, loop):
        self._loop = loop

    def set_mode(self, mode: str):
        self.auto_trade = mode in ["Auto-Trade", "Adaptive"]
        self.adaptive_mode = (mode == "Adaptive")
        if self.log:
            self.log_message(f"Mode changed to: {mode} (AutoTrade: {self.auto_trade}, Adaptive: {self.adaptive_mode})")

    def log_message(self, msg, level="INFO"):
        if self.log:
            timestamp = datetime.now().strftime("%H:%M:%S")
            self.log(f"[{timestamp}] {msg}")

    def update_confidence_display(self, confidence):
        if self.confidence_callback:
            self.confidence_callback(confidence)

    async def _send(self, msg):
        self.req_id += 1
        msg['req_id'] = self.req_id
        fut = asyncio.get_event_loop().create_future()
        self.pending[self.req_id] = fut
        await self.ws.send(json.dumps(msg))
        return await fut

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
                                        await self.signal_queue.put(trade_signal)
                                        self.log_message(f"✅ Signal queued for trading: {trade_signal}")
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
                                    await self.signal_queue.put(self.current_confirmed_signal)
                                    self.log_message(f"✅ Signal queued for trading: {self.current_confirmed_signal}")
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
                    await self._send({"pong": data['ping']})

                elif 'balance' in data:
                    self.balance = float(data['balance']['balance'])
                    if self.update_balance:
                        self.update_balance(self.balance, self.account_currency)

                elif 'error' in data:
                    self.log_message(f"Server error: {data['error']['message']}", "ERROR")

                elif 'ping' in data:
                    # Response to our manual ping – ignore
                    pass

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
            self.log_message("Message loop cancelled")
            raise
        except websockets.ConnectionClosedError as e:
            self.log_message(f"WebSocket connection closed (keepalive timeout?): {e}", "WARN")
        except Exception as e:
            self.log_message(f"Message loop error: {e}", "ERROR")
        finally:
            if self._ping_task:
                self._ping_task.cancel()

            if self.ws:
                await self.ws.close()

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
            duration_value = self.config.ticks_duration
        else:
            duration_unit = "m"
            duration_value = self.config.duration

        self.log_message(f"Placing {signal} stake {stake:.2f} (level {self.consecutive})")
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

        # Wait for contract to finish – add generous buffer
        if duration_unit == "t":
            wait_seconds = duration_value * 3 + 10   # extra buffer for tick contracts
        else:
            wait_seconds = duration_value * 60 + 30  # extra buffer for minute contracts
        await asyncio.sleep(wait_seconds)

        # Retrieve contract details from portfolio (most reliable)
        profit = 0.0
        port = await self._send({"portfolio": 1, "contract_id": trade_id})
        if 'portfolio' in port and port['portfolio'].get('contracts'):
            contract = port['portfolio']['contracts'][0]
            sell_price = float(contract.get('sell_price', 0))
            buy_price = float(contract.get('buy_price', 0))
            profit = sell_price - buy_price
            self.log_message(f"Trade result: {signal} {trade_id} profit={profit:.2f} (sell_price={sell_price}, buy_price={buy_price})")
        else:
            self.log_message(f"Could not retrieve contract {trade_id} from portfolio – using fallback", "WARN")
            # Fallback: try profit_table
            for attempt in range(6):
                profit_resp = await self._send({"profit_table": 1, "limit": 1, "contract_id": trade_id})
                if 'profit_table' in profit_resp and profit_resp['profit_table'].get('transactions'):
                    txn = profit_resp['profit_table']['transactions'][0]
                    profit = float(txn.get('profit_loss', 0))
                    self.log_message(f"Fallback profit from profit_table: {profit:.2f}")
                    break
                await asyncio.sleep(2)
            else:
                self.log_message(f"Could not retrieve profit for {trade_id}", "ERROR")

        self.daily_pnl += profit
        self.log_message(f"Daily P&L: {self.daily_pnl:.2f}")

        # Update balance
        bal = await self._send({"balance": 1})
        if 'balance' in bal:
            self.balance = float(bal['balance']['balance'])
            if self.update_balance:
                self.update_balance(self.balance, self.account_currency)

        # Martingale logic
        if self.config.martingale_mode == "Reverse":
            if profit > 0:
                self.consecutive = 0
                self.current_stake = self.config.base_stake
                self.log_message("Win! Stake reset to base.")
            else:
                self.consecutive += 1
                if self.consecutive <= self.config.max_martingale_steps:
                    self.current_stake *= self.config.martingale_mult
                    self.log_message(f"Loss. Next stake: {self.current_stake:.2f} (level {self.consecutive})")
                else:
                    self.log_message("Max martingale steps reached. Resetting.")
                    self.consecutive = 0
                    self.current_stake = self.config.base_stake
        else:
            if profit > 0:
                self.consecutive = 0
                self.current_stake = self.config.base_stake
                self.log_message("Win! Stake reset.")
            else:
                self.consecutive += 1
                if self.consecutive <= self.config.max_martingale_steps:
                    self.current_stake *= self.config.martingale_mult
                    self.log_message(f"Loss. Next stake: {self.current_stake:.2f} (level {self.consecutive})")
                else:
                    self.log_message("Max martingale steps reached. Resetting.")
                    self.consecutive = 0
                    self.current_stake = self.config.base_stake

        if self.update_stake:
            self.update_stake(self.current_stake, self.consecutive)

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
        """Retrieve recent trade history (closed contracts) using profit_table."""
        resp = await self._send({"profit_table": 1, "limit": limit})
        if 'profit_table' in resp and 'transactions' in resp['profit_table']:
            trades = []
            for txn in resp['profit_table']['transactions']:
                # Use the profit_loss field directly – this is the actual profit/loss from Deriv reports
                profit_loss = float(txn.get('profit_loss', 0))
                trade = {
                    'contract_id': txn.get('contract_id'),
                    'contract_type': txn.get('contract_type'),
                    'buy_price': float(txn.get('buy_price', 0)),
                    'sell_price': float(txn.get('sell_price', 0)),
                    'profit_loss': profit_loss,   # the actual profit/loss
                    'start_time': datetime.fromtimestamp(txn.get('start_time', 0)).strftime('%Y-%m-%d %H:%M:%S'),
                    'end_time': datetime.fromtimestamp(txn.get('end_time', 0)).strftime('%Y-%m-%d %H:%M:%S'),
                }
                trades.append(trade)
            if self.trade_history_callback:
                self.trade_history_callback(trades)
            return trades
        else:
            self.log_message("Could not fetch trade history")
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
            await self._send({"portfolio": 1, "subscribe": 1})
        except Exception as e:
            self.log_message(f"Manual trade exception: {e}", "ERROR")

    async def _send_pings(self):
        """Send a 'ping' request every 30 seconds to keep connection alive."""
        while self.ws and not self.ws.closed:
            await asyncio.sleep(30)
            try:
                await self._send({"ping": 1})
                self.log_message("Sent manual ping", "DEBUG")
            except Exception as e:
                self.log_message(f"Ping failed: {e}", "WARN")
                break

    async def _connect_and_setup(self) -> bool:
        url = f"wss://ws.binaryws.com/websockets/v3?app_id={self.app_id}"
        try:
            self.ws = await websockets.connect(
                url,
                ping_interval=None,      # disable automatic ping
                ping_timeout=None,
                close_timeout=10
            )
            self.log_message("WebSocket connected")
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
            self.log_message(f"Connection error: {e}", "ERROR")
            return False

    async def run_bot(self):
        self.running = True
        while self.running:
            connected = await self._connect_and_setup()
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
            except websockets.ConnectionClosedError as e:
                self.log_message(f"Connection closed: {e}, reconnecting...")
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
        if self.ws:
            await self.ws.close()
        if self._message_loop_task:
            self._message_loop_task.cancel()
        if self._trade_executor_task:
            self._trade_executor_task.cancel()
        if self._ping_task:
            self._ping_task.cancel()
        self.consecutive = 0
        self.current_stake = self.config.base_stake
        if self.update_stake:
            self.update_stake(self.current_stake, self.consecutive)
        self.log_message("Bot stopped – martingale reset")