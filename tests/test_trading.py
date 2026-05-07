import asyncio
import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None))
sys.modules.setdefault(
    "websockets",
    types.SimpleNamespace(
        connect=None,
        ConnectionClosedError=ConnectionError,
    ),
)
sys.modules.setdefault("requests", types.SimpleNamespace(request=None, get=None))

class _TradeSignal:
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"
    OVER = "OVER"
    UNDER = "UNDER"
    EVEN = "EVEN"
    ODD = "ODD"


class _CombinedIndicator:
    def get_signal_detail(self):
        return types.SimpleNamespace(direction=_TradeSignal.NEUTRAL)

    def update(self, *args, **kwargs):
        return None


class _MarketAnalyzer:
    @staticmethod
    def calculate_rsi(*args, **kwargs):
        return 50.0

    @staticmethod
    def moving_average_cross(*args, **kwargs):
        return 0


sys.modules.setdefault(
    "modules.trading.indicator",
    types.SimpleNamespace(CombinedICTandSMSIndicator=_CombinedIndicator, TradeSignal=_TradeSignal),
)
sys.modules.setdefault("modules.trading.analyzer", types.SimpleNamespace(MarketAnalyzer=_MarketAnalyzer))

from config import BotConfig
from modules.trading.bot import DerivBot
from modules.trading.indicator import TradeSignal


class RecordingBot(DerivBot):
    def __init__(self, config):
        self.log_entries = []
        super().__init__("token", config, log_callback=self.log_entries.append)
        self.auto_trade = True
        self.balance = 100.0
        self.sent_messages = []
        self.trade_history_refreshes = 0
        self.profit_result = -0.40
        self.mode_updates = []
        self.mode_callback = self.mode_updates.append

    async def _send(self, msg):
        self.sent_messages.append(msg)
        if "proposal" in msg:
            return {
                "proposal": {
                    "id": "proposal-1",
                    "ask_price": msg["amount"],
                    "payout": msg["amount"] * 1.9,
                }
            }
        if "buy" in msg:
            return {
                "buy": {
                    "contract_id": "contract-1",
                    "buy_price": msg["price"],
                    "payout": msg["price"] * 1.9,
                }
            }
        if "profit_table" in msg:
            return {
                "profit_table": {
                    "transactions": [
                        {
                            "contract_id": "contract-1",
                            "buy_price": 0.40,
                            "sell_price": max(0.0, 0.40 + self.profit_result),
                            "profit_loss": self.profit_result,
                        }
                    ]
                }
            }
        if "balance" in msg:
            return {"balance": {"balance": self.balance, "currency": "USD"}}
        if "portfolio" in msg:
            return {"portfolio": {"contracts": []}}
        return {}

    async def refresh_trade_history_once(self, limit=50):
        self.trade_history_refreshes += 1
        return []


async def _no_sleep(_seconds):
    return None


class StakeAndMartingaleTests(unittest.TestCase):
    def test_auto_trade_uses_base_stake_below_one_dollar(self):
        config = BotConfig(base_stake=0.40, martingale_mult=2.0, selected_strategy="Even")
        bot = RecordingBot(config)

        with patch("modules.trading.bot.asyncio.sleep", _no_sleep):
            asyncio.run(bot._place_trade(TradeSignal.EVEN))

        proposal = next(msg for msg in bot.sent_messages if "proposal" in msg)
        self.assertEqual(proposal["amount"], 0.40)
        self.assertEqual(proposal["basis"], "stake")

    def test_classic_martingale_keeps_steps_below_one_dollar(self):
        config = BotConfig(base_stake=0.40, martingale_mult=2.0, martingale_mode="Classic")
        bot = RecordingBot(config)

        bot._update_martingale_after_trade(-0.40)

        self.assertEqual(bot.consecutive, 1)
        self.assertEqual(bot.current_stake, 0.80)

    def test_adaptive_runs_separately_from_monitor_mode(self):
        config = BotConfig(adaptive_enabled=True, adaptive_pair="Over/Under")
        bot = RecordingBot(config)

        bot.set_mode("Monitor")

        self.assertFalse(bot.auto_trade)
        self.assertTrue(bot.adaptive_mode)
        self.assertTrue(bot._needs_tick_feed())

    def test_auto_trade_can_run_with_adaptive_buy_sell_pair(self):
        config = BotConfig(adaptive_enabled=True, adaptive_pair="Buy/Sell")
        bot = RecordingBot(config)

        bot.set_mode("Auto-Trade")

        self.assertTrue(bot.auto_trade)
        self.assertTrue(bot.adaptive_mode)
        self.assertTrue(bot._needs_candle_feed())

    def test_adaptive_digit_direction_places_tick_contract(self):
        config = BotConfig(
            base_stake=0.40,
            adaptive_enabled=True,
            adaptive_pair="Over/Under",
            selected_strategy="OVER",
            ticks_duration=3,
        )
        bot = RecordingBot(config)
        bot.set_mode("Auto-Trade")

        with patch("modules.trading.bot.asyncio.sleep", _no_sleep):
            asyncio.run(bot._place_trade(TradeSignal.OVER))

        proposal = next(msg for msg in bot.sent_messages if "proposal" in msg)
        self.assertEqual(proposal["contract_type"], "DIGITOVER")
        self.assertEqual(proposal["duration_unit"], "t")
        self.assertEqual(proposal["duration"], 3)
        self.assertTrue(bot._needs_tick_feed())

    def test_pat_proposal_uses_underlying_symbol_field(self):
        config = BotConfig(
            app_id="33cqkvVDkguOv3GBkC6OU",
            symbol="R_100",
            base_stake=0.40,
            selected_strategy="Over 1-3",
            ticks_duration=3,
        )
        bot = RecordingBot(config)

        with patch("modules.trading.bot.asyncio.sleep", _no_sleep):
            asyncio.run(bot._place_trade(TradeSignal.OVER))

        proposal = next(msg for msg in bot.sent_messages if "proposal" in msg)
        self.assertEqual(proposal["underlying_symbol"], "R_100")
        self.assertNotIn("symbol", proposal)

    def test_legacy_proposal_keeps_symbol_field(self):
        config = BotConfig(
            app_id="133059",
            symbol="R_100",
            base_stake=0.40,
            selected_strategy="Over 1-3",
            ticks_duration=3,
        )
        bot = RecordingBot(config)

        with patch("modules.trading.bot.asyncio.sleep", _no_sleep):
            asyncio.run(bot._place_trade(TradeSignal.OVER))

        proposal = next(msg for msg in bot.sent_messages if "proposal" in msg)
        self.assertEqual(proposal["symbol"], "R_100")
        self.assertNotIn("underlying_symbol", proposal)

    def test_max_daily_profit_switches_to_monitor_until_restart(self):
        config = BotConfig(base_stake=0.40, max_daily_profit=0.50, selected_strategy="Even")
        bot = RecordingBot(config)
        bot.profit_result = 0.60

        with patch("modules.trading.bot.asyncio.sleep", _no_sleep):
            asyncio.run(bot._place_trade(TradeSignal.EVEN))

        self.assertFalse(bot.auto_trade)
        self.assertTrue(bot.profit_limit_reached)
        self.assertEqual(bot.mode_updates[-1], "Monitor")
        sent_before = len(bot.sent_messages)
        asyncio.run(bot._place_trade(TradeSignal.EVEN))
        self.assertFalse(any("proposal" in msg for msg in bot.sent_messages[sent_before:]))
