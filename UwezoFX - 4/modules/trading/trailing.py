# modules/trading/trailing.py
import threading
import time
import MetaTrader5 as mt5
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from config import TradingConfig
from modules.trading.indicator import OrderType, Position, PositionStatus

@dataclass
class TrailingConfig:
    enable_trailing_stop: bool = True
    lock_amount_dollars: float = 3.0
    step_amount_dollars: float = 4.0

class TrailingStopLoss:
    """
    Step trailing stop-loss system.
    For each Step Amount of profit gained, locks an additional Lock Amount
    by moving the stop loss accordingly.
    """

    def __init__(self, config, logger, callback_queue):
        self.config = config
        self.logger = logger
        self.callback_queue = callback_queue
        self.positions: Dict[int, Position] = {}
        self.alert_system = None

        self.trailing_config = TrailingConfig(
            enable_trailing_stop=config.enable_trailing_stop_loss,
            lock_amount_dollars=config.lock_amount_dollars,
            step_amount_dollars=config.step_amount_dollars
        )

        self.performance_metrics = {
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'total_profit': 0.0,
            'max_win': 0.0,
            'max_loss': 0.0,
            'avg_win': 0.0,
            'avg_loss': 0.0,
            'profit_factor': 0.0
        }

        self.callbacks = {
            'on_position_closed': None,
            'on_stop_loss_triggered': None,
            'on_take_profit_triggered': None,
            'on_config_updated': None
        }

        self.position_lock = threading.RLock()

        self.logger.info("=" * 60)
        self.logger.info("STEP TRAILING STOP-LOSS SYSTEM INITIALIZED")
        self.logger.info(f"Enabled: {self.trailing_config.enable_trailing_stop}")
        self.logger.info(f"Lock Amount: ${self.trailing_config.lock_amount_dollars}")
        self.logger.info(f"Step Amount: ${self.trailing_config.step_amount_dollars}")
        self.logger.info("=" * 60)

    def set_callback(self, event: str, callback: Callable):
        if event in self.callbacks:
            self.callbacks[event] = callback

    def set_alert_system(self, alert_system):
        self.alert_system = alert_system

    def get_point_value(self, symbol: str) -> float:
        try:
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info:
                tick_value = symbol_info.trade_tick_value
                tick_size = symbol_info.trade_tick_size
                point_size = 10 * tick_size
                point_value = tick_value * (point_size / tick_size)
                return point_value
        except Exception as e:
            self.logger.error(f"Error calculating point value for {symbol}: {e}")

        if 'XAU' in symbol or 'GOLD' in symbol:
            return 0.10
        elif 'JPY' in symbol:
            return 0.01
        else:
            return 0.01

    def add_position(self, ticket: int, symbol: str, order_type: OrderType,
                    volume: float, entry_price: float, stop_loss: float,
                    take_profit: float, comment: str = "") -> bool:
        with self.position_lock:
            try:
                tick = mt5.symbol_info_tick(symbol)
                if not tick:
                    self.logger.error(f"Failed to get tick data for {symbol}")
                    return False

                current_price = tick.ask if order_type == OrderType.LONG else tick.bid

                position = Position(
                    ticket=ticket,
                    symbol=symbol,
                    order_type=order_type,
                    volume=volume,
                    entry_price=entry_price,
                    current_price=current_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    comment=comment,
                    last_locked_profit=0.0,
                    total_locked_profit=0.0,
                    lock_levels=[]
                )

                position.update_current_price(current_price)
                self.positions[ticket] = position

                self.logger.info(f"✅ Added position {ticket} to step trailing management (Total managed: {len(self.positions)})")

                try:
                    self.callback_queue.put_nowait(('trailing_position_added', {
                        'ticket': ticket,
                        'symbol': symbol,
                        'type': order_type.value,
                        'lock_amount': self.trailing_config.lock_amount_dollars,
                        'step_amount': self.trailing_config.step_amount_dollars,
                        'total_managed': len(self.positions)
                    }))
                except:
                    pass

                return True
            except Exception as e:
                self.logger.error(f"Error adding position {ticket}: {e}")
                return False

    def update_position_prices(self):
        """
        Update ALL positions – step trailing logic.
        When profit increases by Step Amount, locks Lock Amount.
        """
        if not self.trailing_config.enable_trailing_stop:
            return

        with self.position_lock:
            tickets = list(self.positions.keys())
            closed_positions = []

            for ticket in tickets:
                position = self.positions.get(ticket)
                if not position or position.status != PositionStatus.OPEN:
                    continue

                try:
                    mt5_position = mt5.positions_get(ticket=ticket)
                    if not mt5_position:
                        position.status = PositionStatus.CLOSED
                        position.exit_time = datetime.now()
                        position.exit_price = position.current_price
                        position.profit = position.mt5_profit
                        closed_positions.append(ticket)

                        was_sl = False
                        was_tp = False
                        if position.order_type == OrderType.LONG:
                            if position.stop_loss and position.exit_price <= position.stop_loss:
                                was_sl = True
                            elif position.take_profit and position.exit_price >= position.take_profit:
                                was_tp = True
                        else:
                            if position.stop_loss and position.exit_price >= position.stop_loss:
                                was_sl = True
                            elif position.take_profit and position.exit_price <= position.take_profit:
                                was_tp = True

                        close_type = "STOP LOSS" if was_sl else "TAKE PROFIT" if was_tp else "MANUAL"
                        self.logger.info(f"Position {ticket} CLOSED - {close_type} - P&L: ${position.profit:.2f}")

                        self.update_performance_metrics(position)

                        if self.alert_system:
                            if was_sl:
                                self.alert_system.alert_stop_loss_hit(position)
                            elif was_tp:
                                self.alert_system.alert_take_profit_hit(position)

                        try:
                            self.callback_queue.put_nowait(('position_closed', {
                                'ticket': ticket,
                                'profit': position.profit,
                                'type': 'stop_loss' if was_sl else 'take_profit' if was_tp else 'manual'
                            }))
                        except:
                            pass

                        if was_sl and self.callbacks['on_stop_loss_triggered']:
                            self.callbacks['on_stop_loss_triggered'](position)
                        elif was_tp and self.callbacks['on_take_profit_triggered']:
                            self.callbacks['on_take_profit_triggered'](position)
                        if self.callbacks['on_position_closed']:
                            self.callbacks['on_position_closed'](position)

                        continue

                    mt5_pos = mt5_position[0]
                    position.mt5_profit = mt5_pos.profit
                    position.current_price = mt5_pos.price_current
                    position.stop_loss = mt5_pos.sl
                    position.take_profit = mt5_pos.tp

                    current_pnl = position.mt5_profit
                    point_value = self.get_point_value(position.symbol)

                    if current_pnl > 0:
                        lock_amount = self.trailing_config.lock_amount_dollars
                        step_amount = self.trailing_config.step_amount_dollars

                        steps = int((current_pnl - position.last_locked_profit) / step_amount + 1e-9)
                        if steps > 0:
                            total_to_lock = steps * lock_amount
                            new_total_locked = position.total_locked_profit + total_to_lock

                            if new_total_locked > current_pnl:
                                new_total_locked = current_pnl
                                total_to_lock = new_total_locked - position.total_locked_profit

                            symbol_info = mt5.symbol_info(position.symbol)
                            if symbol_info:
                                min_stop_points = symbol_info.trade_stops_level
                                point_size = symbol_info.point
                            else:
                                min_stop_points = 10
                                point_size = 0.00001
                            min_distance = min_stop_points * point_size
                            buffer = 0.5 * point_size

                            self.logger.info(f"Position {ticket}: PnL=${current_pnl:.2f}, last_locked=${position.last_locked_profit:.2f}, "
                                            f"steps={steps}, total_to_lock=${total_to_lock:.2f}, new_total_locked=${new_total_locked:.2f}")

                            if position.order_type == OrderType.LONG:
                                new_stop = position.entry_price + (new_total_locked / (position.volume * point_value))

                                if new_stop >= position.current_price - min_distance:
                                    new_stop = position.current_price - min_distance - buffer

                                if new_stop > position.stop_loss:
                                    request = {
                                        "action": mt5.TRADE_ACTION_SLTP,
                                        "symbol": position.symbol,
                                        "position": ticket,
                                        "sl": new_stop,
                                        "tp": position.take_profit,
                                        "magic": self.config.magic_number,
                                        "comment": f"Step lock: +${total_to_lock:.2f}"
                                    }
                                    result = mt5.order_send(request)
                                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                                        old_locked = position.total_locked_profit
                                        position.stop_loss = new_stop
                                        position.total_locked_profit = new_total_locked
                                        position.last_locked_profit = position.last_locked_profit + (steps * step_amount)
                                        position.lock_levels.append(current_pnl)
                                        newly_locked = new_total_locked - old_locked

                                        self.logger.info(f"✅ Position {ticket} STEP LOCK: locked ${newly_locked:.2f} "
                                                        f"(Total locked: ${new_total_locked:.2f}, Profit: ${current_pnl:.2f})")
                                        if self.alert_system:
                                            self.alert_system.alert_profit_locked(position, newly_locked)
                                        try:
                                            self.callback_queue.put_nowait(('profit_locked', {
                                                'ticket': ticket,
                                                'locked_amount': newly_locked,
                                                'total_locked': new_total_locked,
                                                'total_profit': current_pnl,
                                                'new_stop': new_stop
                                            }))
                                        except:
                                            pass
                                    else:
                                        error = result.comment if result else "No result"
                                        retcode = result.retcode if result else "None"
                                        self.logger.error(f"❌ Position {ticket} order failed: {error} (retcode {retcode})")
                                else:
                                    self.logger.info(f"Position {ticket}: new_stop {new_stop:.5f} <= current stop {position.stop_loss:.5f} – skipping")

                            else:
                                new_stop = position.entry_price - (new_total_locked / (position.volume * point_value))

                                if new_stop <= position.current_price + min_distance:
                                    new_stop = position.current_price + min_distance + buffer

                                if new_stop < position.stop_loss:
                                    request = {
                                        "action": mt5.TRADE_ACTION_SLTP,
                                        "symbol": position.symbol,
                                        "position": ticket,
                                        "sl": new_stop,
                                        "tp": position.take_profit,
                                        "magic": self.config.magic_number,
                                        "comment": f"Step lock: +${total_to_lock:.2f}"
                                    }
                                    result = mt5.order_send(request)
                                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                                        old_locked = position.total_locked_profit
                                        position.stop_loss = new_stop
                                        position.total_locked_profit = new_total_locked
                                        position.last_locked_profit = position.last_locked_profit + (steps * step_amount)
                                        position.lock_levels.append(current_pnl)
                                        newly_locked = new_total_locked - old_locked

                                        self.logger.info(f"✅ Position {ticket} STEP LOCK: locked ${newly_locked:.2f} "
                                                        f"(Total locked: ${new_total_locked:.2f}, Profit: ${current_pnl:.2f})")
                                        if self.alert_system:
                                            self.alert_system.alert_profit_locked(position, newly_locked)
                                        try:
                                            self.callback_queue.put_nowait(('profit_locked', {
                                                'ticket': ticket,
                                                'locked_amount': newly_locked,
                                                'total_locked': new_total_locked,
                                                'total_profit': current_pnl,
                                                'new_stop': new_stop
                                            }))
                                        except:
                                            pass
                                    else:
                                        error = result.comment if result else "No result"
                                        retcode = result.retcode if result else "None"
                                        self.logger.error(f"❌ Position {ticket} order failed: {error} (retcode {retcode})")
                                else:
                                    self.logger.info(f"Position {ticket}: new_stop {new_stop:.5f} >= current stop {position.stop_loss:.5f} – skipping")

                except Exception as e:
                    self.logger.error(f"Error updating position {ticket}: {e}")

            for ticket in closed_positions:
                if ticket in self.positions:
                    del self.positions[ticket]
                    self.logger.info(f"Removed position {ticket} from management (Remaining: {len(self.positions)})")                   
                    
    def update_config_for_all_positions(self) -> int:
        with self.position_lock:
            updated_count = 0
            for ticket, position in self.positions.items():
                if position.status == PositionStatus.OPEN:
                    updated_count += 1
            if updated_count > 0:
                self.logger.info(f"Config updated for {updated_count} positions (Total: {len(self.positions)})")
                try:
                    self.callback_queue.put_nowait(('trailing_config_updated', {
                        'updated_count': updated_count,
                        'total_positions': len(self.positions),
                        'config': {
                            'enabled': self.trailing_config.enable_trailing_stop,
                            'lock_amount': self.trailing_config.lock_amount_dollars,
                            'step_amount': self.trailing_config.step_amount_dollars
                        }
                    }))
                except:
                    pass
                if self.callbacks['on_config_updated']:
                    self.callbacks['on_config_updated'](updated_count)
            return updated_count

    def update_config(self, enabled: bool, lock_amount: float, step_amount: float):
        old_enabled = self.trailing_config.enable_trailing_stop

        self.trailing_config.enable_trailing_stop = enabled
        self.trailing_config.lock_amount_dollars = lock_amount
        self.trailing_config.step_amount_dollars = step_amount

        self.logger.info(f"Step trailing config updated - Enabled: {enabled}, "
                         f"Lock: ${lock_amount}, Step: ${step_amount}")

        updated = self.update_config_for_all_positions()
        if updated > 0:
            self.logger.info(f"Applied new config to {updated} existing positions (Total: {len(self.positions)})")

        try:
            if self.callback_queue:
                self.callback_queue.put_nowait(('trailing_config_updated', {
                    'enabled': enabled,
                    'lock_amount': lock_amount,
                    'step_amount': step_amount,
                    'updated_positions': updated,
                    'total_managed': len(self.positions)
                }))
        except:
            pass

    def update_performance_metrics(self, position: Position):
        self.performance_metrics['total_trades'] += 1
        if position.profit > 0:
            self.performance_metrics['winning_trades'] += 1
            self.performance_metrics['total_profit'] += position.profit
            self.performance_metrics['max_win'] = max(self.performance_metrics['max_win'], position.profit)
        else:
            self.performance_metrics['losing_trades'] += 1
            self.performance_metrics['total_profit'] += position.profit
            self.performance_metrics['max_loss'] = min(self.performance_metrics['max_loss'], position.profit)

        if self.performance_metrics['winning_trades'] > 0:
            self.performance_metrics['avg_win'] = (
                self.performance_metrics['total_profit'] / self.performance_metrics['winning_trades']
            )
        if self.performance_metrics['losing_trades'] > 0:
            total_losses = abs(self.performance_metrics['total_profit'] -
                              (self.performance_metrics['winning_trades'] * self.performance_metrics['avg_win']))
            self.performance_metrics['avg_loss'] = total_losses / self.performance_metrics['losing_trades']
        if abs(self.performance_metrics['avg_loss']) > 0:
            self.performance_metrics['profit_factor'] = (
                self.performance_metrics['avg_win'] / abs(self.performance_metrics['avg_loss'])
            )

    def modify_position_sl_tp(self, ticket: int, stop_loss: Optional[float] = None,
                             take_profit: Optional[float] = None) -> bool:
        with self.position_lock:
            if ticket not in self.positions:
                return False
            position = self.positions[ticket]
            try:
                if stop_loss is not None:
                    position.stop_loss = stop_loss
                if take_profit is not None:
                    position.take_profit = take_profit
                return True
            except Exception as e:
                self.logger.error(f"Error modifying position {ticket}: {e}")
                return False

    def close_position(self, ticket: int) -> bool:
        with self.position_lock:
            if ticket not in self.positions:
                return False
            position = self.positions[ticket]
            position.status = PositionStatus.CLOSED
            position.exit_time = datetime.now()
            position.exit_price = position.current_price
            position.profit = position.mt5_profit

            self.update_performance_metrics(position)

            if self.callbacks['on_position_closed']:
                self.callbacks['on_position_closed'](position)

            del self.positions[ticket]
            self.logger.info(f"Position {ticket} manually closed with P&L: ${position.profit:.2f} (Remaining: {len(self.positions)})")
            return True

    def get_open_positions(self) -> List[Position]:
        with self.position_lock:
            return [pos for pos in self.positions.values() if pos.status == PositionStatus.OPEN]

    def get_position(self, ticket: int) -> Optional[Position]:
        with self.position_lock:
            return self.positions.get(ticket)

    def get_performance_summary(self) -> Dict[str, Any]:
        with self.position_lock:
            open_positions = self.get_open_positions()

            total_closed = self.performance_metrics['total_trades']
            win_rate = 0
            if total_closed > 0:
                win_rate = (self.performance_metrics['winning_trades'] / total_closed) * 100

            summary = {
                'performance_metrics': self.performance_metrics.copy(),
                'open_positions_count': len(open_positions),
                'closed_positions_count': total_closed,
                'win_rate': win_rate,
                'current_total_profit': self.performance_metrics['total_profit'],
                'trailing_config': {
                    'enabled': self.trailing_config.enable_trailing_stop,
                    'lock_amount_dollars': self.trailing_config.lock_amount_dollars,
                    'step_amount_dollars': self.trailing_config.step_amount_dollars
                },
                'total_managed_positions': len(self.positions)
            }

            summary['open_positions'] = []
            total_pnl = 0
            total_locked = 0

            for pos in open_positions:
                current_pnl = pos.mt5_profit
                total_pnl += current_pnl
                total_locked += pos.total_locked_profit

                summary['open_positions'].append({
                    'ticket': pos.ticket,
                    'symbol': pos.symbol,
                    'type': pos.order_type.value,
                    'entry_price': pos.entry_price,
                    'current_price': pos.current_price,
                    'stop_loss': pos.stop_loss,
                    'take_profit': pos.take_profit,
                    'pnl': current_pnl,
                    'breakeven_reached': pos.breakeven_reached,
                    'locked_profit': pos.total_locked_profit,
                    'total_locked_profit': pos.total_locked_profit,
                    'lock_levels': pos.lock_levels,
                    'at_risk': current_pnl - pos.total_locked_profit if current_pnl > pos.total_locked_profit else current_pnl
                })

            summary['total_pnl'] = total_pnl
            summary['total_locked_profit'] = total_locked

            return summary

    def enable_trailing(self, enable: bool = True):
        self.trailing_config.enable_trailing_stop = enable
        status = "ENABLED" if enable else "DISABLED"
        self.logger.info(f"Step trailing stop-loss {status} for ALL positions")

    def sync_existing_positions(self) -> int:
        added_count = 0
        try:
            positions = mt5.positions_get()
            if not positions:
                self.logger.info("No existing positions to sync")
                return 0

            for pos in positions:
                if pos.ticket in self.positions:
                    continue

                order_type = OrderType.LONG if pos.type == 0 else OrderType.SHORT
                success = self.add_position(
                    ticket=pos.ticket,
                    symbol=pos.symbol,
                    order_type=order_type,
                    volume=pos.volume,
                    entry_price=pos.price_open,
                    stop_loss=pos.sl,
                    take_profit=pos.tp,
                    comment="Synced from MT5"
                )
                if success:
                    added_count += 1
                    self.logger.info(f"✅ Synced position {pos.ticket} ({pos.symbol}) to step trailing")

            self.logger.info(f"✅ Synced {added_count} existing positions with step trailing manager (Total managed: {len(self.positions)})")

            if self.callback_queue:
                try:
                    self.callback_queue.put_nowait(('trailing_sync_complete', {
                        'added': added_count,
                        'total_managed': len(self.positions)
                    }))
                except:
                    pass

            return added_count
        except Exception as e:
            self.logger.error(f"Error syncing existing positions: {e}")
            return 0