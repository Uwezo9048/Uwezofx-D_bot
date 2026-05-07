import asyncio
import contextlib
import json
import os
import secrets
import threading
import time
from collections import deque
from datetime import timedelta
from functools import wraps
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
try:
    from flask import send_file
except ImportError:
    send_file = None
from werkzeug.middleware.proxy_fix import ProxyFix

import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import BotConfig, Settings
from modules.database.supabase_manager import SupabaseUserManager
from modules.trading.bot import DerivBot
import websockets


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or os.getenv("SECRET_KEY") or "dev-only-change-me"
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
app.permanent_session_lifetime = timedelta(hours=12)


TIMEFRAME_OPTIONS = {
    "1s": 1,
    "2s": 2,
    "5s": 5,
    "10s": 10,
    "15s": 15,
    "30s": 30,
    "1m": 60,
    "2m": 120,
    "3m": 180,
    "5m": 300,
    "10m": 600,
    "15m": 900,
}

STRATEGY_OPTIONS = ["ICT/SMS", "Over 1-3", "Under 6-8", "Even", "Odd"]
MODE_OPTIONS = ["Monitor", "Auto-Trade"]
ADAPTIVE_PAIR_OPTIONS = ["Over/Under", "Even/Odd", "Buy/Sell"]
MARTINGALE_OPTIONS = ["Classic", "Reverse"]
CONFIDENCE_LADDER_OPTIONS = ["75/80/85", "68/75/80"]
MANUAL_CONTRACT_OPTIONS = [
    "Rise/Fall",
    "Higher/Lower",
    "Touch/No Touch",
    "Even/Odd",
    "Over/Under",
]

FALLBACK_SYMBOLS = [
    "R_10",
    "R_25",
    "R_50",
    "R_75",
    "R_100",
    "1HZ10V",
    "1HZ25V",
    "1HZ50V",
    "1HZ75V",
    "1HZ100V",
    "BOOM1000",
    "BOOM500",
    "CRASH1000",
    "CRASH500",
]


def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not session.get("user"):
            flash("Please log in first.", "error")
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped_view


class WebBotManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.bot = None
        self.loop = None
        self.bot_thread = None
        self.state = self._default_state()

    def _default_state(self):
        return {
            "running": False,
            "connected": False,
            "user": None,
            "config": {
                "app_id": Settings.DERIV_APP_ID,
                "symbol": "R_100",
                "strategy": "ICT/SMS",
                "stake": "1.0",
                "duration": "1",
                "ticks_duration": "5",
                "timeframe": "1m",
                "cooldown": "60",
                "max_daily_loss": "50.0",
                "max_daily_profit": "0.0",
                "martingale_mult": "2.5",
                "max_martingale_steps": "4",
                "confirmations": "2",
                "mode": "Monitor",
                "adaptive_enabled": "",
                "adaptive_pair": "Over/Under",
                "martingale_mode": "Classic",
                "confidence_ladder": "75/80/85",
                "manual_contract": "Rise/Fall",
                "manual_stake": "5",
                "manual_duration": "1",
                "timeout_minutes": "5",
                "deriv_account": "",
            },
            "session_token": "",
            "deriv_accounts": [],
            "metrics": {
                "balance": "--",
                "stake": "--",
                "signal": "--",
                "confidence": "--",
            },
            "positions": [],
            "history": [],
            "digits": self._default_digits(),
            "logs": deque(maxlen=250),
            "advisories": deque(maxlen=80),
            "last_error": "",
            "last_updated": None,
        }

    def _default_digits(self):
        return [
            {"digit": digit, "percent": 0.0, "tone": "neutral"}
            for digit in range(10)
        ]

    def _touch(self):
        self.state["last_updated"] = int(time.time())

    def _append_log(self, message):
        with self.lock:
            self.state["logs"].append(message)
            self._touch()

    def _append_advisory(self, message, action="HOLD", confidence=0):
        with self.lock:
            self.state["advisories"].append(
                {
                    "time": time.strftime("%H:%M:%S"),
                    "message": str(message),
                    "action": str(action or "HOLD"),
                    "confidence": int(round(float(confidence or 0))),
                }
            )
            self._touch()

    def _update_balance(self, balance, currency):
        with self.lock:
            self.state["metrics"]["balance"] = f"{balance:.2f} {currency}"
            self.state["connected"] = True
            self._touch()

    def _update_stake(self, stake, level):
        with self.lock:
            self.state["metrics"]["stake"] = f"{stake:.2f} (L{level})"
            self._touch()

    def _update_signal(self, signal):
        with self.lock:
            self.state["metrics"]["signal"] = str(signal)
            self._touch()

    def _update_confidence(self, confidence):
        with self.lock:
            self.state["metrics"]["confidence"] = f"{confidence}%"
            self._touch()

    def _update_mode_from_bot(self, mode):
        with self.lock:
            self.state["config"]["mode"] = str(mode or "Monitor")
            self._touch()

    def _update_digits(self, stats_dict):
        with self.lock:
            digits = self._default_digits()
            for digit, (percentage, tone) in stats_dict.items():
                digits[int(digit)] = {
                    "digit": int(digit),
                    "percent": round(float(percentage), 1),
                    "tone": tone,
                }
            self.state["digits"] = digits
            self._touch()

    def _update_strategy(self, strategy):
        display_map = {
            "OVER": "Over 1-3",
            "UNDER": "Under 6-8",
            "EVEN": "Even",
            "ODD": "Odd",
        }
        with self.lock:
            self.state["config"]["strategy"] = display_map.get(strategy, strategy)
            self._append_log(f"Adaptive strategy changed to: {self.state['config']['strategy']}")
            self._touch()

    def _update_positions(self, positions):
        normalized = []
        for pos in positions:
            profit_loss = float(pos.get("profit_loss", 0) or 0)
            normalized.append(
                {
                    "id": str(pos.get("contract_id", "")),
                    "type": str(pos.get("contract_type", "")),
                    "buy_price": f"{float(pos.get('buy_price', 0) or 0):.2f}",
                    "current": f"{float(pos.get('current_price', 0) or 0):.2f}",
                    "payout": f"{float(pos.get('payout', 0) or 0):.2f}",
                    "pl": f"{profit_loss:+.2f}" if profit_loss else "0.00",
                    "status": str(pos.get("status", "")),
                }
            )
        with self.lock:
            self.state["positions"] = normalized
            self._touch()

    def _update_history(self, trades):
        normalized = []
        for trade in trades:
            stake_value = float(trade.get("stake", trade.get("buy_price", 0)) or 0)
            contract_value = float(
                trade.get("contract_value", trade.get("payout", trade.get("sell_price", 0)) or 0)
            )
            raw_profit_loss = trade.get("profit_loss", "0.00")
            try:
                profit_value = float(raw_profit_loss) if raw_profit_loss not in (None, "") else contract_value - stake_value
                if profit_value == 0.0 and (stake_value or contract_value):
                    profit_value = contract_value - stake_value
                profit_loss = f"{profit_value:+.2f}" if profit_value else "0.00"
            except (TypeError, ValueError):
                profit_value = contract_value - stake_value
                profit_loss = f"{profit_value:+.2f}" if profit_value else "0.00"
            normalized.append(
                {
                    "currency": str(trade.get("currency", "USD")),
                    "stake": f"{stake_value:.2f}",
                    "contract": f"{contract_value:.2f}",
                    "profit_loss": profit_loss,
                }
            )
        with self.lock:
            self.state["history"] = normalized
            self._touch()

    def snapshot(self):
        with self.lock:
            history_total = 0.0
            for item in self.state["history"]:
                try:
                    history_total += float(str(item["profit_loss"]).replace("+", ""))
                except ValueError:
                    continue
            return {
                "running": self.state["running"],
                "connected": self.state["connected"],
                "user": self.state["user"],
                "config": dict(self.state["config"]),
                "metrics": dict(self.state["metrics"]),
                "positions": list(self.state["positions"]),
                "history": list(self.state["history"]),
                "digits": list(self.state["digits"]),
                "logs": list(self.state["logs"]),
                "advisories": list(self.state["advisories"]),
                "last_error": self.state["last_error"],
                "history_total": f"{history_total:+.2f}" if history_total else "0.00",
                "last_updated": self.state["last_updated"],
                "token_saved": bool(self.state.get("session_token")),
                "deriv_accounts": list(self.state.get("deriv_accounts", [])),
            }

    def _set_error(self, message):
        with self.lock:
            self.state["last_error"] = message
            self.state["connected"] = False
            self._touch()

    def set_user(self, user):
        with self.lock:
            self.state["user"] = user
            self._touch()

    def update_config_from_form(self, form):
        with self.lock:
            for field in self.state["config"]:
                if field == "app_id":
                    continue
                value = form.get(field)
                if value is not None:
                    self.state["config"][field] = value.strip()
            self.state["config"]["adaptive_enabled"] = "on" if form.get("adaptive_enabled") == "on" else ""
            selected_token = self._token_for_selected_account_locked()
            selected_app_id = self._app_id_for_selected_account_locked()
            if selected_token:
                self.state["session_token"] = selected_token
            self.state["config"]["app_id"] = selected_app_id or str(Settings.DERIV_APP_ID)
            self._touch()

    def remember_token(self, token):
        token = (token or "").strip()
        if not token:
            return
        with self.lock:
            self.state["session_token"] = token
            self._touch()

    def remember_deriv_accounts(self, accounts):
        clean_accounts = []
        for account in accounts:
            token = str(account.get("token", "")).strip()
            account_id = str(account.get("account", "")).strip()
            if not token or not account_id:
                continue
            provided_type = str(account.get("type", "")).strip().title()
            if provided_type not in {"Demo", "Real"}:
                account_type = str(account.get("account_type") or account.get("raw_type") or "").lower()
                is_demo = "demo" in account_type or account_id.upper().startswith(("VRTC", "VR", "DEMO"))
                provided_type = "Demo" if is_demo else "Real"
            clean_accounts.append(
                {
                    "token": token,
                    "account": account_id,
                    "currency": str(account.get("currency", "")).strip(),
                    "type": provided_type,
                    "auth_app_id": str(account.get("auth_app_id") or Settings.DERIV_APP_ID),
                }
            )
        if not clean_accounts:
            return
        with self.lock:
            self.state["deriv_accounts"] = clean_accounts
            current_selection = self.state["config"].get("deriv_account", "")
            account_ids = {item["account"] for item in clean_accounts}
            if current_selection not in account_ids:
                preferred_demo = next((item for item in clean_accounts if item["type"] == "Demo"), None)
                self.state["config"]["deriv_account"] = (preferred_demo or clean_accounts[0])["account"]
            self.state["session_token"] = self._token_for_selected_account_locked() or clean_accounts[0]["token"]
            self.state["config"]["app_id"] = self._app_id_for_selected_account_locked() or str(Settings.DERIV_APP_ID)
            self._touch()

    def select_deriv_account(self, account_id):
        account_id = (account_id or "").strip()
        if not account_id:
            return
        with self.lock:
            for account in self.state.get("deriv_accounts", []):
                if account.get("account") == account_id:
                    self.state["config"]["deriv_account"] = account_id
                    self.state["session_token"] = account.get("token", "")
                    self.state["config"]["app_id"] = account.get("auth_app_id") or str(Settings.DERIV_APP_ID)
                    self._touch()
                    return

    def _token_for_selected_account_locked(self):
        selected_account = self.state["config"].get("deriv_account", "")
        for account in self.state.get("deriv_accounts", []):
            if account.get("account") == selected_account:
                return account.get("token", "")
        return ""

    def _app_id_for_selected_account_locked(self):
        selected_account = self.state["config"].get("deriv_account", "")
        for account in self.state.get("deriv_accounts", []):
            if account.get("account") == selected_account:
                return account.get("auth_app_id", "")
        return ""

    def get_session_token(self):
        with self.lock:
            selected_token = self._token_for_selected_account_locked()
            if selected_token:
                return selected_token
            return self.state.get("session_token", "")

    def _make_config(self):
        config_values = self.state["config"]
        strategy = config_values["strategy"]
        ticks_duration = (
            int(config_values["ticks_duration"])
            if strategy in {"Over 1-3", "Under 6-8", "Even", "Odd"}
            else 5
        )
        return BotConfig(
            app_id=str(config_values["app_id"]).strip(),
            symbol=config_values["symbol"],
            granularity_seconds=TIMEFRAME_OPTIONS.get(config_values["timeframe"], 60),
            base_stake=float(config_values["stake"]),
            duration=int(config_values["duration"]),
            ticks_duration=ticks_duration,
            cooldown=int(config_values["cooldown"]),
            max_daily_loss=float(config_values["max_daily_loss"]),
            max_daily_profit=float(config_values.get("max_daily_profit", 0) or 0),
            martingale_mult=float(config_values["martingale_mult"]),
            max_martingale_steps=int(config_values["max_martingale_steps"]),
            martingale_mode=config_values["martingale_mode"],
            confidence_ladder=config_values.get("confidence_ladder", "75/80/85"),
            confirmations_required=int(config_values["confirmations"]),
            selected_strategy=strategy,
            timeframe=config_values["timeframe"],
            deriv_account=config_values.get("deriv_account", ""),
            adaptive_enabled=config_values.get("adaptive_enabled") == "on",
            adaptive_pair=config_values.get("adaptive_pair", "Over/Under"),
        )

    def start_bot(self, token):
        with self.lock:
            try:
                config = self._make_config()
            except Exception as exc:
                return False, f"Invalid bot settings: {exc}"

            if self.state["running"]:
                bot = self.bot
                mode = self.state["config"]["mode"]
                if bot:
                    bot.config = config
                    bot.app_id = bot._app_id_for_token(config.app_id or Settings.DERIV_APP_ID)
                    bot.set_mode(mode)
                self._touch()
                should_refresh_feeds = bool(bot)
            else:
                should_refresh_feeds = False

            if should_refresh_feeds:
                pass
            elif self.state["running"]:
                return False, "Bot is already running."

        if should_refresh_feeds:
            ok, result = self._run_coro(bot.ensure_market_feeds(), timeout=10)
            self._append_log(
                f"Running bot settings updated | Mode: {mode} | Adaptive: {'On' if bot.adaptive_mode else 'Off'} "
                f"({bot.config.adaptive_pair})"
            )
            if not ok:
                return False, f"Bot settings updated, but feed refresh failed: {result}"
            return True, "Bot settings updated."

        with self.lock:
            self.bot = DerivBot(
                token,
                config,
                log_callback=self._append_log,
                balance_callback=self._update_balance,
                stake_callback=self._update_stake,
                signal_callback=self._update_signal,
                confidence_callback=self._update_confidence,
                digit_stats_callback=self._update_digits,
                strategy_update_callback=self._update_strategy,
                positions_callback=self._update_positions,
                trade_history_callback=self._update_history,
                advisory_callback=self._append_advisory,
                mode_callback=self._update_mode_from_bot,
            )
            self.loop = asyncio.new_event_loop()
            self.bot.set_event_loop(self.loop)
            self.bot.set_mode(self.state["config"]["mode"])
            self.state["running"] = True
            self.state["connected"] = False
            self.state["last_error"] = ""
            self._touch()

            def run_loop():
                asyncio.set_event_loop(self.loop)
                try:
                    self.loop.run_until_complete(self.bot.run_bot())
                except Exception as exc:
                    self._set_error(str(exc))
                    self._append_log(f"Bot runtime error: {exc}")
                finally:
                    pending = [task for task in asyncio.all_tasks(self.loop) if not task.done()]
                    for task in pending:
                        task.cancel()
                    if pending:
                        with contextlib.suppress(Exception):
                            self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    with contextlib.suppress(Exception):
                        self.loop.run_until_complete(self.loop.shutdown_asyncgens())
                    self.loop.close()
                    with self.lock:
                        self.state["running"] = False
                        self.bot = None
                        self.loop = None
                        self.bot_thread = None
                        self._touch()

            self.bot_thread = threading.Thread(target=run_loop, daemon=True)
            self.bot_thread.start()
            self._append_log(
                f"Bot started in {self.state['config']['mode']} mode with strategy: {self.state['config']['strategy']}"
            )
            return True, "Bot started."

    def _run_coro(self, coro, timeout=20):
        with self.lock:
            if not self.bot or not self.loop:
                return False, "Bot is not running."
            future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            result = future.result(timeout=timeout)
            return True, result
        except Exception as exc:
            self._set_error(str(exc))
            self._append_log(f"Action failed: {exc}")
            return False, str(exc)

    def stop_bot(self):
        success, result = self._run_coro(self.bot.stop(), timeout=15) if self.bot else (True, None)
        if self.bot_thread and self.bot_thread.is_alive():
            self.bot_thread.join(timeout=10)
        with self.lock:
            self.state["running"] = False
            self.state["connected"] = False
            self._touch()
        self._append_log("Bot stopped")
        return success, "Bot stopped." if success else result

    def reset_martingale(self):
        if not self.bot:
            return False, "Bot is not running."
        success, result = self._run_coro(self.bot.reset_martingale())
        if success:
            self._append_log("Martingale reset requested.")
            return True, "Martingale reset requested."
        return False, result

    def refresh_data(self):
        if not self.bot:
            return False, "Bot is not running."
        ok_positions, _ = self._run_coro(self.bot.get_open_positions())
        ok_history, _ = self._run_coro(self.bot.get_trade_history(limit=50))
        if ok_positions and ok_history:
            return True, "Data refreshed."
        return False, "Refresh failed."

    def set_mode(self, mode):
        with self.lock:
            self.state["config"]["mode"] = mode
            bot = self.bot
            config_values = dict(self.state["config"])
        if bot:
            bot.config.adaptive_enabled = config_values.get("adaptive_enabled") == "on"
            bot.config.adaptive_pair = config_values.get("adaptive_pair", "Over/Under")
            bot.config.selected_strategy = config_values.get("strategy", bot.config.selected_strategy)
            bot.set_mode(mode)
            if mode == "Auto-Trade" and getattr(bot, "profit_limit_reached", False) and not bot.auto_trade:
                with self.lock:
                    self.state["config"]["mode"] = "Monitor"
                    self._touch()
                return False, "Maximum profit target reached. Restart the bot to enable Auto-Trade again."
            self._append_log(
                f"Mode changed to: {mode} | Adaptive: {'On' if bot.adaptive_mode else 'Off'} "
                f"({bot.config.adaptive_pair})"
            )
            self._run_coro(bot.ensure_market_feeds(), timeout=10)
        return True, f"Mode set to {mode}."

    def set_timeout(self, timeout_minutes):
        try:
            timeout_value = int(str(timeout_minutes).strip())
        except (TypeError, ValueError):
            return False, "Timeout must be a whole number of minutes."
        if timeout_value < 1 or timeout_value > 1440:
            return False, "Timeout must be between 1 and 1440 minutes."
        with self.lock:
            self.state["config"]["timeout_minutes"] = str(timeout_value)
            self._touch()
        return True, f"Timeout set to {timeout_value} minute{'s' if timeout_value != 1 else ''}."

    def pause_for_session_timeout(self):
        with self.lock:
            self.state["config"]["mode"] = "Monitor"
            bot = self.bot
        if bot:
            bot.set_mode("Monitor")
            self._append_log("Dashboard timed out. Bot activity kept; trading paused in Monitor mode.")
        else:
            self._append_log("Dashboard timed out. Activity kept for next login.")
        return True, "Session timed out. Bot activity was kept in Monitor mode."

    def close_position(self, contract_id):
        if not self.bot:
            return False, "Bot is not running."
        success, result = self._run_coro(self.bot.close_position(int(contract_id)))
        if success:
            self._append_log(f"Close position requested for {contract_id}")
            return True, "Position close requested."
        return False, result

    def manual_trade(self, form):
        if not self.bot:
            return False, "Bot is not running."

        contract_group = form.get("manual_contract", self.state["config"]["manual_contract"])
        stake = float(form.get("manual_stake", self.state["config"]["manual_stake"]))
        duration = int(form.get("manual_duration", self.state["config"]["manual_duration"]))
        action = form.get("action", "")

        mapping = {
            ("Rise/Fall", "buy"): ("CALL", None, "m"),
            ("Rise/Fall", "sell"): ("PUT", None, "m"),
            ("Higher/Lower", "buy"): ("CALL", None, "m"),
            ("Higher/Lower", "sell"): ("PUT", None, "m"),
            ("Touch/No Touch", "buy"): ("ONETOUCH", "+0.005", "m"),
            ("Touch/No Touch", "sell"): ("NOTOUCH", "+0.005", "m"),
            ("Even/Odd", "buy"): ("DIGITEVEN", None, "t"),
            ("Even/Odd", "sell"): ("DIGITODD", None, "t"),
            ("Over/Under", "buy"): ("DIGITOVER", "3", "t"),
            ("Over/Under", "sell"): ("DIGITUNDER", "6", "t"),
        }

        contract_type, barrier, unit = mapping[(contract_group, action)]
        success, result = self._run_coro(
            self.bot.manual_trade_generic(contract_type, stake, duration, unit, barrier),
            timeout=30,
        )
        if success:
            with self.lock:
                self.state["config"]["manual_contract"] = contract_group
                self.state["config"]["manual_stake"] = str(stake)
                self.state["config"]["manual_duration"] = str(duration)
                self._touch()
            return True, "Manual trade sent."
        return False, result


class UserBotHub:
    def __init__(self):
        self.lock = threading.RLock()
        self.managers = {}

    def _user_key(self, user):
        user_id = user.get("id")
        if user_id is not None:
            return str(user_id)
        return str(user.get("username", "anonymous"))

    def get_manager(self, user):
        key = self._user_key(user)
        with self.lock:
            manager = self.managers.get(key)
            if manager is None:
                manager = WebBotManager()
                self.managers[key] = manager
            manager.set_user(user)
            return manager

    def pop_manager(self, user):
        key = self._user_key(user)
        with self.lock:
            return self.managers.pop(key, None)


user_manager = SupabaseUserManager()
bot_hub = UserBotHub()
pairing_links = {}
pairing_lock = threading.RLock()
PAIRING_LINK_TTL_SECONDS = 180


def cleanup_pairing_links():
    now = time.time()
    with pairing_lock:
        expired = [code for code, item in pairing_links.items() if item.get("expires_at", 0) <= now]
        for code in expired:
            pairing_links.pop(code, None)


def current_manager():
    user = session.get("user")
    if not user:
        return None
    return bot_hub.get_manager(user)


def extract_deriv_accounts(args):
    accounts = []
    for index in range(1, 20):
        token = args.get(f"token{index}", "").strip()
        if not token:
            continue
        accounts.append(
            {
                "token": token,
                "account": args.get(f"acct{index}", "").strip(),
                "currency": args.get(f"cur{index}", "").strip(),
                "auth_app_id": str(Settings.DERIV_OAUTH_APP_ID),
            }
        )
    return accounts


def remember_deriv_accounts_for_session(accounts):
    if not accounts:
        return False
    manager = current_manager()
    if not manager:
        return False
    manager.remember_deriv_accounts(accounts)
    return True


def remember_pending_deriv_accounts(accounts):
    pending_accounts = []
    for account in accounts:
        token = str(account.get("token", "")).strip()
        account_id = str(account.get("account", "")).strip()
        if token and account_id:
            pending_accounts.append(
                {
                    "token": token,
                    "account": account_id,
                    "currency": str(account.get("currency", "")).strip(),
                    "auth_app_id": str(account.get("auth_app_id") or Settings.DERIV_APP_ID),
                }
            )
    if pending_accounts:
        session["pending_deriv_accounts"] = pending_accounts


def attach_pending_deriv_accounts(user):
    pending_accounts = session.pop("pending_deriv_accounts", None)
    if not pending_accounts:
        return False
    manager = bot_hub.get_manager(user)
    manager.remember_deriv_accounts(pending_accounts)
    return True


def handle_deriv_token_redirect():
    accounts = extract_deriv_accounts(request.args)
    if not accounts:
        return None
    if remember_deriv_accounts_for_session(accounts):
        flash("Deriv account linked. Select Demo or Real from the bot settings before running.", "success")
        return redirect(url_for("dashboard"))
    flash("Log in to your bot first, then click Link Deriv Account again.", "error")
    return redirect(url_for("login"))


def deriv_callback_url():
    configured_url = (
        os.getenv("DERIV_OAUTH_REDIRECT_URL")
        or os.getenv("DERIV_CALLBACK_URL")
        or ""
    ).strip()
    if configured_url:
        return configured_url
    return url_for("deriv_callback", _external=True)


def extract_pat_accounts(payload, token):
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        candidates = data.get("accounts") or data.get("items") or data.get("data") or data.get("account")
    else:
        candidates = data
    if isinstance(candidates, dict):
        candidates = [candidates]
    accounts = []
    for item in candidates or []:
        if not isinstance(item, dict):
            continue
        account_id = (
            item.get("account_id")
            or item.get("accountId")
            or item.get("id")
            or item.get("loginid")
            or item.get("account")
        )
        if not account_id:
            continue
        account_id = str(account_id)
        account_type = str(item.get("account_type") or item.get("type") or "").lower()
        is_demo = "demo" in account_type or account_id.upper().startswith(("VRTC", "VR", "DEMO"))
        accounts.append(
            {
                "token": token,
                "account": account_id,
                "currency": str(item.get("currency") or item.get("currency_code") or "USD"),
                "type": "Demo" if is_demo else "Real",
                "auth_app_id": str(Settings.DERIV_PAT_APP_ID),
            }
        )
    return accounts


def parse_deriv_json_response(response):
    try:
        return response.json(), ""
    except ValueError:
        body = str(getattr(response, "text", "") or "").strip()
        if not body:
            return None, "empty response"
        return None, body[:200]


def normalize_deriv_token(token):
    token = str(token or "").strip()
    if not token:
        return ""
    parts = []
    for line in token.splitlines():
        clean = line.strip()
        if not clean:
            continue
        if not clean.replace("_", "").replace("-", "").isalnum():
            break
        parts.append(clean)
    return "".join(parts) if parts else token


def token_source_label(token):
    token = normalize_deriv_token(token)
    if not token:
        return "empty"
    return "PAT" if token.lower().startswith("pat_") else "classic"


def mask_deriv_token(token):
    token = normalize_deriv_token(token)
    if not token:
        return ""
    if len(token) <= 12:
        return "*" * len(token)
    return f"{token[:8]}...{token[-6:]}"


def deriv_non_json_error_message(response, detail):
    detail = str(detail or "empty response").strip()
    if response.status_code == 401:
        return (
            f"Deriv rejected this PAT token: HTTP 401: {detail}. "
            "Generate a fresh PAT token in Deriv, make sure it has trade scope, "
            "and paste the new token exactly as shown."
        )
    return (
        "Deriv PAT account service returned a non-JSON response "
        f"(HTTP {response.status_code}: {detail}). "
        "Make sure DERIV_APP_ID is from a Deriv PAT-type app with trade scope; "
        "legacy Deriv app IDs cannot be used with PAT tokens."
    )


def uses_deriv_options_auth(token, app_id):
    token_text = normalize_deriv_token(token).lower()
    app_id_text = str(app_id or "").strip()
    return token_text.startswith("pat_") or bool(app_id_text and not app_id_text.isdigit())


def app_id_for_token_auth(token, app_id):
    token = normalize_deriv_token(token)
    app_id_text = str(app_id or "").strip()
    if token.lower().startswith("pat_") and app_id_text.isdigit():
        return str(Settings.DERIV_PAT_APP_ID)
    return app_id_text


async def authorize_legacy_deriv_token(token, app_id):
    url = f"wss://ws.derivws.com/websockets/v3?app_id={app_id}"
    try:
        async with websockets.connect(url, ping_interval=None, close_timeout=5) as ws:
            await ws.send(json.dumps({"authorize": token}))
            response = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
    except Exception as exc:
        return False, f"Could not reach Deriv authorization service: {exc}", None

    if response.get("error"):
        error = response["error"]
        return False, error.get("message", "Deriv rejected this token."), None

    authorized = response.get("authorize") or {}
    account = authorized.get("loginid") or authorized.get("account") or ""
    if not account:
        return False, "Deriv authorized the token, but did not return an account id.", None

    account_type = "Demo" if str(account).upper().startswith(("VRTC", "VR", "DEMO")) else "Real"
    return True, "Deriv token connected.", [
        {
            "token": token,
            "account": account,
            "currency": authorized.get("currency", ""),
            "type": account_type,
            "auth_app_id": str(app_id),
        }
    ]


async def authorize_deriv_token(token, app_id, legacy_app_id=None):
    token = normalize_deriv_token(token)
    app_id = app_id_for_token_auth(token, app_id)
    legacy_app_id = str(legacy_app_id or Settings.DERIV_LEGACY_APP_ID)
    if uses_deriv_options_auth(token, app_id):
        import requests

        headers = {
            "Authorization": f"Bearer {token}",
            "Deriv-App-ID": str(app_id),
            "Content-Type": "application/json",
        }
        try:
            response = requests.get(
                "https://api.derivws.com/trading/v1/options/accounts",
                headers=headers,
                timeout=15,
            )
        except Exception as exc:
            return False, f"Could not reach Deriv PAT account service: {exc}", None

        payload, non_json_detail = parse_deriv_json_response(response)
        if payload is None:
            if response.status_code == 401 and not token.lower().startswith("pat_"):
                return await authorize_legacy_deriv_token(token, legacy_app_id)
            message = deriv_non_json_error_message(response, non_json_detail)
            if response.status_code == 401:
                message += f" Token used: {mask_deriv_token(token)}. App ID used: {app_id}."
            return False, message, None

        if response.status_code >= 400:
            if response.status_code == 401 and not token.lower().startswith("pat_"):
                return await authorize_legacy_deriv_token(token, legacy_app_id)
            errors = payload.get("errors") if isinstance(payload, dict) else None
            message = (
                errors[0].get("message")
                if isinstance(errors, list) and errors and isinstance(errors[0], dict)
                else f"Deriv rejected this PAT token: HTTP {response.status_code}"
            )
            if response.status_code == 401:
                message += f" Token used: {mask_deriv_token(token)}. App ID used: {app_id}."
            return False, message, None

        accounts = extract_pat_accounts(payload, token)
        if not accounts:
            return False, "PAT token was accepted, but no Options trading accounts were returned.", None
        return True, "Deriv PAT token connected.", accounts

    return await authorize_legacy_deriv_token(token, app_id)


def fetch_active_symbols(app_id):
    import requests

    try:
        response = requests.get(
            f"https://api.binary.com/active_symbols?app_id={app_id}&product_type=basic",
            timeout=10,
        )
        if response.status_code == 200:
            data = response.json()
            symbols = [
                symbol["symbol"]
                for symbol in data.get("active_symbols", [])
                if not symbol.get("is_trading_suspended", 0)
            ]
            if symbols:
                return sorted(symbols)
    except Exception:
        pass
    return FALLBACK_SYMBOLS


def render_dashboard_page():
    manager = current_manager()
    snapshot = manager.snapshot() if manager else WebBotManager().snapshot()
    symbols = fetch_active_symbols(snapshot["config"]["app_id"])
    user = session.get("user", {})
    return render_template(
        "dashboard.html",
        user=user,
        state=snapshot,
        symbols=symbols,
        deriv_callback_url=deriv_callback_url(),
        timeframe_options=list(TIMEFRAME_OPTIONS.keys()),
        strategy_options=STRATEGY_OPTIONS,
        mode_options=MODE_OPTIONS,
        adaptive_pair_options=ADAPTIVE_PAIR_OPTIONS,
        martingale_options=MARTINGALE_OPTIONS,
        confidence_ladder_options=CONFIDENCE_LADDER_OPTIONS,
        manual_contract_options=MANUAL_CONTRACT_OPTIONS,
    )


@app.route("/", methods=["GET", "POST"])
def login():
    token_redirect = handle_deriv_token_redirect()
    if token_redirect:
        return token_redirect

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        login_code = request.form.get("login_code", "").strip()
        if not username or not login_code:
            flash("Username and login code required", "error")
            return render_template("login.html")

        success, message, user = user_manager.login(username, login_code)
        if not success:
            flash(message, "error")
            return render_template("login.html")

        session.permanent = True
        session["user"] = user
        linked_deriv = attach_pending_deriv_accounts(user)
        if not linked_deriv:
            bot_hub.get_manager(user)
        flash("Login successful. Deriv account linked." if linked_deriv else "Login successful.", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    manager = current_manager()
    if manager:
        manager.stop_bot()
    user = session.get("user")
    if user:
        bot_hub.pop_manager(user)
    session.clear()
    flash("Logged out.", "success")
    return redirect(url_for("login"))


@app.route("/session-timeout")
def session_timeout():
    manager = current_manager()
    if manager:
        manager.pause_for_session_timeout()
    session.clear()
    flash("Session timed out. Bot activity was kept and trading is paused in Monitor mode.", "success")
    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        success, message = user_manager.register_user(
            request.form.get("username", "").strip(),
            request.form.get("email", "").strip(),
            request.form.get("phone", "").strip(),
            request.form.get("password", ""),
        )
        flash(message, "success" if success else "error")
        return redirect(url_for("register"))

    return render_template("register.html")


@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    if request.method == "POST":
        success, message = user_manager.request_login_code_resend(
            request.form.get("username", "").strip(),
            request.form.get("phone", "").strip(),
        )
        flash(message, "success" if success else "error")
        return redirect(url_for("reset_password"))

    return render_template("reset_password.html")


@app.route("/dashboard")
@login_required
def dashboard():
    token_redirect = handle_deriv_token_redirect()
    if token_redirect:
        return token_redirect
    return render_dashboard_page()


@app.route("/deriv/connect")
@login_required
def deriv_connect():
    params = {"app_id": str(Settings.DERIV_OAUTH_APP_ID)}
    return redirect(f"https://oauth.deriv.com/oauth2/authorize?{urlencode(params)}")


@app.route("/deriv/callback")
def deriv_callback():
    if request.args.get("error"):
        error_description = request.args.get("error_description") or request.args.get("error")
        flash(f"Deriv account linking failed: {error_description}", "error")
        return redirect(url_for("dashboard") if session.get("user") else url_for("login"))

    expected_state = session.pop("deriv_oauth_state", "")
    returned_state = request.args.get("state", "")
    if expected_state and returned_state and expected_state != returned_state:
        flash("Deriv account linking failed. Please try again.", "error")
        return redirect(url_for("dashboard") if session.get("user") else url_for("login"))

    accounts = extract_deriv_accounts(request.args)

    if not accounts:
        flash("No Deriv token was returned. You can still paste an API token manually.", "error")
        return redirect(url_for("dashboard") if session.get("user") else url_for("login"))

    if remember_deriv_accounts_for_session(accounts):
        flash("Deriv account linked. Select Demo or Real from the bot settings before running.", "success")
        return redirect(url_for("dashboard"))

    remember_pending_deriv_accounts(accounts)
    flash("Deriv account received. Log in to your bot to finish linking.", "success")
    return redirect(url_for("login"))


@app.route("/deriv/connect-token", methods=["POST"])
@login_required
def deriv_connect_token():
    manager = current_manager()
    if not manager:
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"success": False, "message": "Please log in first."}), 401
        flash("Please log in first.", "error")
        return redirect(url_for("login"))

    submitted_token = normalize_deriv_token(request.form.get("token", ""))
    token = submitted_token
    if not token:
        message = "Paste the new Deriv API token first, then click Connect Token."
        with manager.lock:
            manager.state["session_token"] = ""
            manager._touch()
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"success": False, "message": message}), 400
        flash(message, "error")
        return redirect(url_for("dashboard"))

    success, message, authorized_accounts = asyncio.run(
        authorize_deriv_token(token, Settings.DERIV_PAT_APP_ID, Settings.DERIV_LEGACY_APP_ID)
    )
    if success:
        accounts = authorized_accounts if isinstance(authorized_accounts, list) else [authorized_accounts]
        manager.remember_deriv_accounts(accounts)
        selected_account = request.form.get("deriv_account", "").strip()
        account_ids = {str(account.get("account", "")).strip() for account in accounts}
        if selected_account in account_ids:
            manager.select_deriv_account(selected_account)
        elif accounts:
            manager.select_deriv_account(manager.snapshot()["config"].get("deriv_account") or accounts[0]["account"])
        if len(accounts) > 1:
            message = f"{message} {len(accounts)} accounts available; choose Demo or Real before running."
    elif "401" in str(message) or "Invalid or expired token" in str(message):
        with manager.lock:
            manager.state["session_token"] = ""
            manager._touch()
    message = f"{message} ({token_source_label(token)} token {mask_deriv_token(token)})"

    if request.headers.get("X-Requested-With") == "fetch":
        payload = manager.snapshot()
        payload.update({"success": success, "message": message})
        return jsonify(payload), 200 if success else 400
    flash(message, "success" if success else "error")
    return redirect(url_for("dashboard"))


@app.route("/pairing/create", methods=["POST"])
@login_required
def create_pairing_link():
    manager = current_manager()
    if not manager:
        return jsonify({"success": False, "message": "Please log in first."}), 401

    cleanup_pairing_links()
    code = secrets.token_urlsafe(24)
    user = session.get("user", {})
    with pairing_lock:
        pairing_links[code] = {
            "user": user,
            "expires_at": time.time() + PAIRING_LINK_TTL_SECONDS,
        }
    return jsonify(
        {
            "success": True,
            "url": url_for("pair_dashboard", code=code, _external=True),
            "qr_url": url_for("pairing_qr", code=code),
            "code": code,
            "expires_in": PAIRING_LINK_TTL_SECONDS,
        }
    )


@app.route("/pairing/qr/<code>.png")
@login_required
def pairing_qr(code):
    cleanup_pairing_links()
    with pairing_lock:
        pairing = pairing_links.get(str(code or ""))
    if not pairing:
        return jsonify({"success": False, "message": "QR pairing link expired or invalid."}), 404

    import qrcode

    image = qrcode.make(url_for("pair_dashboard", code=code, _external=True))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    if send_file is None:
        return buffer.getvalue()
    return send_file(buffer, mimetype="image/png", max_age=0)


@app.route("/pair/<code>")
def pair_dashboard(code):
    cleanup_pairing_links()
    with pairing_lock:
        pairing = pairing_links.pop(str(code or ""), None)
    if not pairing:
        flash("QR pairing link expired or invalid. Generate a new QR from the running bot.", "error")
        return redirect(url_for("login"))

    user = pairing.get("user") or {}
    if not user:
        flash("QR pairing failed. Please log in normally.", "error")
        return redirect(url_for("login"))

    session.permanent = True
    session["user"] = user
    bot_hub.get_manager(user)
    flash("Device paired. You can now control the running bot from this device.", "success")
    return redirect(url_for("dashboard"))


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "service": "uwezo-render-web"}), 200


@app.route("/bot/start", methods=["POST"])
@login_required
def start_bot():
    manager = current_manager()
    if not manager:
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"success": False, "message": "Please log in first."}), 401
        flash("Please log in first.", "error")
        return redirect(url_for("login"))

    manager.update_config_from_form(request.form)
    token = normalize_deriv_token(request.form.get("token", "")) or manager.get_session_token()
    if not token:
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"success": False, "message": "API token is required."}), 400
        flash("API token is required.", "error")
        return redirect(url_for("dashboard"))

    manager.remember_token(token)
    success, message = manager.start_bot(token)
    if request.headers.get("X-Requested-With") == "fetch":
        payload = manager.snapshot()
        payload.update({"success": success, "message": message})
        return jsonify(payload), 200 if success else 400
    flash(message, "success" if success else "error")
    return redirect(url_for("dashboard"))


@app.route("/bot/stop", methods=["POST"])
@login_required
def stop_bot():
    manager = current_manager()
    if not manager:
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"success": False, "message": "Please log in first."}), 401
        flash("Please log in first.", "error")
        return redirect(url_for("login"))
    success, message = manager.stop_bot()
    if request.headers.get("X-Requested-With") == "fetch":
        payload = manager.snapshot()
        payload.update({"success": success, "message": message})
        return jsonify(payload), 200 if success else 400
    flash(message, "success" if success else "error")
    return redirect(url_for("dashboard"))


@app.route("/bot/reset-martingale", methods=["POST"])
@login_required
def reset_martingale():
    manager = current_manager()
    if not manager:
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"success": False, "message": "Please log in first."}), 401
        flash("Please log in first.", "error")
        return redirect(url_for("login"))
    success, message = manager.reset_martingale()
    if request.headers.get("X-Requested-With") == "fetch":
        payload = manager.snapshot()
        payload.update({"success": success, "message": message})
        return jsonify(payload), 200 if success else 400
    flash(message, "success" if success else "error")
    return redirect(url_for("dashboard"))


@app.route("/bot/mode", methods=["POST"])
@login_required
def set_mode():
    manager = current_manager()
    if not manager:
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"success": False, "message": "Please log in first."}), 401
        flash("Please log in first.", "error")
        return redirect(url_for("login"))
    manager.update_config_from_form(request.form)
    mode = request.form.get("mode", manager.snapshot()["config"].get("mode", "Monitor"))
    success, message = manager.set_mode(mode)
    if request.headers.get("X-Requested-With") == "fetch":
        payload = manager.snapshot()
        payload.update({"success": success, "message": message})
        return jsonify(payload), 200 if success else 400
    flash(message, "success" if success else "error")
    return redirect(url_for("dashboard"))


@app.route("/dashboard/timeout", methods=["POST"])
@login_required
def set_dashboard_timeout():
    manager = current_manager()
    if not manager:
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"success": False, "message": "Please log in first."}), 401
        flash("Please log in first.", "error")
        return redirect(url_for("login"))
    success, message = manager.set_timeout(request.form.get("timeout_minutes", "5"))
    if request.headers.get("X-Requested-With") == "fetch":
        payload = manager.snapshot()
        payload.update({"success": success, "message": message})
        return jsonify(payload), 200 if success else 400
    flash(message, "success" if success else "error")
    return redirect(url_for("dashboard"))


@app.route("/bot/manual-trade", methods=["POST"])
@login_required
def manual_trade():
    manager = current_manager()
    if not manager:
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"success": False, "message": "Please log in first."}), 401
        flash("Please log in first.", "error")
        return redirect(url_for("login"))
    try:
        success, message = manager.manual_trade(request.form)
    except Exception as exc:
        success, message = False, f"Invalid manual trade settings: {exc}"
    if request.headers.get("X-Requested-With") == "fetch":
        payload = manager.snapshot()
        payload.update({"success": success, "message": message})
        return jsonify(payload), 200 if success else 400
    flash(message, "success" if success else "error")
    return redirect(url_for("dashboard"))


@app.route("/bot/close-position", methods=["POST"])
@login_required
def close_position():
    manager = current_manager()
    if not manager:
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"success": False, "message": "Please log in first."}), 401
        flash("Please log in first.", "error")
        return redirect(url_for("login"))
    contract_id = request.form.get("contract_id", "").strip()
    if not contract_id:
        success, message = False, "Contract ID is required."
    else:
        try:
            success, message = manager.close_position(contract_id)
        except Exception as exc:
            success, message = False, f"Unable to close position: {exc}"
    if request.headers.get("X-Requested-With") == "fetch":
        payload = manager.snapshot()
        payload.update({"success": success, "message": message})
        return jsonify(payload), 200 if success else 400
    flash(message, "success" if success else "error")
    return redirect(url_for("dashboard"))


@app.route("/bot/refresh", methods=["POST"])
@login_required
def refresh_bot_data():
    manager = current_manager()
    if not manager:
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"success": False, "message": "Please log in first."}), 401
        flash("Please log in first.", "error")
        return redirect(url_for("login"))
    success, message = manager.refresh_data()
    if request.headers.get("X-Requested-With") == "fetch":
        payload = manager.snapshot()
        payload.update({"success": success, "message": message})
        return jsonify(payload), 200 if success else 400
    flash(message, "success" if success else "error")
    return redirect(url_for("dashboard"))


@app.route("/api/status")
@login_required
def api_status():
    manager = current_manager()
    if not manager:
        return jsonify({"error": "not_authenticated"}), 401
    return jsonify(manager.snapshot())


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "10000")),
        debug=os.getenv("FLASK_DEBUG") == "1",
    )
