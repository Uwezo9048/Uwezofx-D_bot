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
                            "sell_price": 0.00,
                            "profit_loss": -0.40,
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
