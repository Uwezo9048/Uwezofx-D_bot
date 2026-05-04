import tkinter as tk
from tkinter import ttk, messagebox
import threading
import asyncio
import queue
import time
from datetime import datetime
from config import BotConfig, Settings
from modules.database.supabase_manager import SupabaseUserManager
from modules.trading.bot import DerivBot
from modules.gui.login import ModernLoginScreen
from modules.gui.widgets import ModernUI, ModernCard
from modules.utils.helpers import set_app_icon, load_logo

class DerivUwezoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("UWEZO-FX Deriv Trading Bot")
        self.root.geometry("1400x900")
        self.root.configure(bg=ModernUI.COLORS['bg_dark'])
        ModernUI.configure_ttk_styles(self.root)
        set_app_icon(self.root)

        self.user_manager = SupabaseUserManager()
        self.current_user = None
        self.is_logged_in = False
        self.ui_active = False  # Flag to prevent updates after logout

        self.bot = None
        self.bot_thread = None
        self.loop = None
        self.log_queue = queue.Queue()
        self.log_text = None
        self.session_api_token = ""

        self.logo_image = load_logo()

        self.fallback_symbols = [
            "R_10", "R_25", "R_50", "R_75", "R_100",
            "1HZ10V", "1HZ25V", "1HZ50V", "1HZ75V", "1HZ100V",
            "BOOM1000", "BOOM500", "CRASH1000", "CRASH500",
        ]

        self.timeframe_options = {
            "1s": 1, "2s": 2, "5s": 5, "10s": 10, "15s": 15, "30s": 30,
            "1m": 60, "2m": 120, "3m": 180, "5m": 300, "10m": 600, "15m": 900,
        }

        self.start_btn = None
        self.stop_btn = None
        self.positions_tree = None
        self.history_tree = None

        self.show_login_screen()
        self.process_log_queue()
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    # ---------- Login / Registration ----------
    def show_login_screen(self):
        self.ui_active = False
        for widget in self.root.winfo_children():
            widget.destroy()
        self.root.configure(bg=ModernUI.COLORS['bg_dark'])
        card = ModernCard(self.root, title=None)
        card.pack(expand=True, padx=90, pady=70, fill='both')
        if self.logo_image:
            tk.Label(card.content, image=self.logo_image, bg=ModernUI.COLORS['bg_card']).pack(pady=10)
        else:
            tk.Label(card.content, text="UWEZO-FX", font=('Montserrat', 24, 'bold'),
                     fg=ModernUI.COLORS['accent_primary'], bg=ModernUI.COLORS['bg_card']).pack(pady=10)
        tk.Label(card.content, text="UWEZO-FX DERIV TRADING CONSOLE",
                 font=('Segoe UI', 15, 'bold'), fg=ModernUI.COLORS['text_primary'], bg=ModernUI.COLORS['bg_card']).pack()
        tk.Label(card.content, text="Deriv market analysis, bot controls, and live account metrics",
                 font=('Segoe UI', 10), fg=ModernUI.COLORS['text_secondary'], bg=ModernUI.COLORS['bg_card']).pack(pady=(4, 0))
        form = tk.Frame(card.content, bg=ModernUI.COLORS['bg_card'])
        form.pack(pady=20)
        tk.Label(form, text="Username", fg=ModernUI.COLORS['text_secondary'], bg=ModernUI.COLORS['bg_card']).grid(row=0, column=0, padx=5, pady=5, sticky='w')
        self.login_username = tk.Entry(form, width=25, bg=ModernUI.COLORS['bg_sidebar'], fg='white', insertbackground='white', bd=0)
        self.login_username.grid(row=0, column=1, padx=5, pady=5)
        ModernUI.add_glow_effect(self.login_username)
        tk.Label(form, text="Login Code", fg=ModernUI.COLORS['text_secondary'], bg=ModernUI.COLORS['bg_card']).grid(row=1, column=0, padx=5, pady=5, sticky='w')
        self.login_code = tk.Entry(form, width=25, show="*", bg=ModernUI.COLORS['bg_sidebar'], fg='white', insertbackground='white', bd=0)
        self.login_code.grid(row=1, column=1, padx=5, pady=5)
        ModernUI.add_glow_effect(self.login_code)

        self.login_username.bind('<Return>', lambda e: self.login())
        self.login_code.bind('<Return>', lambda e: self.login())

        btn_frame = tk.Frame(card.content, bg=ModernUI.COLORS['bg_card'])
        btn_frame.pack(pady=10)
        login_btn = ModernUI.create_gradient_button(btn_frame, "Login", self.login, 'primary')
        login_btn.pack(side=tk.LEFT, padx=5)
        register_btn = ModernUI.create_gradient_button(btn_frame, "Create Account", self.show_register, 'success')
        register_btn.pack(side=tk.LEFT, padx=5)
        forgot_btn = ModernUI.create_gradient_button(btn_frame, "Forgot Password?", self.show_password_reset, 'info')
        forgot_btn.pack(side=tk.LEFT, padx=5)
        self.login_message = tk.Label(card.content, text="", fg=ModernUI.COLORS['accent_danger'], bg=ModernUI.COLORS['bg_card'])
        self.login_message.pack(pady=10)

        self.login_username.focus_set()

    def login(self):
        username = self.login_username.get().strip()
        code = self.login_code.get().strip()
        if not username or not code:
            self.login_message.config(text="Username and login code required")
            return
        try:
            success, msg, user = self.user_manager.login(username, code)
            if success:
                self.current_user = user
                self.is_logged_in = True
                self.show_main_app()
            else:
                self.login_message.config(text=msg)
        except Exception as e:
            self.login_message.config(text="Network error. Please check your connection.")
            print(f"Login error: {e}")

    def show_register(self):
        win = tk.Toplevel(self.root)
        win.title("Create Account")
        win.geometry("450x550")
        win.configure(bg=ModernUI.COLORS['bg_dark'])
        win.transient(self.root)
        win.grab_set()
        card = ModernCard(win, title="Register")
        card.pack(fill='both', expand=True, padx=20, pady=20)
        form = tk.Frame(card.content, bg=ModernUI.COLORS['bg_card'])
        form.pack(pady=10)
        fields = [("Username", "reg_username"), ("Email", "reg_email"), ("Phone (+254...)", "reg_phone"), ("Password", "reg_password"), ("Confirm", "reg_confirm")]
        entries = {}
        for i, (label, key) in enumerate(fields):
            tk.Label(form, text=label, fg=ModernUI.COLORS['text_secondary'], bg=ModernUI.COLORS['bg_card']).grid(row=i, column=0, padx=5, pady=5, sticky='w')
            ent = tk.Entry(form, width=30, bg=ModernUI.COLORS['bg_sidebar'], fg='white', insertbackground='white', bd=0, show="*" if "password" in key else "")
            ent.grid(row=i, column=1, padx=5, pady=5)
            ModernUI.add_glow_effect(ent)
            entries[key] = ent
        msg_label = tk.Label(card.content, text="", fg=ModernUI.COLORS['accent_danger'], bg=ModernUI.COLORS['bg_card'])
        msg_label.pack(pady=10)
        def do_register():
            username = entries['reg_username'].get().strip()
            email = entries['reg_email'].get().strip()
            phone = entries['reg_phone'].get().strip()
            pwd = entries['reg_password'].get()
            confirm = entries['reg_confirm'].get()
            if pwd != confirm:
                msg_label.config(text="Passwords do not match")
                return
            success, msg = self.user_manager.register_user(username, email, phone, pwd)
            if success:
                msg_label.config(text=msg, fg=ModernUI.COLORS['accent_success'])
                win.after(2000, win.destroy)
            else:
                msg_label.config(text=msg)
        btn = ModernUI.create_gradient_button(card.content, "Register", do_register, 'success')
        btn.pack(pady=10)

    def show_password_reset(self):
        win = tk.Toplevel(self.root)
        win.title("Reset Password")
        win.geometry("400x300")
        win.configure(bg=ModernUI.COLORS['bg_dark'])
        win.transient(self.root)
        win.grab_set()
        card = ModernCard(win, title="Reset Password")
        card.pack(fill='both', expand=True, padx=20, pady=20)
        tk.Label(card.content, text="Email:", fg=ModernUI.COLORS['text_secondary'], bg=ModernUI.COLORS['bg_card']).pack(anchor='w', pady=5)
        email_ent = tk.Entry(card.content, width=30, bg=ModernUI.COLORS['bg_sidebar'], fg='white', bd=0)
        email_ent.pack(fill='x', pady=5)
        ModernUI.add_glow_effect(email_ent)
        msg = tk.Label(card.content, text="", fg=ModernUI.COLORS['accent_danger'], bg=ModernUI.COLORS['bg_card'])
        msg.pack(pady=10)
        def do_reset():
            email = email_ent.get().strip()
            if not email:
                msg.config(text="Email required")
                return
            success, resp = self.user_manager.request_password_reset(email)
            msg.config(text=resp, fg=ModernUI.COLORS['accent_success'] if success else ModernUI.COLORS['accent_danger'])
            if success:
                win.after(3000, win.destroy)
        btn = ModernUI.create_gradient_button(card.content, "Send Reset Link", do_reset, 'primary')
        btn.pack(pady=10)

    # ---------- Helper Methods ----------
    def fetch_active_symbols(self, app_id: str):
        import requests
        try:
            url = f"https://api.binary.com/active_symbols?app_id={app_id}&product_type=basic"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if 'active_symbols' in data:
                    symbols = [s['symbol'] for s in data['active_symbols'] if not s.get('is_trading_suspended', 0)]
                    return sorted(symbols)
        except Exception as e:
            self.log(f"Symbol fetch error: {e}")
        return self.fallback_symbols

    def load_symbols_thread(self, app_id: str):
        symbols = self.fetch_active_symbols(app_id)
        self.root.after(0, lambda: self.symbol_combo.config(values=symbols))
        self.log(f"Loaded {len(symbols)} available symbols")

    def log(self, msg):
        self.log_queue.put(msg)

    def process_log_queue(self):
        while True:
            try:
                msg = self.log_queue.get_nowait()
                if self.log_text and self.log_text.winfo_exists():
                    self.log_text.config(state='normal')
                    self.log_text.insert('end', msg + "\n")
                    self.log_text.see('end')
                    self.log_text.config(state='normal')
            except queue.Empty:
                break
        self.root.after(100, self.process_log_queue)

    # ---------- Timestamp Formatting for Deriv Report Style ----------
    def _format_timestamp(self, timestamp) -> str:
        """Format timestamp to match Deriv report: '22 Apr 2026 13:40:15 GMT'"""
        if not timestamp:
            return "—"
        
        try:
            from datetime import datetime
            
            # If timestamp is a string, try to parse it
            if isinstance(timestamp, str):
                # Try different formats
                for fmt in ['%Y-%m-%d %H:%M:%S', '%d %b %Y %H:%M:%S GMT', '%Y-%m-%dT%H:%M:%S']:
                    try:
                        dt = datetime.strptime(timestamp, fmt)
                        return dt.strftime('%d %b %Y %H:%M:%S GMT')
                    except ValueError:
                        continue
                return timestamp
            
            # If timestamp is a number (Unix timestamp)
            if isinstance(timestamp, (int, float)):
                dt = datetime.fromtimestamp(timestamp)
                return dt.strftime('%d %b %Y %H:%M:%S GMT')
            
            return str(timestamp)
        except Exception:
            return str(timestamp)

    def _format_contract_type(self, contract_type: str) -> str:
        """Format contract type with icons like Deriv report."""
        if not contract_type:
            return "—"
        
        ct_lower = contract_type.lower()
        
        # Map contract types to display names with icons
        if 'digitover' in ct_lower or 'over' in ct_lower:
            return "⬆️ Over"
        elif 'digitunder' in ct_lower or 'under' in ct_lower:
            return "⬇️ Under"
        elif 'digiteven' in ct_lower or 'even' in ct_lower:
            return "🔵 Even"
        elif 'digitodd' in ct_lower or 'odd' in ct_lower:
            return "🔴 Odd"
        elif 'call' in ct_lower or 'rise' in ct_lower or 'higher' in ct_lower:
            return "📈 Rise"
        elif 'put' in ct_lower or 'fall' in ct_lower or 'lower' in ct_lower:
            return "📉 Fall"
        elif 'touch' in ct_lower and 'no' not in ct_lower:
            return "🎯 Touch"
        elif 'notouch' in ct_lower or 'no touch' in ct_lower:
            return "🚫 No Touch"
        elif 'classic' in ct_lower:
            return "Classic"
        elif 'iot' in ct_lower or 'sms' in ct_lower:
            return "IOT/SMS"
        elif '1m' in ct_lower:
            return "1m"
        else:
            # Return a shortened version for unknown types
            return contract_type[:12] if len(contract_type) > 12 else contract_type

    # ---------- Callbacks for Bot (with existence checks) ----------
    def update_balance(self, balance, currency):
        def _update():
            if self.ui_active and self.balance_label and self.balance_label.winfo_exists():
                self.balance_label.config(text=f"Balance: {balance:.2f} {currency}")
        self.root.after(0, _update)

    def update_stake_display(self, stake, level):
        def _update():
            if self.ui_active and self.stake_label and self.stake_label.winfo_exists():
                self.stake_label.config(text=f"Stake: {stake:.2f} (L{level})")
        self.root.after(0, _update)

    def update_signal(self, signal):
        def _update():
            if self.ui_active and self.signal_label and self.signal_label.winfo_exists():
                self.signal_label.config(text=f"Signal: {signal}")
        self.root.after(0, _update)

    def update_confidence(self, confidence):
        def _update():
            if self.ui_active and self.confidence_label and self.confidence_label.winfo_exists():
                self.confidence_label.config(text=f"Confidence: {confidence}%")
        self.root.after(0, _update)

    def update_digit_stats(self, stats_dict):
        color_map = {
            'red': '#FF5E7D', 'yellow': '#FFB443', 'blue': '#3FA2F7',
            'green': '#00D9A5', 'neutral': '#2E3F66'
        }
        def _update():
            if not self.ui_active or not hasattr(self, 'digit_labels'):
                return
            for d, (pct, color) in stats_dict.items():
                if d in self.digit_labels:
                    lbl, pct_lbl = self.digit_labels[d]
                    if lbl and lbl.winfo_exists() and pct_lbl and pct_lbl.winfo_exists():
                        bg_color = color_map.get(color, color_map['neutral'])
                        lbl.config(bg=bg_color)
                        pct_lbl.config(text=f"{pct:.1f}%")
        self.root.after(0, _update)

    def update_strategy_display(self, strategy):
        display_map = {"OVER": "Over 1-3", "UNDER": "Under 6-8", "EVEN": "Even", "ODD": "Odd"}
        display_name = display_map.get(strategy, strategy)
        def _update():
            if self.ui_active and hasattr(self, 'strategy_select_var') and self.strategy_select_var:
                self.strategy_select_var.set(display_name)
            self.log(f"🔄 Adaptive strategy changed to: {display_name}")
        self.root.after(0, _update)

    def update_positions_display(self, positions):
        def _update():
            if not self.ui_active or not self.positions_tree or not self.positions_tree.winfo_exists():
                return
            for item in self.positions_tree.get_children():
                self.positions_tree.delete(item)
            for pos in positions:
                values = (
                    pos.get('contract_id', ''),
                    pos.get('contract_type', ''),
                    f"{pos.get('buy_price', 0):.2f}",
                    f"{pos.get('current_price', 0):.2f}",
                    f"{pos.get('payout', 0):.2f}",
                    f"{pos.get('profit_loss', 0):.2f}",
                    pos.get('status', ''),
                )
                item = self.positions_tree.insert('', 'end', values=values)
                pl = pos.get('profit_loss', 0)
                if pl > 0:
                    self.positions_tree.tag_configure('profit', foreground='#00D9A5')
                    self.positions_tree.item(item, tags=('profit',))
                elif pl < 0:
                    self.positions_tree.tag_configure('loss', foreground='#FF5E7D')
                    self.positions_tree.item(item, tags=('loss',))
        self.root.after(0, _update)

    def update_trade_history(self, trades):
        def _update():
            if not self.ui_active or not self.history_tree or not self.history_tree.winfo_exists():
                return
            for item in self.history_tree.get_children():
                self.history_tree.delete(item)
            
            # Configure tags for profit/loss coloring
            self.history_tree.tag_configure('profit', foreground='#00D9A5')  # Green for profit
            self.history_tree.tag_configure('loss', foreground='#FF5E7D')    # Red for loss
            self.history_tree.tag_configure('neutral', foreground='#E0E7FF') # White for neutral
            
            for trade in trades:
                currency = trade.get('currency', 'USD')
                stake = trade.get('stake', trade.get('buy_price', 0))
                try:
                    stake_str = f"{float(stake):.2f}" if stake else "0.00"
                except (ValueError, TypeError):
                    stake_str = "0.00"

                contract_value = trade.get('contract_value', trade.get('payout', trade.get('sell_price', 0)))
                try:
                    contract_val = float(contract_value) if contract_value else 0.0
                    contract_str = f"{contract_val:.2f}"
                except (ValueError, TypeError):
                    contract_val = 0.0
                    contract_str = "0.00"

                profit = trade.get('profit_loss', 0)
                try:
                    profit_val = float(profit) if profit else 0.0
                    if profit_val == 0.0 and (contract_val or float(stake or 0)):
                        profit_val = contract_val - float(stake or 0)
                    profit_str = f"{profit_val:+.2f}" if profit_val else "0.00"
                except (ValueError, TypeError):
                    try:
                        profit_val = contract_val - float(stake or 0)
                        profit_str = f"{profit_val:+.2f}" if profit_val else "0.00"
                    except (ValueError, TypeError):
                        profit_val = 0.0
                        profit_str = "0.00"
                
                values = (
                    currency,
                    stake_str,
                    contract_str,
                    profit_str
                )
                
                item = self.history_tree.insert('', 'end', values=values)
                
                # Apply color based on profit/loss
                if profit_val > 0:
                    self.history_tree.item(item, tags=('profit',))
                elif profit_val < 0:
                    self.history_tree.item(item, tags=('loss',))
                else:
                    self.history_tree.item(item, tags=('neutral',))
                    
        self.root.after(0, _update)

    def refresh_trade_history(self):
        if self.bot and self.loop:
            asyncio.run_coroutine_threadsafe(self.bot.get_trade_history(limit=50), self.loop)

    def on_strategy_change(self, event=None):
        strategy = self.strategy_select_var.get()
        if strategy in ["Over 1-3", "Under 6-8", "Even", "Odd"]:
            self.timeframe_label.grid_remove()
            self.timeframe_combo.grid_remove()
            self.duration_label.grid_remove()
            self.duration_entry.grid_remove()
            self.ticks_duration_label.grid()
            self.ticks_duration_entry.grid()
            self.confirmations_label.grid_remove()
            self.confirmations_spinbox.grid_remove()
        else:
            self.timeframe_label.grid()
            self.timeframe_combo.grid()
            self.duration_label.grid()
            self.duration_entry.grid()
            self.ticks_duration_label.grid_remove()
            self.ticks_duration_entry.grid_remove()
            self.confirmations_label.grid()
            self.confirmations_spinbox.grid()

    def on_mode_change(self):
        if self.bot:
            mode = self.mode_var.get()
            self.bot.set_mode(mode)

    def on_manual_contract_change(self, event=None):
        contract = self.manual_contract_var.get()
        self.manual_btn1.pack_forget()
        self.manual_btn2.pack_forget()
        if contract == "Rise/Fall":
            self.manual_duration_label.config(text="Duration (min):")
            self.manual_btn1.config(text="BUY", command=self.manual_rise)
            self.manual_btn2.config(text="SELL", command=self.manual_fall)
        elif contract == "Higher/Lower":
            self.manual_duration_label.config(text="Duration (min):")
            self.manual_btn1.config(text="HIGHER", command=self.manual_higher)
            self.manual_btn2.config(text="LOWER", command=self.manual_lower)
        elif contract == "Touch/No Touch":
            self.manual_duration_label.config(text="Duration (min):")
            self.manual_btn1.config(text="TOUCH", command=self.manual_touch)
            self.manual_btn2.config(text="NO TOUCH", command=self.manual_no_touch)
        elif contract == "Even/Odd":
            self.manual_duration_label.config(text="Duration (ticks):")
            self.manual_btn1.config(text="EVEN", command=self.manual_even)
            self.manual_btn2.config(text="ODD", command=self.manual_odd)
        elif contract == "Over/Under":
            self.manual_duration_label.config(text="Duration (ticks):")
            self.manual_btn1.config(text="OVER 1-3", command=self.manual_over)
            self.manual_btn2.config(text="UNDER 6-8", command=self.manual_under)
        self.manual_btn1.pack(side='left', padx=5)
        self.manual_btn2.pack(side='left', padx=5)

    def _execute_manual_trade(self, contract_type: str, barrier: str = None):
        if not self.bot or not self.bot.ws:
            messagebox.showerror("Error", "Bot is not running. Please run the bot first.")
            return
        try:
            stake = float(self.manual_stake_var.get())
            duration = int(self.manual_duration_var.get())
        except ValueError:
            messagebox.showerror("Error", "Invalid stake or duration.")
            return
        contract = self.manual_contract_var.get()
        duration_unit = "t" if contract in ["Even/Odd", "Over/Under"] else "m"
        asyncio.run_coroutine_threadsafe(
            self.bot.manual_trade_generic(contract_type, stake, duration, duration_unit, barrier),
            self.loop
        )

    def manual_rise(self): self._execute_manual_trade("CALL")
    def manual_fall(self): self._execute_manual_trade("PUT")
    def manual_higher(self): self._execute_manual_trade("CALL")
    def manual_lower(self): self._execute_manual_trade("PUT")
    def manual_touch(self): self._execute_manual_trade("ONETOUCH", "+0.005")
    def manual_no_touch(self): self._execute_manual_trade("NOTOUCH", "+0.005")
    def manual_even(self): self._execute_manual_trade("DIGITEVEN")
    def manual_odd(self): self._execute_manual_trade("DIGITODD")
    def manual_over(self): self._execute_manual_trade("DIGITOVER", "3")
    def manual_under(self): self._execute_manual_trade("DIGITUNDER", "6")

    def close_position(self):
        selection = self.positions_tree.selection()
        if not selection:
            messagebox.showwarning("No selection", "Please select a position to close.")
            return
        item = self.positions_tree.item(selection[0])
        values = item['values']
        contract_id = values[0]
        if not contract_id:
            return
        if messagebox.askyesno("Confirm Close", f"Close position {contract_id}?"):
            asyncio.run_coroutine_threadsafe(self.bot.close_position(int(contract_id)), self.loop)

    def start_bot(self):
        token = self.token_var.get().strip() or self.session_api_token
        if not token:
            messagebox.showerror("Error", "API Token required")
            return
        self.session_api_token = token
        try:
            app_id = int(self.app_id_var.get())
            symbol = self.symbol_var.get()
            timeframe_str = self.timeframe_var.get()
            granularity = self.timeframe_options.get(timeframe_str, 60)
            base_stake = float(self.stake_var.get())
            duration = int(self.duration_var.get())
            cooldown = int(self.cooldown_var.get())
            max_loss = float(self.max_loss_var.get())
            mult = float(self.mult_var.get())
            max_steps = int(self.max_steps_var.get())
            confirmations = int(self.confirmations_var.get())
            strategy = self.strategy_select_var.get()
            martingale_mode = self.martingale_mode_var.get()
            ticks_duration = int(self.ticks_duration_var.get()) if strategy in ["Over 1-3", "Under 6-8", "Even", "Odd"] else 5
        except ValueError as e:
            messagebox.showerror("Error", f"Invalid input: {e}")
            return

        config = BotConfig(
            symbol=symbol,
            granularity_seconds=granularity,
            base_stake=base_stake,
            duration=duration,
            ticks_duration=ticks_duration,
            cooldown=cooldown,
            max_daily_loss=max_loss,
            martingale_mult=mult,
            max_martingale_steps=max_steps,
            martingale_mode=martingale_mode,
            confirmations_required=confirmations,
            selected_strategy=strategy,
            timeframe=timeframe_str
        )

        self.bot = DerivBot(token, config,
                            log_callback=self.log, balance_callback=self.update_balance,
                            stake_callback=self.update_stake_display,
                            signal_callback=self.update_signal, confidence_callback=self.update_confidence,
                            digit_stats_callback=self.update_digit_stats,
                            strategy_update_callback=self.update_strategy_display,
                            positions_callback=self.update_positions_display,
                            trade_history_callback=self.update_trade_history)
        self.loop = asyncio.new_event_loop()
        self.bot.set_event_loop(self.loop)
        initial_mode = self.mode_var.get()
        self.bot.set_mode(initial_mode)

        def run_loop():
            asyncio.set_event_loop(self.loop)
            self.loop.run_until_complete(self.bot.run_bot())

        self.bot_thread = threading.Thread(target=run_loop, daemon=True)
        self.bot_thread.start()

        self.start_btn.config(state='disabled')
        self.stop_btn.config(state='normal')
        self.log(f"🚀 Bot started in {initial_mode} mode with strategy: {strategy}")

    def stop_bot(self):
        if self.bot and self.loop:
            future = asyncio.run_coroutine_threadsafe(self.bot.stop(), self.loop)
            try:
                future.result(timeout=5)
            except Exception as e:
                self.log(f"Stop error: {e}")
        self.bot = None
        if self.start_btn and self.start_btn.winfo_exists():
            self.start_btn.config(state='normal')
        if self.stop_btn and self.stop_btn.winfo_exists():
            self.stop_btn.config(state='disabled')
        self.log("🛑 Bot stopped")

    def reset_martingale(self):
        if self.bot and self.loop:
            asyncio.run_coroutine_threadsafe(self.bot.reset_martingale(), self.loop)
            self.log("🔄 Martingale reset requested.")
        else:
            self.log("Bot not running, cannot reset martingale.")

    def on_closing(self):
        self.ui_active = False
        self.stop_bot()
        self.root.destroy()

    # ---------- Keyboard navigation methods ----------
    def setup_keyboard_navigation(self):
        focusable_widgets = []
        def collect_focusable(widget):
            if isinstance(widget, (tk.Entry, ttk.Combobox, tk.Spinbox)):
                focusable_widgets.append(widget)
            for child in widget.winfo_children():
                collect_focusable(child)
        if hasattr(self, 'settings_scroll'):
            collect_focusable(self.settings_scroll)
        for i, w in enumerate(focusable_widgets):
            def make_focus_next(idx):
                def fn(event):
                    next_idx = (idx + 1) % len(focusable_widgets)
                    focusable_widgets[next_idx].focus_set()
                    return 'break'
                return fn
            def make_focus_prev(idx):
                def fn(event):
                    prev_idx = (idx - 1) % len(focusable_widgets)
                    focusable_widgets[prev_idx].focus_set()
                    return 'break'
                return fn
            w.bind('<Down>', make_focus_next(i))
            w.bind('<Up>', make_focus_prev(i))

    def bind_scroll_keys(self, canvas):
        def scroll_up(event):
            canvas.yview_scroll(-1, 'units')
        def scroll_down(event):
            canvas.yview_scroll(1, 'units')
        def scroll_page_up(event):
            canvas.yview_scroll(-1, 'pages')
        def scroll_page_down(event):
            canvas.yview_scroll(1, 'pages')
        def scroll_home(event):
            canvas.yview_moveto(0)
        def scroll_end(event):
            canvas.yview_moveto(1)
        canvas.bind('<Up>', scroll_up)
        canvas.bind('<Down>', scroll_down)
        canvas.bind('<Prior>', scroll_page_up)
        canvas.bind('<Next>', scroll_page_down)
        canvas.bind('<Home>', scroll_home)
        canvas.bind('<End>', scroll_end)
        canvas.focus_set()

    # ---------- Toggle show/hide secrets ----------
    def toggle_secrets_visibility(self):
        if self.show_secrets_var.get():
            self.app_id_entry.config(show="")
            self.token_entry.config(show="")
        else:
            self.app_id_entry.config(show="*")
            self.token_entry.config(show="*")

    # ---------- Main App UI ----------
    def show_main_app(self):
        self.ui_active = True
        for widget in self.root.winfo_children():
            widget.destroy()
        self.root.configure(bg=ModernUI.COLORS['bg_dark'])
        ModernUI.configure_ttk_styles(self.root)

        # Top bar
        top_frame = tk.Frame(
            self.root,
            bg=ModernUI.COLORS['bg_card'],
            height=72,
            highlightbackground=ModernUI.COLORS['border'],
            highlightthickness=1,
        )
        top_frame.pack(fill='x', padx=10, pady=(10, 5))
        if self.logo_image:
            logo_label = tk.Label(top_frame, image=self.logo_image, bg=ModernUI.COLORS['bg_card'])
            logo_label.pack(side='left', padx=(14, 10), pady=8)
        brand_frame = tk.Frame(top_frame, bg=ModernUI.COLORS['bg_card'])
        brand_frame.pack(side='left', padx=4, pady=8)
        tk.Label(brand_frame, text="UWEZO-FX DERIV BOT", font=('Montserrat', 17, 'bold'),
                 fg=ModernUI.COLORS['accent_primary'], bg=ModernUI.COLORS['bg_card']).pack(anchor='w')
        tk.Label(brand_frame, text="Deriv analysis and execution console", font=('Segoe UI', 9),
                 fg=ModernUI.COLORS['text_secondary'], bg=ModernUI.COLORS['bg_card']).pack(anchor='w')
        tk.Label(top_frame, text=f"Welcome, {self.current_user.get('username', 'Trader')}",
                 fg=ModernUI.COLORS['text_secondary'], bg=ModernUI.COLORS['bg_card'],
                 font=('Segoe UI', 9, 'bold')).pack(side='right', padx=10)
        logout_btn = ModernUI.create_gradient_button(top_frame, "Logout", self.logout, 'danger')
        logout_btn.pack(side='right', padx=10, pady=5)

        # Main container
        main_pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg=ModernUI.COLORS['bg_dark'], sashrelief='raised')
        main_pane.pack(fill='both', expand=True, padx=10, pady=(0, 10))

        # LEFT: SETTINGS + MANUAL TRADE
        left_frame = tk.Frame(main_pane, bg=ModernUI.COLORS['bg_dark'], width=500)
        main_pane.add(left_frame, width=500)

        settings_card = ModernCard(left_frame, title="BOT SETTINGS")
        settings_card.pack(fill='both', expand=True)

        settings_canvas = tk.Canvas(settings_card.content, bg=ModernUI.COLORS['bg_card'], highlightthickness=0)
        scrollbar = tk.Scrollbar(settings_card.content, orient=tk.VERTICAL, command=settings_canvas.yview)
        settings_scroll = tk.Frame(settings_canvas, bg=ModernUI.COLORS['bg_card'])
        settings_canvas.create_window((0,0), window=settings_scroll, anchor='nw')
        settings_canvas.configure(yscrollcommand=scrollbar.set)
        settings_canvas.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        self.settings_scroll = settings_scroll
        self.bind_scroll_keys(settings_canvas)

        row = 0
        LABEL_WIDTH = 18

        def add_label_entry(parent, text, var, width=10, show=None):
            nonlocal row
            f = tk.Frame(parent, bg=ModernUI.COLORS['bg_card'])
            f.grid(row=row, column=0, sticky='ew', padx=5, pady=2)
            tk.Label(f, text=text, fg=ModernUI.COLORS['text_secondary'], bg=ModernUI.COLORS['bg_card'],
                     font=('Segoe UI', 9), width=LABEL_WIDTH, anchor='w').pack(side='left', padx=(0,5))
            e = tk.Entry(f, textvariable=var, width=width, bg=ModernUI.COLORS['bg_sidebar'], fg='white', bd=0,
                         font=('Segoe UI', 9), show=show)
            e.pack(side='left', fill='x', expand=True)
            ModernUI.add_glow_effect(e)
            row += 1
            return e

        def add_label_combo(parent, text, var, values, width=12):
            nonlocal row
            f = tk.Frame(parent, bg=ModernUI.COLORS['bg_card'])
            f.grid(row=row, column=0, sticky='ew', padx=5, pady=2)
            tk.Label(f, text=text, fg=ModernUI.COLORS['text_secondary'], bg=ModernUI.COLORS['bg_card'],
                     font=('Segoe UI', 9), width=LABEL_WIDTH, anchor='w').pack(side='left', padx=(0,5))
            c = ttk.Combobox(f, textvariable=var, values=values, width=width, font=('Segoe UI', 9), state='readonly')
            c.pack(side='left', fill='x', expand=True)
            row += 1
            return c

        self.app_id_var = tk.StringVar(value=str(Settings.DERIV_APP_ID))
        self.app_id_entry = add_label_entry(settings_scroll, "App ID:", self.app_id_var, 10, show="*")
        self.token_var = tk.StringVar(value=self.session_api_token)
        self.token_entry = add_label_entry(settings_scroll, "API Token:", self.token_var, 30, show="*")
        tk.Label(settings_scroll, text="Token stays active until logout.", fg=ModernUI.COLORS['text_muted'],
                 bg=ModernUI.COLORS['bg_card'], font=('Segoe UI', 8)).grid(row=row, column=0, sticky='w', padx=10, pady=(0, 4))
        row += 1

        self.show_secrets_var = tk.BooleanVar(value=False)
        show_cb = tk.Checkbutton(settings_scroll, text="Show secrets", variable=self.show_secrets_var,
                                 command=self.toggle_secrets_visibility,
                                 fg=ModernUI.COLORS['text_secondary'], bg=ModernUI.COLORS['bg_card'],
                                 selectcolor=ModernUI.COLORS['bg_sidebar'], font=('Segoe UI', 8))
        show_cb.grid(row=row, column=0, sticky='w', padx=5, pady=2)
        row += 1

        self.symbol_var = tk.StringVar(value="R_100")
        self.symbol_combo = add_label_combo(settings_scroll, "Symbol:", self.symbol_var, self.fallback_symbols, 20)

        self.stake_var = tk.StringVar(value="1.0")
        add_label_entry(settings_scroll, "Base Stake:", self.stake_var, 8)

        self.cooldown_var = tk.StringVar(value="60")
        add_label_entry(settings_scroll, "Cooldown (s):", self.cooldown_var, 6)

        self.max_loss_var = tk.StringVar(value="50.0")
        add_label_entry(settings_scroll, "Max Daily Loss:", self.max_loss_var, 8)

        self.mult_var = tk.StringVar(value="2.5")
        add_label_entry(settings_scroll, "Martingale Mult:", self.mult_var, 6)

        self.max_steps_var = tk.StringVar(value="4")
        add_label_entry(settings_scroll, "Max Steps:", self.max_steps_var, 4)

        self.martingale_mode_var = tk.StringVar(value="Classic")
        add_label_combo(settings_scroll, "Martingale Mode:", self.martingale_mode_var, ["Classic", "Reverse"], 10)

        self.strategy_select_var = tk.StringVar(value="ICT/SMS")
        strategy_combo = add_label_combo(settings_scroll, "Strategy:", self.strategy_select_var,
                                         ["ICT/SMS", "Over 1-3", "Under 6-8", "Even", "Odd"], 12)
        strategy_combo.bind('<<ComboboxSelected>>', self.on_strategy_change)

        self.duration_label = tk.Label(settings_scroll, text="Duration (min):", fg=ModernUI.COLORS['text_secondary'],
                                       bg=ModernUI.COLORS['bg_card'], font=('Segoe UI', 9), width=LABEL_WIDTH, anchor='w')
        self.duration_label.grid(row=row, column=0, sticky='w', padx=10, pady=2)
        self.duration_var = tk.StringVar(value="1")
        self.duration_entry = tk.Entry(settings_scroll, textvariable=self.duration_var, width=5,
                                       bg=ModernUI.COLORS['bg_sidebar'], fg='white', bd=0, font=('Segoe UI', 9))
        self.duration_entry.grid(row=row, column=0, sticky='e', padx=(LABEL_WIDTH*7+20, 5), pady=2)
        row += 1

        self.ticks_duration_label = tk.Label(settings_scroll, text="Duration (ticks):", fg=ModernUI.COLORS['text_secondary'],
                                             bg=ModernUI.COLORS['bg_card'], font=('Segoe UI', 9), width=LABEL_WIDTH, anchor='w')
        self.ticks_duration_label.grid(row=row, column=0, sticky='w', padx=10, pady=2)
        self.ticks_duration_var = tk.StringVar(value="5")
        self.ticks_duration_entry = tk.Entry(settings_scroll, textvariable=self.ticks_duration_var, width=5,
                                             bg=ModernUI.COLORS['bg_sidebar'], fg='white', bd=0, font=('Segoe UI', 9))
        self.ticks_duration_entry.grid(row=row, column=0, sticky='e', padx=(LABEL_WIDTH*7+20, 5), pady=2)
        self.ticks_duration_label.grid_remove()
        self.ticks_duration_entry.grid_remove()
        row += 1

        self.timeframe_label = tk.Label(settings_scroll, text="Timeframe:", fg=ModernUI.COLORS['text_secondary'],
                                        bg=ModernUI.COLORS['bg_card'], font=('Segoe UI', 9), width=LABEL_WIDTH, anchor='w')
        self.timeframe_label.grid(row=row, column=0, sticky='w', padx=10, pady=2)
        self.timeframe_var = tk.StringVar(value="1m")
        self.timeframe_combo = ttk.Combobox(settings_scroll, textvariable=self.timeframe_var,
                                            values=list(self.timeframe_options.keys()), width=8, font=('Segoe UI', 9))
        self.timeframe_combo.grid(row=row, column=0, sticky='e', padx=(LABEL_WIDTH*7+20, 5), pady=2)
        row += 1

        self.confirmations_label = tk.Label(settings_scroll, text="Confirmations:", fg=ModernUI.COLORS['text_secondary'],
                                            bg=ModernUI.COLORS['bg_card'], font=('Segoe UI', 9), width=LABEL_WIDTH, anchor='w')
        self.confirmations_label.grid(row=row, column=0, sticky='w', padx=10, pady=2)
        self.confirmations_var = tk.StringVar(value="2")
        self.confirmations_spinbox = tk.Spinbox(settings_scroll, from_=1, to=10, textvariable=self.confirmations_var, width=3,
                                                bg=ModernUI.COLORS['bg_sidebar'], fg='white', bd=0, font=('Segoe UI', 9))
        self.confirmations_spinbox.grid(row=row, column=0, sticky='e', padx=(LABEL_WIDTH*7+20, 5), pady=2)
        row += 1

        self.mode_var = tk.StringVar(value="Monitor")
        mode_frame = tk.Frame(settings_scroll, bg=ModernUI.COLORS['bg_card'])
        mode_frame.grid(row=row, column=0, columnspan=2, sticky='ew', padx=5, pady=5)
        tk.Label(mode_frame, text="Mode:", fg=ModernUI.COLORS['text_secondary'], bg=ModernUI.COLORS['bg_card'], font=('Segoe UI', 9)).pack(side='left', padx=5)
        for mode in ["Monitor", "Auto-Trade", "Adaptive"]:
            rb = tk.Radiobutton(mode_frame, text=mode, variable=self.mode_var, value=mode,
                                fg='white', bg=ModernUI.COLORS['bg_card'], selectcolor=ModernUI.COLORS['bg_sidebar'],
                                activebackground=ModernUI.COLORS['bg_card'], command=self.on_mode_change,
                                font=('Segoe UI', 8))
            rb.pack(side='left', padx=5)
        row += 1

        btn_frame = tk.Frame(settings_scroll, bg=ModernUI.COLORS['bg_card'])
        btn_frame.grid(row=row, column=0, columnspan=2, pady=10)
        self.start_btn = ModernUI.create_gradient_button(btn_frame, "RUN BOT", self.start_bot, 'success')
        self.start_btn.pack(side='left', padx=5)
        self.stop_btn = ModernUI.create_gradient_button(btn_frame, "STOP BOT", self.stop_bot, 'danger')
        self.stop_btn.pack(side='left', padx=5)
        self.stop_btn.config(state='disabled')
        reset_mart_btn = ModernUI.create_gradient_button(btn_frame, "RESET MARTINGALE", self.reset_martingale, 'warning')
        reset_mart_btn.pack(side='left', padx=5)
        row += 1

        # Manual Trade Section
        ttk.Separator(settings_scroll, orient='horizontal').grid(row=row, column=0, columnspan=2, sticky='ew', pady=10)
        row += 1
        tk.Label(settings_scroll, text="MANUAL TRADING", fg=ModernUI.COLORS['accent_primary'],
                 bg=ModernUI.COLORS['bg_card'], font=('Montserrat', 10, 'bold')).grid(row=row, column=0, columnspan=2, pady=(0,5))
        row += 1

        contract_frame = tk.Frame(settings_scroll, bg=ModernUI.COLORS['bg_card'])
        contract_frame.grid(row=row, column=0, columnspan=2, sticky='ew', padx=5, pady=2)
        tk.Label(contract_frame, text="Contract:", fg=ModernUI.COLORS['text_secondary'],
                 bg=ModernUI.COLORS['bg_card'], font=('Segoe UI', 9), width=LABEL_WIDTH, anchor='w').pack(side='left', padx=(0,5))
        self.manual_contract_var = tk.StringVar(value="Rise/Fall")
        contract_combo = ttk.Combobox(contract_frame, textvariable=self.manual_contract_var,
                                      values=["Rise/Fall", "Higher/Lower", "Touch/No Touch", "Even/Odd", "Over/Under"],
                                      width=20, font=('Segoe UI', 9), state='readonly')
        contract_combo.pack(side='left', fill='x', expand=True)
        contract_combo.bind('<<ComboboxSelected>>', self.on_manual_contract_change)
        row += 1

        stake_frame = tk.Frame(settings_scroll, bg=ModernUI.COLORS['bg_card'])
        stake_frame.grid(row=row, column=0, columnspan=2, sticky='ew', padx=5, pady=2)
        tk.Label(stake_frame, text="Stake:", fg=ModernUI.COLORS['text_secondary'],
                 bg=ModernUI.COLORS['bg_card'], font=('Segoe UI', 9), width=LABEL_WIDTH, anchor='w').pack(side='left', padx=(0,5))
        self.manual_stake_var = tk.StringVar(value="1.0")
        tk.Entry(stake_frame, textvariable=self.manual_stake_var, width=10, bg=ModernUI.COLORS['bg_sidebar'],
                 fg='white', bd=0, font=('Segoe UI', 9)).pack(side='left', fill='x', expand=True)
        row += 1

        duration_frame = tk.Frame(settings_scroll, bg=ModernUI.COLORS['bg_card'])
        duration_frame.grid(row=row, column=0, columnspan=2, sticky='ew', padx=5, pady=2)
        self.manual_duration_label = tk.Label(duration_frame, text="Duration (min):", fg=ModernUI.COLORS['text_secondary'],
                                              bg=ModernUI.COLORS['bg_card'], font=('Segoe UI', 9), width=LABEL_WIDTH, anchor='w')
        self.manual_duration_label.pack(side='left', padx=(0,5))
        self.manual_duration_var = tk.StringVar(value="1")
        tk.Entry(duration_frame, textvariable=self.manual_duration_var, width=5, bg=ModernUI.COLORS['bg_sidebar'],
                 fg='white', bd=0, font=('Segoe UI', 9)).pack(side='left', fill='x', expand=True)
        row += 1

        man_btn_frame = tk.Frame(settings_scroll, bg=ModernUI.COLORS['bg_card'])
        man_btn_frame.grid(row=row, column=0, columnspan=2, pady=10)
        self.manual_btn1 = ModernUI.create_gradient_button(man_btn_frame, "BUY", self.manual_rise, 'success')
        self.manual_btn1.pack(side='left', padx=5)
        self.manual_btn2 = ModernUI.create_gradient_button(man_btn_frame, "SELL", self.manual_fall, 'danger')
        self.manual_btn2.pack(side='left', padx=5)
        row += 1

        settings_scroll.update_idletasks()
        settings_canvas.configure(scrollregion=settings_canvas.bbox('all'))
        self.setup_keyboard_navigation()

        # RIGHT: DASHBOARD
        right_frame = tk.Frame(main_pane, bg=ModernUI.COLORS['bg_dark'])
        main_pane.add(right_frame, width=900)

        status_frame = tk.Frame(right_frame, bg=ModernUI.COLORS['bg_dark'], height=46)
        status_frame.pack(fill='x', pady=(0, 8))

        def make_metric(parent, text, color):
            label = tk.Label(
                parent,
                text=text,
                fg=color,
                bg=ModernUI.COLORS['bg_sidebar'],
                font=('Segoe UI', 9, 'bold'),
                padx=12,
                pady=8,
                highlightbackground=ModernUI.COLORS['border'],
                highlightthickness=1,
            )
            label.pack(side='left', padx=(0, 8), fill='x')
            return label

        self.balance_label = make_metric(status_frame, "Balance: --", ModernUI.COLORS['accent_success'])
        self.stake_label = make_metric(status_frame, "Stake: --", ModernUI.COLORS['accent_info'])
        self.signal_label = make_metric(status_frame, "Signal: --", ModernUI.COLORS['accent_warning'])
        self.confidence_label = make_metric(status_frame, "Confidence: --", ModernUI.COLORS['accent_primary'])

        notebook = ttk.Notebook(right_frame)
        notebook.pack(fill='both', expand=True)

        positions_tab = tk.Frame(notebook, bg=ModernUI.COLORS['bg_dark'])
        notebook.add(positions_tab, text="Positions/History")
        sub_notebook = ttk.Notebook(positions_tab)
        sub_notebook.pack(fill='both', expand=True)

        open_pos_frame = tk.Frame(sub_notebook, bg=ModernUI.COLORS['bg_dark'])
        sub_notebook.add(open_pos_frame, text="Open Positions")
        pos_frame = tk.Frame(open_pos_frame, bg=ModernUI.COLORS['bg_card'])
        pos_frame.pack(fill='both', expand=True, padx=5, pady=5)
        columns = ('ID', 'Type', 'Buy Price', 'Current', 'Payout', 'P&L', 'Status')
        self.positions_tree = ttk.Treeview(pos_frame, columns=columns, show='headings', height=12)
        for col in columns:
            self.positions_tree.heading(col, text=col)
            self.positions_tree.column(col, width=90)
        self.positions_tree.pack(side='left', fill='both', expand=True)
        scroll_pos = ttk.Scrollbar(pos_frame, orient='vertical', command=self.positions_tree.yview)
        scroll_pos.pack(side='right', fill='y')
        self.positions_tree.configure(yscrollcommand=scroll_pos.set)
        close_btn = ModernUI.create_gradient_button(pos_frame, "❌ Close Selected", self.close_position, 'danger')
        close_btn.pack(pady=5)

        history_frame = tk.Frame(sub_notebook, bg=ModernUI.COLORS['bg_dark'])
        sub_notebook.add(history_frame, text="Trade History")
        hist_panel = tk.Frame(history_frame, bg=ModernUI.COLORS['bg_card'])
        hist_panel.pack(fill='both', expand=True, padx=5, pady=5)
        hist_btn_frame = tk.Frame(hist_panel, bg=ModernUI.COLORS['bg_card'])
        hist_btn_frame.pack(fill='x', pady=5)
        refresh_hist_btn = ModernUI.create_gradient_button(hist_btn_frame, "Refresh History", self.refresh_trade_history, 'info')
        refresh_hist_btn.pack(side='left', padx=5)

        hist_tree_frame = tk.Frame(hist_panel, bg=ModernUI.COLORS['bg_card'])
        hist_tree_frame.pack(fill='both', expand=True)
        
        hist_columns = ('Currency', 'Stake', 'Contract', 'Profit/Loss')
        self.history_tree = ttk.Treeview(hist_tree_frame, columns=hist_columns, show='headings', height=12)
        
        col_config = {
            'Currency': {'width': 90, 'anchor': 'center'},
            'Stake': {'width': 110, 'anchor': 'e'},
            'Contract': {'width': 120, 'anchor': 'e'},
            'Profit/Loss': {'width': 120, 'anchor': 'e'},
        }

        for col in hist_columns:
            self.history_tree.heading(col, text=col)
            self.history_tree.column(col, 
                                     width=col_config[col]['width'], 
                                     anchor=col_config[col]['anchor'],
                                     minwidth=50)
        
        self.history_tree.pack(side='left', fill='both', expand=True)
        
        # Scrollbars
        scroll_hist_v = ttk.Scrollbar(hist_tree_frame, orient='vertical', command=self.history_tree.yview)
        scroll_hist_v.pack(side='right', fill='y')
        scroll_hist_h = ttk.Scrollbar(hist_panel, orient='horizontal', command=self.history_tree.xview)
        scroll_hist_h.pack(side='bottom', fill='x')
        self.history_tree.configure(yscrollcommand=scroll_hist_v.set, xscrollcommand=scroll_hist_h.set)

        stats_tab = tk.Frame(notebook, bg=ModernUI.COLORS['bg_dark'])
        notebook.add(stats_tab, text="Digit Stats")
        stats_card_inner = ModernCard(stats_tab, title=None)
        stats_card_inner.pack(fill='both', expand=True, padx=5, pady=5)
        self.digit_labels = {}
        stats_grid = tk.Frame(stats_card_inner.content, bg=ModernUI.COLORS['bg_card'])
        stats_grid.pack(fill='both', expand=True)
        color_map = {'red': '#FF5E7D', 'yellow': '#FFB443', 'blue': '#3FA2F7', 'green': '#00D9A5', 'neutral': '#2E3F66'}
        for d in range(10):
            row_idx = d // 5
            col_idx = d % 5
            frame = tk.Frame(stats_grid, bg=ModernUI.COLORS['bg_card'], highlightbackground=ModernUI.COLORS['border'], highlightthickness=1)
            frame.grid(row=row_idx, column=col_idx, padx=2, pady=2, sticky='nsew')
            stats_grid.columnconfigure(col_idx, weight=1)
            stats_grid.rowconfigure(row_idx, weight=1)
            digit_label = tk.Label(frame, text=str(d), font=('Segoe UI', 12, 'bold'), fg='white', bg=color_map['neutral'])
            digit_label.pack(fill='both', expand=True, padx=2, pady=2)
            percent_label = tk.Label(frame, text="0.0%", font=('Segoe UI', 8), fg='white', bg=ModernUI.COLORS['bg_card'])
            percent_label.pack(fill='x', padx=2, pady=(0,2))
            self.digit_labels[d] = (digit_label, percent_label)

        log_tab = tk.Frame(notebook, bg=ModernUI.COLORS['bg_dark'])
        notebook.add(log_tab, text="Event Log")
        log_frame = tk.Frame(log_tab, bg=ModernUI.COLORS['bg_card'])
        log_frame.pack(fill='both', expand=True, padx=5, pady=5)
        self.log_text = tk.Text(log_frame, bg='#0E1628', fg='#E0E7FF', insertbackground='white', font=('Consolas', 8), wrap='word')
        scroll_log = tk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll_log.set)
        scroll_log.pack(side='right', fill='y')
        self.log_text.pack(side='left', fill='both', expand=True)

        app_id = self.app_id_var.get()
        threading.Thread(target=self.load_symbols_thread, args=(app_id,), daemon=True).start()

    def logout(self):
        self.ui_active = False
        self.stop_bot()
        self.current_user = None
        self.is_logged_in = False
        self.session_api_token = ""
        self.show_login_screen()
