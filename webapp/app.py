import asyncio
import contextlib
import os
import threading
import time
from collections import deque
from functools import wraps
from pathlib import Path

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for

import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import BotConfig, Settings
from modules.database.supabase_manager import SupabaseUserManager
from modules.trading.bot import DerivBot


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY") or os.getenv("SECRET_KEY") or "dev-only-change-me"


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
MODE_OPTIONS = ["Monitor", "Auto-Trade", "Adaptive"]
MARTINGALE_OPTIONS = ["Classic", "Reverse"]
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
                "martingale_mult": "2.5",
                "max_martingale_steps": "4",
                "confirmations": "2",
                "mode": "Monitor",
                "martingale_mode": "Classic",
                "manual_contract": "Rise/Fall",
                "manual_stake": "5",
                "manual_duration": "1",
            },
            "session_token": "",
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
                "last_error": self.state["last_error"],
                "history_total": f"{history_total:+.2f}" if history_total else "0.00",
                "last_updated": self.state["last_updated"],
                "token_saved": bool(self.state.get("session_token")),
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
            # Keep app_id shared across users/services from environment settings.
            self.state["config"]["app_id"] = str(Settings.DERIV_APP_ID)
            for field in self.state["config"]:
                if field == "app_id":
                    continue
                value = form.get(field)
                if value is not None:
                    self.state["config"][field] = value.strip()
            self._touch()

    def remember_token(self, token):
        token = (token or "").strip()
        if not token:
            return
        with self.lock:
            self.state["session_token"] = token
            self._touch()

    def get_session_token(self):
        with self.lock:
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
            app_id=int(config_values["app_id"]),
            symbol=config_values["symbol"],
            granularity_seconds=TIMEFRAME_OPTIONS.get(config_values["timeframe"], 60),
            base_stake=float(config_values["stake"]),
            duration=int(config_values["duration"]),
            ticks_duration=ticks_duration,
            cooldown=int(config_values["cooldown"]),
            max_daily_loss=float(config_values["max_daily_loss"]),
            martingale_mult=float(config_values["martingale_mult"]),
            max_martingale_steps=int(config_values["max_martingale_steps"]),
            martingale_mode=config_values["martingale_mode"],
            confirmations_required=int(config_values["confirmations"]),
            selected_strategy=strategy,
            timeframe=config_values["timeframe"],
        )

    def start_bot(self, token):
        with self.lock:
            if self.state["running"]:
                return False, "Bot is already running."

            try:
                config = self._make_config()
            except Exception as exc:
                return False, f"Invalid bot settings: {exc}"

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
        if bot:
            bot.set_mode(mode)
            self._append_log(f"Mode changed to: {mode}")
        return True, f"Mode set to {mode}."

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


def current_manager():
    user = session.get("user")
    if not user:
        return None
    return bot_hub.get_manager(user)


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
        timeframe_options=list(TIMEFRAME_OPTIONS.keys()),
        strategy_options=STRATEGY_OPTIONS,
        mode_options=MODE_OPTIONS,
        martingale_options=MARTINGALE_OPTIONS,
        manual_contract_options=MANUAL_CONTRACT_OPTIONS,
    )


@app.route("/", methods=["GET", "POST"])
def login():
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

        session["user"] = user
        bot_hub.get_manager(user)
        flash("Login successful.", "success")
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
        success, message = user_manager.request_password_reset(
            request.form.get("email", "").strip()
        )
        flash(message, "success" if success else "error")
        return redirect(url_for("reset_password"))

    return render_template("reset_password.html")


@app.route("/dashboard")
@login_required
def dashboard():
    return render_dashboard_page()


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

    token = request.form.get("token", "").strip() or manager.get_session_token()
    if not token:
        if request.headers.get("X-Requested-With") == "fetch":
            return jsonify({"success": False, "message": "API token is required."}), 400
        flash("API token is required.", "error")
        return redirect(url_for("dashboard"))

    manager.update_config_from_form(request.form)
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
    mode = request.form.get("mode", "Monitor")
    success, message = manager.set_mode(mode)
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
