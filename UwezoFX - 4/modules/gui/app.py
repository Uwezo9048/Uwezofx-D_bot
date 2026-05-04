# modules/gui/app.py

# modules/gui/app.py
import base64
import hashlib
from platform import platform
import tkinter as tk
from tkinter import messagebox, ttk, filedialog
import queue
import threading
import time
import os
import json
from datetime import datetime

from attrs import asdict
import numpy as np
from config import TradingConfig, Settings
from modules.database.supabase_manager import SupabaseUserManager
from modules.trading.system import TradingSystem
from modules.gui.login import ModernLoginScreen
from modules.gui.widgets import ModernUI, MiniChart, ScrollableFrame, AnimatedProgressBar, HelpCenterBot, AboutSection, LoadingAnimation
from modules.gui.sections import (
    create_dashboard_section, create_trading_section, create_positions_section,
    create_news_section, create_settings_section, create_trailing_section,
    create_alerts_section, create_reversal_section
)
from modules.utils.helpers import set_app_icon, darken_color, lighten_color
import MetaTrader5 as mt5

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False


class ModernUwezoTradingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("UWEZO-FX TRADING SYSTEM - ENHANCED REVERSAL EDITION")
        self.root.geometry("1400x900")
        self.root.configure(bg=ModernUI.COLORS['bg_dark'])
        set_app_icon(self.root)

        self.colors = ModernUI.COLORS
        self.callback_queue = queue.Queue(maxsize=100)

        self.user_manager = SupabaseUserManager()
        self.current_user = None
        self.is_logged_in = False

        self.config = TradingConfig.load()
        self.trading_system = None
        self.trading_thread = None
        self.trading_running = False

        self.current_section = "dashboard"
        self.notifications = []
        self.current_positions = []
        self.available_symbols = []
        self.current_profile_photo = None

        self.symbol_search_after_id = None
        self.last_full_refresh = time.time()
        self.refresh_interval = 1   # UPDATED: from 2 to 1 second for faster updates
        self.pending_updates = {}

        self.root.bind('<Control-r>', lambda e: self.refresh_application())
        self.root.bind('<Control-R>', lambda e: self.refresh_application())
        # Auto‑focus symbol combobox when typing
        self.root.bind('<Key>', self._focus_symbol_combobox)

        self.last_trailing_stats = {}
        self.trailing_update_pending = False
        self.reversal_mode_enabled = False
        self.last_reversal_time = None
        self.reversal_trades_count = 0

        self.broker_credentials_file = "broker_credentials.dat"
        self.broker_connected = False
        self._last_signal_update = 0

        self.gradients = {}
        self.icons = {}

        self.setup_styles()
        self.create_widgets()
        self.show_animated_login_screen()
        self.process_urgent_callbacks()
        self.periodic_refresh()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Modern.TButton', background=self.colors['accent_primary'],
                        foreground='white', borderwidth=0, focuscolor='none',
                        font=('Segoe UI', 10, 'bold'))
        style.map('Modern.TButton', background=[('active', darken_color(self.colors['accent_primary']))])
        style.configure('Success.TButton', background=self.colors['accent_success'],
                        foreground='white', borderwidth=0, font=('Segoe UI', 10, 'bold'))
        style.map('Success.TButton', background=[('active', darken_color(self.colors['accent_success']))])
        style.configure('Danger.TButton', background=self.colors['accent_danger'],
                        foreground='white', borderwidth=0, font=('Segoe UI', 10, 'bold'))
        style.map('Danger.TButton', background=[('active', darken_color(self.colors['accent_danger']))])
        style.configure('Outline.TButton', background='transparent',
                        foreground=self.colors['text_primary'], relief='solid',
                        borderwidth=1, font=('Segoe UI', 10))
        style.map('Outline.TButton', background=[('active', self.colors['hover'])])
        style.configure('Modern.TEntry', fieldbackground=self.colors['bg_card'],
                        foreground=self.colors['text_primary'],
                        insertcolor=self.colors['text_primary'],
                        borderwidth=1, relief='solid')
        style.configure('Modern.TCombobox', fieldbackground=self.colors['bg_card'],
                        foreground=self.colors['text_primary'],
                        arrowcolor=self.colors['text_primary'],
                        borderwidth=1, relief='solid')

    def create_widgets(self):
        self.main_container = tk.Frame(self.root, bg=self.colors['bg_dark'])
        self.main_container.pack(fill=tk.BOTH, expand=True)
        self.app_frame = tk.Frame(self.main_container, bg=self.colors['bg_dark'])

        # Sidebar
        self.sidebar = tk.Frame(self.app_frame, bg=self.colors['bg_sidebar'], width=250)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y)
        self.sidebar.pack_propagate(False)

        sidebar_gradient = ModernUI.create_gradient(250, 900, self.colors['bg_sidebar'],
                                                    self.colors['bg_dark'], 'vertical')
        self.sidebar_bg = tk.Label(self.sidebar, image=sidebar_gradient)
        self.sidebar_bg.place(relwidth=1, relheight=1)
        self.gradients['sidebar'] = sidebar_gradient

        # Logo
        logo_frame = tk.Frame(self.sidebar, bg=self.colors['bg_sidebar'], height=100)
        logo_frame.pack(fill=tk.X, pady=20)
        logo_frame.pack_propagate(False)
        logo_label = tk.Label(logo_frame, text="UWEZO-FX", font=('Montserrat', 18, 'bold'),
                              fg=self.colors['accent_primary'], bg=self.colors['bg_sidebar'])
        logo_label.pack()
        sub_label = tk.Label(logo_frame, text="TRADE ALL ASSETS", font=('Segoe UI', 10),
                             fg=self.colors['accent_success'], bg=self.colors['bg_sidebar'])
        sub_label.pack()

        # Navigation buttons
        nav_buttons = [
            ('dashboard', '📊 Dashboard'),
            ('trading', '📈 Trading Signal'),
            ('positions', '💼 Positions'),
            ('news', '📰 News'),
            ('settings', '⚙️ Settings'),
            ('trailing', '🎯 Trailing'),
            ('alerts', '🔊 Alerts'),
            ('reversal', '🔄 Reversal Stats')
        ]
        self.nav_vars = {}
        for section, label in nav_buttons:
            btn = tk.Button(self.sidebar, text=label, bg=self.colors['bg_sidebar'],
                            fg=self.colors['text_secondary'], bd=0, font=('Segoe UI', 11),
                            anchor='w', padx=20, pady=10, cursor='hand2')
            btn.config(command=self.animate_button_click(btn, self.switch_section, section))
            btn.pack(fill=tk.X)
            self.nav_vars[section] = btn
            ModernUI.add_glow_effect(btn, self.colors['accent_primary'])

        tk.Frame(self.sidebar, bg=self.colors['bg_sidebar'], height=20).pack(fill=tk.X, expand=True)

        logout_btn = tk.Button(self.sidebar, text="🚪 Logout", bg=self.colors['bg_sidebar'],
                               fg=self.colors['accent_danger'], bd=0, font=('Segoe UI', 11),
                               anchor='w', padx=20, pady=10, cursor='hand2', command=self.logout)
        logout_btn.pack(fill=tk.X)
        ModernUI.add_glow_effect(logout_btn, self.colors['accent_danger'])

        self.add_help_and_about_buttons()

        # Content area
        self.content = tk.Frame(self.app_frame, bg=self.colors['bg_dark'])
        self.content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Top bar
        self.top_bar = tk.Frame(self.content, bg=self.colors['bg_card'], height=70)
        self.top_bar.pack(fill=tk.X)
        self.top_bar.pack_propagate(False)
        self.top_bar.config(highlightbackground=self.colors['border'], highlightthickness=1)

        self.page_title = tk.Label(self.top_bar, text="Dashboard", font=('Montserrat', 18, 'bold'),
                                   fg=self.colors['text_primary'], bg=self.colors['bg_card'])
        self.page_title.pack(side=tk.LEFT, padx=20, pady=20)

        self.symbol_display = tk.Label(self.top_bar, text="", font=('Segoe UI', 12, 'bold'),
                                       fg=self.colors['accent_success'], bg=self.colors['bg_card'])
        self.symbol_display.pack(side=tk.LEFT, padx=20)

        self.session_frame = tk.Frame(self.top_bar, bg=self.colors['bg_card'])
        self.session_frame.pack(side=tk.LEFT, padx=20)
        self.market_trades_label = tk.Label(self.session_frame, text="Market: 0/5",
                                            font=('Segoe UI', 11, 'bold'),
                                            fg=self.colors['accent_success'], bg=self.colors['bg_card'])
        self.market_trades_label.pack(side=tk.LEFT, padx=5)
        self.pending_orders_label = tk.Label(self.session_frame, text="Pending: 0/5",
                                             font=('Segoe UI', 11, 'bold'),
                                             fg=self.colors['accent_warning'], bg=self.colors['bg_card'])
        self.pending_orders_label.pack(side=tk.LEFT, padx=5)

        refresh_frame = tk.Frame(self.top_bar, bg=self.colors['bg_card'])
        refresh_frame.pack(side=tk.LEFT, padx=20)
        self.refresh_button = tk.Button(refresh_frame, text="🔄 Refresh", font=('Segoe UI', 10, 'bold'),
                                        fg=self.colors['text_primary'], bg=self.colors['bg_sidebar'],
                                        activebackground=self.colors['hover'],
                                        activeforeground=self.colors['text_primary'],
                                        bd=0, padx=10, pady=5, cursor='hand2', command=self.refresh_application)
        self.refresh_button.pack()
        ModernUI.add_glow_effect(self.refresh_button, self.colors['accent_primary'])
        self.refresh_status = tk.Label(refresh_frame, text="", font=('Segoe UI', 8),
                                       fg=self.colors['text_secondary'], bg=self.colors['bg_card'])
        self.refresh_status.pack()

        profile_frame = tk.Frame(self.top_bar, bg=self.colors['bg_card'])
        profile_frame.pack(side=tk.RIGHT, padx=20)
        self.profile_label = tk.Label(profile_frame, text="Loading...", font=('Segoe UI', 11),
                                      fg=self.colors['text_primary'], bg=self.colors['bg_card'])
        self.profile_label.pack(side=tk.LEFT, padx=5)
        self.profile_photo = tk.Label(profile_frame, text="👤", font=('Segoe UI', 16),
                                      fg=self.colors['text_primary'], bg=self.colors['bg_card'])
        self.profile_photo.pack(side=tk.LEFT)

        self.connection_indicator = tk.Label(self.top_bar, text="●", font=('Segoe UI', 14),
                                             fg=self.colors['accent_success'], bg=self.colors['bg_card'])
        self.connection_indicator.pack(side=tk.RIGHT, padx=10)
        self.connection_label = tk.Label(self.top_bar, text="LIVE", font=('Segoe UI', 10),
                                         fg=self.colors['accent_success'], bg=self.colors['bg_card'])
        self.connection_label.pack(side=tk.RIGHT, padx=5)

        # Scrollable container
        self.scrollable_container = ScrollableFrame(self.content)
        self.scrollable_container.pack(fill=tk.BOTH, expand=True)

        # Create sections using the functions from sections.py
        self.sections = {}
        self.sections['dashboard'] = create_dashboard_section(self.scrollable_container.scrollable_frame, self.colors, self)
        self.sections['trading'] = create_trading_section(self.scrollable_container.scrollable_frame, self.colors, self)
        self.sections['positions'] = create_positions_section(self.scrollable_container.scrollable_frame, self.colors, self)
        self.sections['news'] = create_news_section(self.scrollable_container.scrollable_frame, self.colors, self)
        self.sections['settings'] = create_settings_section(self.scrollable_container.scrollable_frame, self.colors, self)
        self.sections['trailing'] = create_trailing_section(self.scrollable_container.scrollable_frame, self.colors, self)
        self.sections['alerts'] = create_alerts_section(self.scrollable_container.scrollable_frame, self.colors, self)
        self.sections['reversal'] = create_reversal_section(self.scrollable_container.scrollable_frame, self.colors, self)

        self.switch_section('dashboard')

    def add_help_and_about_buttons(self):
        tk.Frame(self.sidebar, bg=self.colors['bg_sidebar'], height=10).pack()
        help_btn = tk.Button(self.sidebar, text="🆘 Help Center", bg=self.colors['bg_sidebar'],
                             fg=self.colors['text_secondary'], bd=0, font=('Segoe UI', 11),
                             anchor='w', padx=20, pady=10, cursor='hand2',
                             command=self.open_help_center)
        help_btn.pack(fill=tk.X)
        ModernUI.add_glow_effect(help_btn, self.colors['accent_info'])
        about_btn = tk.Button(self.sidebar, text="ℹ️ About", bg=self.colors['bg_sidebar'],
                              fg=self.colors['text_secondary'], bd=0, font=('Segoe UI', 11),
                              anchor='w', padx=20, pady=10, cursor='hand2',
                              command=self.open_about_section)
        about_btn.pack(fill=tk.X)
        ModernUI.add_glow_effect(about_btn, self.colors['accent_primary'])

    def open_help_center(self):
        self.help_bot = HelpCenterBot(self.root, self.colors)
        self.help_bot.open()

    def open_about_section(self):
        self.about_section = AboutSection(self.root, self.colors)
        self.about_section.open()

    def animate_button_click(self, button, command, *args):
        def animated_command():
            try:
                original_bg = button.cget('bg') if button.winfo_exists() else None
                original_fg = button.cget('fg') if button.winfo_exists() else None
            except:
                original_bg = None
                original_fg = None
            try:
                if button.winfo_exists():
                    button.config(bg='#FFFFFF', fg='#4F7DF3')
                    button.update()
            except:
                pass
            def execute():
                try:
                    if button.winfo_exists() and original_bg:
                        button.config(bg=original_bg, fg=original_fg)
                except:
                    pass
                if args:
                    command(*args)
                else:
                    command()
            button.after(100, execute)
        return animated_command

    def _focus_symbol_combobox(self, event):
        """Automatically focus the symbol combobox when user starts typing."""
        # Don't interfere if already typing in an Entry or Combobox
        if isinstance(event.widget, (tk.Entry, ttk.Combobox)):
            return
        if hasattr(self, 'symbol_combo') and self.symbol_combo.winfo_exists():
            self.symbol_combo.focus_set()
            # Insert the typed character
            self.symbol_combo.insert('end', event.char)
            return 'break'

    def show_animated_login_screen(self):
        if hasattr(self, 'login_screen') and self.login_screen:
            self.login_screen.destroy()
        self.login_screen = ModernLoginScreen(
            self.root,
            self.colors,
            self.handle_login_callback,
            self.show_create_account,
            self.show_password_reset
        )

    def handle_login_callback(self, username, login_code):
        self.login_screen.status_text.config(text="🔐 Verifying credentials...")
        def do_login():
            success, msg, user_data = self.user_manager.login(username, login_code)
            self.root.after(0, lambda: self.handle_login_result(success, msg, user_data))
        threading.Thread(target=do_login, daemon=True).start()

    def handle_login_result(self, success, msg, user_data):
        if success:
            self.current_user = user_data
            self.is_logged_in = True

            self.last_full_refresh = time.time() - self.refresh_interval
            self.refresh_status.config(text="Auto: starting...")
            self._full_reload_data(silent=False)
            self.login_screen.destroy()
            self.app_frame.pack(fill=tk.BOTH, expand=True)
            self.profile_label.config(text=user_data.get('username', 'User'))
            self.start_trading_system()
            self.load_user_data()
            self.show_welcome_animation()
            self.add_notification("Welcome", f"Welcome back, {user_data.get('username', 'User')}!", "success")
        else:
            # Center the card before showing the error message
            self.login_screen.login_card.place(relx=0.5, rely=0.5, anchor='center', width=500, height=600)
            self.login_screen.message_label.config(text=msg)
            
            # Determine if it's an authentication error
            auth_keywords = ["Invalid", "not approved", "deactivated", "rejected", "Invalid username", "Invalid login code"]
            is_auth_error = any(keyword in msg for keyword in auth_keywords)
            
            if is_auth_error:
                self.login_screen.shake_login_form()
                # Re-center again after shake completes
                self.root.after(600, lambda: self.login_screen.login_card.place(relx=0.5, rely=0.5, anchor='center', width=500, height=600))
            else:
                # For network errors: no shake, but ensure the card stays centered
                # (the label may have changed height, so re-center after a short delay)
                self.root.after(100, lambda: self.login_screen.login_card.place(relx=0.5, rely=0.5, anchor='center', width=500, height=600))
            
            self.login_screen.login_button.config(state='normal')
            self.login_screen.create_button.config(state='normal')

    def show_welcome_animation(self):
        welcome_label = tk.Label(self.app_frame, text="Welcome to UWEZO-FX!", font=('Montserrat', 24, 'bold'),
                                 fg=self.colors['accent_success'], bg=self.colors['bg_dark'])
        welcome_label.place(relx=0.5, rely=0.5, anchor='center')
        def fade_out():
            for i in range(10, 0, -1):
                try:
                    alpha = i / 10
                    r = int(46 * alpha + 15 * (1 - alpha))
                    g = int(204 * alpha + 25 * (1 - alpha))
                    b = int(113 * alpha + 50 * (1 - alpha))
                    welcome_label.config(fg=f'#{r:02x}{g:02x}{b:02x}')
                except:
                    pass
                time.sleep(0.05)
            welcome_label.destroy()
        self.root.after(2000, lambda: threading.Thread(target=fade_out, daemon=True).start())

    def show_create_account(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Create Account")
        dialog.geometry("450x550")
        dialog.configure(bg=self.colors['bg_dark'])
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 225
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 275
        dialog.geometry(f"+{x}+{y}")

        form_frame = tk.Frame(dialog, bg=self.colors['bg_card'], bd=0)
        form_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        tk.Label(form_frame, text="Create New Account", font=('Montserrat', 16, 'bold'),
                 fg=self.colors['accent_primary'], bg=self.colors['bg_card']).pack(pady=10)

        info_text = tk.Label(form_frame,
                             text="After registration, your account will need admin approval.\nYou will receive your login code via SMS and email.",
                             fg=self.colors['text_secondary'], bg=self.colors['bg_card'],
                             font=('Segoe UI', 9), justify=tk.CENTER)
        info_text.pack(pady=10)

        form = tk.Frame(form_frame, bg=self.colors['bg_card'])
        form.pack(pady=10)

        # Username
        tk.Label(form, text="Username:", fg=self.colors['text_secondary'], bg=self.colors['bg_card'],
                 font=('Segoe UI', 10)).grid(row=0, column=0, padx=5, pady=5, sticky='w')
        username_entry = tk.Entry(form, width=30, bg=self.colors['bg_sidebar'],
                                  fg=self.colors['text_primary'], insertbackground=self.colors['text_primary'],
                                  bd=0, font=('Segoe UI', 10))
        username_entry.grid(row=0, column=1, padx=5, pady=5)
        ModernUI.add_glow_effect(username_entry, self.colors['accent_primary'])

        # Email
        tk.Label(form, text="Email:", fg=self.colors['text_secondary'], bg=self.colors['bg_card'],
                 font=('Segoe UI', 10)).grid(row=1, column=0, padx=5, pady=5, sticky='w')
        email_entry = tk.Entry(form, width=30, bg=self.colors['bg_sidebar'],
                               fg=self.colors['text_primary'], insertbackground=self.colors['text_primary'],
                               bd=0, font=('Segoe UI', 10))
        email_entry.grid(row=1, column=1, padx=5, pady=5)
        ModernUI.add_glow_effect(email_entry, self.colors['accent_primary'])

        # Phone Number
        tk.Label(form, text="Phone Number:", fg=self.colors['text_secondary'], bg=self.colors['bg_card'],
                 font=('Segoe UI', 10)).grid(row=2, column=0, padx=5, pady=5, sticky='w')
        phone_entry = tk.Entry(form, width=30, bg=self.colors['bg_sidebar'],
                               fg=self.colors['text_primary'], insertbackground=self.colors['text_primary'],
                               bd=0, font=('Segoe UI', 10))
        phone_entry.grid(row=2, column=1, padx=5, pady=5)
        phone_entry.insert(0, "+254")
        ModernUI.add_glow_effect(phone_entry, self.colors['accent_primary'])
        phone_hint = tk.Label(form, text="Format: +254XXXXXXXXX (Kenya) or your country code",
                              fg=self.colors['text_muted'], bg=self.colors['bg_card'],
                              font=('Segoe UI', 8))
        phone_hint.grid(row=3, column=0, columnspan=2, pady=2)

        # Password
        tk.Label(form, text="Password:", fg=self.colors['text_secondary'], bg=self.colors['bg_card'],
                 font=('Segoe UI', 10)).grid(row=4, column=0, padx=5, pady=5, sticky='w')
        password_entry = tk.Entry(form, width=30, show="*", bg=self.colors['bg_sidebar'],
                                  fg=self.colors['text_primary'], insertbackground=self.colors['text_primary'],
                                  bd=0, font=('Segoe UI', 10))
        password_entry.grid(row=4, column=1, padx=5, pady=5)
        ModernUI.add_glow_effect(password_entry, self.colors['accent_primary'])

        # Confirm Password
        tk.Label(form, text="Confirm:", fg=self.colors['text_secondary'], bg=self.colors['bg_card'],
                 font=('Segoe UI', 10)).grid(row=5, column=0, padx=5, pady=5, sticky='w')
        confirm_entry = tk.Entry(form, width=30, show="*", bg=self.colors['bg_sidebar'],
                                 fg=self.colors['text_primary'], insertbackground=self.colors['text_primary'],
                                 bd=0, font=('Segoe UI', 10))
        confirm_entry.grid(row=5, column=1, padx=5, pady=5)
        ModernUI.add_glow_effect(confirm_entry, self.colors['accent_primary'])

        message = tk.Label(form_frame, text="", fg=self.colors['accent_danger'],
                           bg=self.colors['bg_card'], font=('Segoe UI', 10))
        message.pack(pady=5)

        def do_create():
            username = username_entry.get().strip()
            email = email_entry.get().strip()
            phone = phone_entry.get().strip()
            password = password_entry.get()
            confirm = confirm_entry.get()
            if not username or not email or not phone or not password:
                message.config(text="All fields are required")
                return
            if len(username) < 3:
                message.config(text="Username must be at least 3 characters")
                return
            if len(password) < 6:
                message.config(text="Password must be at least 6 characters")
                return
            if password != confirm:
                message.config(text="Passwords do not match")
                return
            if '@' not in email or '.' not in email:
                message.config(text="Invalid email address")
                return
            if not phone.startswith('+') or len(phone) < 10:
                message.config(text="Invalid phone number. Use format: +254XXXXXXXXX")
                return
            success, msg = self.user_manager.register_user(username, email, phone, password)
            if success:
                message.config(text=msg, fg=self.colors['accent_success'])
                dialog.after(3000, dialog.destroy)
            else:
                message.config(text=msg)

        btn_frame = tk.Frame(form_frame, bg=self.colors['bg_card'])
        btn_frame.pack(pady=10)
        register_btn = ModernUI.create_animated_button(btn_frame, "Register", do_create, 'success')
        register_btn.pack(side=tk.LEFT, padx=5)
        cancel_btn = ModernUI.create_animated_button(btn_frame, "Cancel", dialog.destroy, 'danger')
        cancel_btn.pack(side=tk.LEFT, padx=5)
        dialog.bind('<Return>', lambda e: do_create())
        dialog.bind('<Escape>', lambda e: dialog.destroy())

    def show_password_reset(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Reset Password")
        dialog.geometry("400x300")
        dialog.configure(bg=self.colors['bg_dark'])
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() // 2) - 200
        y = self.root.winfo_y() + (self.root.winfo_height() // 2) - 150
        dialog.geometry(f"+{x}+{y}")

        notebook = ttk.Notebook(dialog)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Tab 1: Request reset link
        request_frame = tk.Frame(notebook, bg=self.colors['bg_card'])
        notebook.add(request_frame, text="Request Reset")
        tk.Label(request_frame, text="Enter your email address:",
                 fg=self.colors['text_secondary'], bg=self.colors['bg_card'],
                 font=('Segoe UI', 11)).pack(pady=20)
        email_entry = tk.Entry(request_frame, width=30, bg=self.colors['bg_sidebar'],
                               fg=self.colors['text_primary'], insertbackground=self.colors['text_primary'],
                               bd=0, font=('Segoe UI', 11))
        email_entry.pack(pady=10)
        ModernUI.add_glow_effect(email_entry, self.colors['accent_primary'])
        message = tk.Label(request_frame, text="", fg=self.colors['accent_danger'],
                           bg=self.colors['bg_card'], font=('Segoe UI', 10))
        message.pack(pady=10)

        def do_request():
            email = email_entry.get().strip()
            if not email:
                message.config(text="Email is required")
                return
            success, msg = self.user_manager.request_password_reset(email)
            if success:
                message.config(text=msg, fg=self.colors['accent_success'])
                dialog.after(2000, lambda: notebook.select(1))
            else:
                message.config(text=msg)

        request_btn = ModernUI.create_animated_button(request_frame, "Send Reset Link", do_request, 'primary')
        request_btn.pack(pady=10)

        # Tab 2: Reset with token
        reset_frame = tk.Frame(notebook, bg=self.colors['bg_card'])
        notebook.add(reset_frame, text="Reset Password")
        tk.Label(reset_frame, text="Reset Token:", fg=self.colors['text_secondary'],
                 bg=self.colors['bg_card'], font=('Segoe UI', 11)).pack(pady=5)
        token_entry = tk.Entry(reset_frame, width=30, bg=self.colors['bg_sidebar'],
                               fg=self.colors['text_primary'], insertbackground=self.colors['text_primary'],
                               bd=0, font=('Segoe UI', 11))
        token_entry.pack(pady=5)
        tk.Label(reset_frame, text="New Password:", fg=self.colors['text_secondary'],
                 bg=self.colors['bg_card'], font=('Segoe UI', 11)).pack(pady=5)
        password_entry = tk.Entry(reset_frame, width=30, show="*", bg=self.colors['bg_sidebar'],
                                  fg=self.colors['text_primary'], insertbackground=self.colors['text_primary'],
                                  bd=0, font=('Segoe UI', 11))
        password_entry.pack(pady=5)
        tk.Label(reset_frame, text="Confirm Password:", fg=self.colors['text_secondary'],
                 bg=self.colors['bg_card'], font=('Segoe UI', 11)).pack(pady=5)
        confirm_entry = tk.Entry(reset_frame, width=30, show="*", bg=self.colors['bg_sidebar'],
                                 fg=self.colors['text_primary'], insertbackground=self.colors['text_primary'],
                                 bd=0, font=('Segoe UI', 11))
        confirm_entry.pack(pady=5)
        reset_message = tk.Label(reset_frame, text="", fg=self.colors['accent_danger'],
                                 bg=self.colors['bg_card'], font=('Segoe UI', 10))
        reset_message.pack(pady=10)

        def do_reset():
            token = token_entry.get().strip()
            password = password_entry.get()
            confirm = confirm_entry.get()
            if not token or not password:
                reset_message.config(text="All fields are required")
                return
            if password != confirm:
                reset_message.config(text="Passwords do not match")
                return
            if len(password) < 6:
                reset_message.config(text="Password must be at least 6 characters")
                return
            success, msg = self.user_manager.reset_password_with_token(token, password)
            if success:
                reset_message.config(text=msg, fg=self.colors['accent_success'])
                dialog.after(2000, dialog.destroy)
            else:
                reset_message.config(text=msg)

        reset_btn = ModernUI.create_animated_button(reset_frame, "Reset Password", do_reset, 'success')
        reset_btn.pack(pady=10)

        cancel_btn = ModernUI.create_animated_button(dialog, "Close", dialog.destroy, 'danger')
        cancel_btn.pack(pady=10)

    def start_trading_system(self):
        if not self.trading_running:
            self.trading_running = True
            self.trading_system = TradingSystem(self.config, self.callback_queue)
            self.trading_thread = threading.Thread(target=self.run_trading_system, daemon=True)
            self.trading_thread.start()

    def run_trading_system(self):
        if self.trading_system.initialize():
            self.trading_system.running = True
            self.trading_system.run()

    def load_user_data(self):
        # --- Load profile photo from root folder ---
        # Look for my_photo.jpg (or .png) in the root directory
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))  # goes up to project root
        photo_path = os.path.join(root_dir, "my_photo.jpg")
        
        # If .jpg not found, try .png as fallback
        if not os.path.exists(photo_path):
            photo_path = os.path.join(root_dir, "my_photo.png")
        
        if os.path.exists(photo_path):
            try:
                from PIL import Image, ImageTk, ImageDraw
                # Load and resize to 40x40
                img = Image.open(photo_path).resize((40, 40), Image.Resampling.LANCZOS)
                # Create circular mask
                mask = Image.new('L', (40, 40), 0)
                draw = ImageDraw.Draw(mask)
                draw.ellipse((0, 0, 40, 40), fill=255)
                # Apply mask
                result = Image.new('RGBA', (40, 40), (0, 0, 0, 0))
                result.paste(img, (0, 0), mask)
                self.profile_photo_image = ImageTk.PhotoImage(result)
                self.profile_photo.config(image=self.profile_photo_image, text="")
            except Exception as e:
                print(f"Could not load profile photo: {e}")
                self.profile_photo.config(text="👤", image="")
        else:
            # Fallback to emoji
            self.profile_photo.config(text="👤", image="")

        # --- The rest of the method (Supabase user info) ---
        if self.current_user and isinstance(self.current_user, dict):
            user_id = self.current_user.get('id')
            if user_id:
                user_info = self.user_manager.get_user_info(user_id)
                if user_info and user_info.get('profile_photo'):
                    self.current_profile_photo = user_info['profile_photo']
        self.refresh_symbols()
        self.load_settings()

    def load_settings(self):
        """Load settings from config into UI elements."""
        # Symbol selection
        self.symbol_var.set(self.config.symbol or "")
        if self.config.symbol:
            self.symbol_display.config(text=f"Selected: {self.config.symbol}")

        # Trading parameters (SL/TP, lot size, etc.)
        if hasattr(self, 'sl_pips_entry') and self.sl_pips_entry:
            self.sl_pips_entry.delete(0, tk.END)
            self.sl_pips_entry.insert(0, str(self.config.stop_loss_pips))
            self.tp_pips_entry.delete(0, tk.END)
            self.tp_pips_entry.insert(0, str(self.config.take_profit_pips))
            self.lot_size.delete(0, tk.END)
            self.lot_size.insert(0, str(self.config.fixed_lot_size))

        # Checkboxes and toggles
        if hasattr(self, 'enable_sl_var'):
            self.enable_sl_var.set(self.config.enable_stop_loss)
        if hasattr(self, 'enable_tp_var'):
            self.enable_tp_var.set(self.config.enable_take_profit)
        if hasattr(self, 'close_opposite_var'):
            self.close_opposite_var.set(self.config.close_opposite_on_signal_change)
        if hasattr(self, 'sts_var'):
            self.sts_var.set(self.config.use_sts_signal)
        if hasattr(self, 'news_sentiment_var'):
            self.news_sentiment_var.set(self.config.use_news_sentiment)
        if hasattr(self, 'trailing_var'):
            self.trailing_var.set(self.config.enable_trailing_stop_loss)

        # Trailing stop amounts
        if hasattr(self, 'lock_amount_entry') and self.lock_amount_entry:
            self.lock_amount_entry.delete(0, tk.END)
            self.lock_amount_entry.insert(0, str(self.config.lock_amount_dollars))
        if hasattr(self, 'step_amount_entry') and self.step_amount_entry:
            self.step_amount_entry.delete(0, tk.END)
            self.step_amount_entry.insert(0, str(self.config.step_amount_dollars))

        # Reversal settings (lot size, confidence, cooldown)
        if hasattr(self, 'reversal_lot_size') and self.reversal_lot_size:
            self.reversal_lot_size.delete(0, tk.END)
            self.reversal_lot_size.insert(0, str(self.config.reversal_trade_volume))
        if hasattr(self, 'reversal_min_conf') and self.reversal_min_conf:
            self.reversal_min_conf.delete(0, tk.END)
            self.reversal_min_conf.insert(0, str(self.config.reversal_min_confidence_score))
        if hasattr(self, 'reversal_cooldown') and self.reversal_cooldown:
            self.reversal_cooldown.delete(0, tk.END)
            self.reversal_cooldown.insert(0, str(self.config.reversal_cooldown_seconds))

        # Reversal mode button appearance
        self.reversal_mode_enabled = self.config.enable_reversal_trading
        if self.reversal_mode_enabled:
            self.reversal_button.config(text="🟢 REVERSAL MODE: ON", bg=self.colors['accent_success'])
        else:
            self.reversal_button.config(text="🔴 REVERSAL MODE: OFF", bg=self.colors['accent_danger'])

        # Confidence spinboxes
        if hasattr(self, 'min_confidence_var') and self.min_confidence_var:
            self.min_confidence_var.set(str(self.config.reversal_min_confidence_score))
        if hasattr(self, 'reversal_min_conf_var') and self.reversal_min_conf_var:
            self.reversal_min_conf_var.set(str(self.config.reversal_min_confidence_score))

        # Bot lot size
        if hasattr(self, 'bot_lot_size_entry') and self.bot_lot_size_entry:
            self.bot_lot_size_entry.delete(0, tk.END)
            self.bot_lot_size_entry.insert(0, str(self.config.fixed_lot_size))

        # ========== UPDATE TOGGLE BUTTON STATES (Reversal Statistics) ==========
        if hasattr(self, 'indicator_buttons'):
            for config_key, btn in self.indicator_buttons.items():
                # Get current value from config (default to True if missing)
                current_state = getattr(self.config, config_key, True)
                # Update button text and color
                if current_state:
                    new_text = btn.cget('text').replace('❌ INACTIVE', '✅ ACTIVE')
                    btn.config(text=new_text, bg=self.colors['accent_success'])
                else:
                    new_text = btn.cget('text').replace('✅ ACTIVE', '❌ INACTIVE')
                    btn.config(text=new_text, bg=self.colors['accent_danger'])

        # Load saved broker connections (if cryptography available)
        if CRYPTO_AVAILABLE:
            self.load_saved_connections()

    # ========== Action Methods ==========
    def toggle_reversal_indicator(self, config_key: str, button):
        """Toggle a reversal confirmation indicator on/off."""
        current = getattr(self.config, config_key, True)
        new_state = not current
        setattr(self.config, config_key, new_state)

        # Update button appearance
        if new_state:
            button.config(text=button.cget('text').replace('❌ INACTIVE', '✅ ACTIVE'),
                        bg=self.colors['accent_success'])
        else:
            button.config(text=button.cget('text').replace('✅ ACTIVE', '❌ INACTIVE'),
                        bg=self.colors['accent_danger'])

        # Save config
        self.save_config()

        # Update trading system if running
        if self.trading_system:
            setattr(self.trading_system.config, config_key, new_state)
            self.trading_system.reversal_trader.config = self.trading_system.config

        self.add_notification("Reversal Indicator", f"{config_key} is now {'ENABLED' if new_state else 'DISABLED'}", "info")

    def toggle_auto_trading(self):
        if self.trading_system:
            self.config.auto_trading = self.auto_var.get()
            self.trading_system.config.auto_trading = self.config.auto_trading
            self.save_config()
            status = "ENABLED" if self.config.auto_trading else "DISABLED"
            self.add_notification("Auto Trading", f"Auto trading {status}", "info")

    def update_bot_lot_size(self, event=None):
        try:
            new_lot = float(self.bot_lot_size_entry.get())
            if new_lot <= 0:
                return
            self.config.fixed_lot_size = new_lot
            if self.trading_system:
                self.trading_system.config.fixed_lot_size = new_lot
            self.save_config()
            self.add_notification("Bot Lot Size", f"Auto trading lot size set to {new_lot:.2f}", "info")
        except ValueError:
            pass

    def toggle_sts(self):
        enabled = self.sts_var.get()
        if self.trading_system:
            self.trading_system.set_sts_mode(enabled)
        self.config.use_sts_signal = enabled
        self.save_config()
        status = "ENABLED" if enabled else "DISABLED"
        self.add_notification("STS Mode", f"STS mode {status}", "info")

    def toggle_news_sentiment(self):
        enabled = self.news_sentiment_var.get()
        if self.trading_system:
            self.config.use_news_sentiment = enabled
            self.trading_system.config.use_news_sentiment = enabled
        self.save_config()
        status = "ENABLED" if enabled else "DISABLED"
        self.add_notification("News Sentiment", f"News sentiment {status}", "info")

    def toggle_alerts(self):
        enabled = self.alerts_var.get()
        if self.trading_system:
            self.trading_system.alert_system.set_enabled(enabled)
        status = "ENABLED" if enabled else "DISABLED"
        self.add_notification("Sound Alerts", f"Sound alerts {status}", "info")

    def test_alerts(self):
        if self.trading_system:
            self.trading_system.alert_system.alert_buy_signal(100.0, "Test")
            self.trading_system.alert_system.alert_sell_signal(99.0, "Test")
            self.trading_system.alert_system.alert_signal_reversal("BUY", "SELL", 99.5)
            self.trading_system.alert_system.alert_reversal_execution(5)
            self.trading_system.alert_system.alert_overbought("RSI", 75, 70)
            self.trading_system.alert_system.alert_oversold("RSI", 25, 30)
            self.trading_system.alert_system.alert_trade_execution("BUY", 0.1, 100.0)
            class DummyPosition:
                def __init__(self):
                    self.symbol = "XAUUSD"
                    self.ticket = 12345
                    self.profit = 50.0
            dummy = DummyPosition()
            self.trading_system.alert_system.alert_stop_loss_hit(dummy)
            dummy.profit = 150.0
            self.trading_system.alert_system.alert_take_profit_hit(dummy)
            self.trading_system.alert_system.alert_profit_locked(dummy, 50.0)
            self.trading_system.alert_system.alert_high_impact_news({'title': 'Test News Event', 'impact': 'High'})
            self.add_notification("Alert Test", "All alerts tested", "success")

    def execute_manual_trade(self, direction):
        if not self.trading_system or not self.trading_system.config.symbol:
            messagebox.showerror("Error", "No symbol selected")
            return
        try:
            volume = float(self.lot_size.get())
            success, msg = self.trading_system.execute_manual_trade(direction, volume, None, None)
            if not success:
                messagebox.showerror("Trade Failed", msg)
        except ValueError:
            messagebox.showerror("Error", "Invalid input values")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def close_losing_positions(self):
        count = 0
        for pos in self.current_positions:
            if pos.get('profit', 0) < 0:
                success, msg = self.trading_system.close_position(pos['ticket'])
                if success:
                    count += 1
        self.add_notification("Bulk Action", f"Closed {count} losing positions", "info")

    def close_profitable_positions(self):
        count = 0
        for pos in self.current_positions:
            if pos.get('profit', 0) > 0:
                success, msg = self.trading_system.close_position(pos['ticket'])
                if success:
                    count += 1
        self.add_notification("Bulk Action", f"Closed {count} profitable positions", "info")

    def close_all_positions(self):
        success, msg = self.trading_system.close_all_positions()
        self.add_notification("Bulk Action", msg, "success" if success else "error")

    def cancel_all_orders(self):
        if self.trading_system:
            orders = mt5.orders_get()
            if orders:
                count = 0
                for order in orders:
                    request = {"action": mt5.TRADE_ACTION_REMOVE, "order": order.ticket, "comment": "Cancel All"}
                    result = mt5.order_send(request)
                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        count += 1
                self.add_notification("Orders Cancelled", f"Cancelled {count} pending orders", "success")
            else:
                self.add_notification("No Orders", "No pending orders to cancel", "info")

    def reset_signal_counter(self):
        success, msg = self.trading_system.reset_signal_counter()
        self.add_notification("Counter Reset", msg, "success")

    def reset_session_counter(self):
        success, msg = self.trading_system.reset_session_counter()
        self.add_notification("Session Reset", msg, "success" if success else "error")

    def change_symbol(self):
        """Change the trading symbol - ensure the selected symbol is used."""
        symbol = self.symbol_var.get().strip()
        if not symbol:
            messagebox.showwarning("No Symbol", "Please select or type a symbol.")
            return
        
        if not self.trading_system:
            messagebox.showerror("Error", "Trading system not initialized.")
            return
        
        # First, try to find an exact match in available symbols
        exact_match = None
        for avail in self.available_symbols:
            if avail.upper() == symbol.upper():
                exact_match = avail
                break
        
        # Use exact match if found, otherwise use what user typed
        symbol_to_set = exact_match if exact_match else symbol
        
        success, msg = self.trading_system.change_symbol(symbol_to_set)
        if success:
            self.config.symbol = symbol_to_set
            self.save_config()
            self.symbol_display.config(text=f"Selected: {symbol_to_set}")
            # Update combobox to show the exact symbol (with correct capitalization)
            self.symbol_var.set(symbol_to_set)
            self.add_notification("Symbol Changed", f"Now trading {symbol_to_set}", "success")
        else:
            messagebox.showerror("Error", msg)
            # Revert combobox to current symbol if available
            if self.config.symbol:
                self.symbol_var.set(self.config.symbol)
            else:
                self.symbol_var.set("")

    def on_symbol_search(self, event):
        """Handle symbol search with proper debounce - don't interrupt typing."""
        # Cancel previous search timer
        if self.symbol_search_after_id:
            self.root.after_cancel(self.symbol_search_after_id)
        # Schedule new search after longer delay (800ms) to allow typing
        self.symbol_search_after_id = self.root.after(1000, self.perform_symbol_search)

    def perform_symbol_search(self):
        """Perform symbol search - only update dropdown, don't change typed text."""
        query = self.symbol_var.get().strip()
        
        # Only search if user has typed at least 2 characters
        if len(query) >= 2 and self.trading_system:
            matches = self.trading_system.search_symbols(query)
            if matches:
                # Store the current typed text
                current_text = self.symbol_var.get()
                # Update dropdown values
                self.symbol_combo['values'] = matches
                # Restore the typed text (combobox may have changed it)
                self.symbol_var.set(current_text)
                # Open dropdown to show matches
                self.symbol_combo.event_generate('<Down>')
            else:
                # No matches - show empty list
                self.symbol_combo['values'] = []
        elif len(query) == 0:
            # If query is empty, restore full symbol list
            self.symbol_combo['values'] = self.available_symbols

    def refresh_symbols(self):
        """Refresh available symbols list without changing current selection."""
        if self.trading_system:
            self.available_symbols = self.trading_system.scan_available_symbols()
            # Store current value before updating dropdown
            current_value = self.symbol_var.get()
            self.symbol_combo['values'] = self.available_symbols
            # Restore current value (don't lose what user typed)
            if current_value:
                self.symbol_var.set(current_value)

    def save_settings(self):
        try:
            self.config.enable_trailing_stop_loss = self.trailing_var.get()
            self.config.lock_amount_dollars = float(self.lock_amount_entry.get())
            self.config.step_amount_dollars = float(self.step_amount_entry.get())
            self.config.enable_stop_loss = self.enable_sl_var.get()
            self.config.enable_take_profit = self.enable_tp_var.get()
            self.config.stop_loss_pips = float(self.sl_pips_entry.get())
            self.config.take_profit_pips = float(self.tp_pips_entry.get())
            self.config.close_opposite_on_signal_change = self.close_opposite_var.get()
            if hasattr(self, 'reversal_lot_size'):
                self.config.reversal_trade_volume = float(self.reversal_lot_size.get())
            if hasattr(self, 'reversal_min_conf'):
                self.config.reversal_min_confidence_score = float(self.reversal_min_conf.get())
            if hasattr(self, 'reversal_cooldown'):
                self.config.reversal_cooldown_seconds = int(self.reversal_cooldown.get())
            if self.trading_system:
                self.trading_system.config = self.config
                self.trading_system.reversal_trader.config = self.config
                self.trading_system.trailing_stop.update_config(
                    self.config.enable_trailing_stop_loss,
                    self.config.lock_amount_dollars,
                    self.config.step_amount_dollars
                )
            self.save_config()
            self.add_notification("Settings", "Settings saved successfully", "success")
        except ValueError as e:
            messagebox.showerror("Error", "Invalid input values")

    def update_trailing_config(self):
        try:
            enabled = self.trailing_var.get()
            lock_amount = float(self.lock_amount_entry.get())
            step_amount = float(self.step_amount_entry.get())
            self.config.enable_trailing_stop_loss = enabled
            self.config.lock_amount_dollars = lock_amount
            self.config.step_amount_dollars = step_amount
            if self.trading_system:
                self.trading_system.config.enable_trailing_stop_loss = enabled
                self.trading_system.config.lock_amount_dollars = lock_amount
                self.trading_system.config.step_amount_dollars = step_amount
                self.trading_system.trailing_stop.update_config(enabled, lock_amount, step_amount)
            self.save_config()
            self.add_notification("Step Trailing Config", f"Step trailing configuration updated\n• Enabled: {enabled}\n• Lock Amount: ${lock_amount}\n• Step Amount: ${step_amount}", "success")
        except ValueError:
            messagebox.showerror("Error", "Invalid input values - please enter numbers only")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to update config: {str(e)}")

    def apply_trailing_all(self):
        success, msg = self.trading_system.apply_trailing_to_all_positions()
        self.add_notification("Trailing Stop", msg, "success" if success else "error")
        if success:
            self.trailing_update_pending = True
            self.pending_updates['trailing'] = True

    def refresh_trailing_stats(self):
        if self.trading_system and self.trading_system.trailing_stop:
            self.trading_system.force_trailing_stats_update()
            self.add_notification("Trailing Stats", "Refreshing trailing statistics...", "info")

    # ========== MT5 Connection Methods ==========
    def connect_local_mt5(self):
        try:
            self.broker_status_label.config(text="● CONNECTING...", fg=self.colors['accent_warning'])
            self.root.update()
            try:
                mt5.shutdown()
            except:
                pass
            terminal_path = self.mt5_path.get().strip()
            if terminal_path and os.path.exists(terminal_path):
                success = mt5.initialize(path=terminal_path)
            else:
                success = mt5.initialize()
            if not success:
                error = mt5.last_error()
                self.broker_status_label.config(text="● CONNECTION FAILED", fg=self.colors['accent_danger'])
                self.add_notification("MT5 Connection", f"Failed: {error}", "error")
                return False
            account_info = mt5.account_info()
            if account_info:
                self.update_account_info_display(account_info)
                self.broker_status_label.config(text="● CONNECTED", fg=self.colors['accent_success'])
                self.broker_account_label.config(text=f"Account: {account_info.login} ({account_info.name})")
                self.connect_local_btn.config(state='disabled')
                self.connect_remote_btn.config(state='disabled')
                self.disconnect_btn.config(state='normal')
                if self.trading_system:
                    self.trading_system.mt5_connected = True
                    self.trading_system.sync_existing_positions_with_trailing()
                    self.perform_full_refresh()
                if not terminal_path:
                    terminal_info = mt5.terminal_info()
                    if terminal_info and hasattr(terminal_info, 'path'):
                        self.mt5_path.delete(0, tk.END)
                        self.mt5_path.insert(0, terminal_info.path)
                self.broker_connected = True
                self.add_notification("MT5 Connection", "Connected to MT5 successfully", "success")
                self.perform_full_refresh()
                return True
            else:
                self.broker_status_label.config(text="● NO ACCOUNT", fg=self.colors['accent_warning'])
                self.add_notification("MT5 Connection", "Connected but no account loaded", "warning")
                return False
        except Exception as e:
            self.broker_status_label.config(text="● ERROR", fg=self.colors['accent_danger'])
            self.add_notification("MT5 Connection", f"Error: {str(e)}", "error")
            return False

    def connect_remote_mt5(self):
        try:
            server = self.broker_server.get().strip()
            login_str = self.broker_login.get().strip()
            password = self.broker_password.get()
            if not server or not login_str or not password:
                self.add_notification("MT5 Connection", "Please fill in all fields", "warning")
                return False
            try:
                login = int(login_str)
            except ValueError:
                self.add_notification("MT5 Connection", "Login must be a number", "error")
                return False
            self.broker_status_label.config(text="● CONNECTING...", fg=self.colors['accent_warning'])
            self.root.update()
            try:
                mt5.shutdown()
            except:
                pass
            if not mt5.initialize():
                error = mt5.last_error()
                self.broker_status_label.config(text="● INIT FAILED", fg=self.colors['accent_danger'])
                self.add_notification("MT5 Connection", f"Init failed: {error}", "error")
                return False
            authorized = mt5.login(login=login, password=password, server=server)
            if not authorized:
                error = mt5.last_error()
                self.broker_status_label.config(text="● LOGIN FAILED", fg=self.colors['accent_danger'])
                self.add_notification("MT5 Connection", f"Login failed: {error}", "error")
                return False
            account_info = mt5.account_info()
            if account_info:
                self.update_account_info_display(account_info)
                self.broker_status_label.config(text="● CONNECTED", fg=self.colors['accent_success'])
                self.broker_account_label.config(text=f"Account: {account_info.login} ({account_info.name})")
                self.connect_local_btn.config(state='disabled')
                self.connect_remote_btn.config(state='disabled')
                self.disconnect_btn.config(state='normal')
                if self.trading_system:
                    self.trading_system.mt5_connected = True
                    self.trading_system.sync_existing_positions_with_trailing()
                    self.perform_full_refresh()
                if self.save_credentials_var.get() and CRYPTO_AVAILABLE:
                    self.save_broker_credentials(server, login_str, password)
                self.add_notification("MT5 Connection", f"Connected to {server}", "success")
                terminal_info = mt5.terminal_info()
                if terminal_info and hasattr(terminal_info, 'path'):
                    self.mt5_path.delete(0, tk.END)
                    self.mt5_path.insert(0, terminal_info.path)
                self.broker_connected = True
                self.perform_full_refresh()
                return True
            else:
                self.broker_status_label.config(text="● NO ACCOUNT", fg=self.colors['accent_warning'])
                return False
        except Exception as e:
            self.broker_status_label.config(text="● ERROR", fg=self.colors['accent_danger'])
            self.add_notification("MT5 Connection", f"Error: {str(e)}", "error")
            return False

    def disconnect_mt5(self):
        if self.trading_system:
            self.trading_system.manual_disconnect = False
        try:
            mt5.shutdown()
            self.broker_status_label.config(text="● DISCONNECTED", fg=self.colors['accent_danger'])
            self.broker_account_label.config(text="No account connected")
            self.broker_balance.config(text="$0.00")
            self.broker_equity.config(text="$0.00")
            self.broker_margin.config(text="$0.00")
            self.broker_free_margin.config(text="$0.00")
            self.broker_server_info.config(text="Not connected")
            self.broker_terminal.config(text="Not connected")
            self.connect_local_btn.config(state='normal')
            self.connect_remote_btn.config(state='normal')
            self.disconnect_btn.config(state='disabled')
            if self.trading_system:
                self.trading_system.mt5_connected = False
                self.perform_full_refresh()
            self.broker_connected = False
            self.add_notification("MT5 Connection", "Disconnected from MT5", "info")
        except Exception as e:
            self.add_notification("MT5 Connection", f"Error disconnecting: {str(e)}", "error")

    def update_account_info_display(self, account_info):
        if account_info:
            self.broker_balance.config(text=f"${account_info.balance:.2f}")
            self.broker_equity.config(text=f"${account_info.equity:.2f}")
            self.broker_margin.config(text=f"${account_info.margin:.2f}")
            self.broker_free_margin.config(text=f"${account_info.margin_free:.2f}")
            self.broker_server_info.config(text=account_info.server)
            terminal_info = mt5.terminal_info()
            if terminal_info:
                self.broker_terminal.config(text=terminal_info.name)

    def test_mt5_connection(self):
        try:
            terminal_info = mt5.terminal_info()
            if terminal_info:
                account_info = mt5.account_info()
                if account_info:
                    msg = (f"✅ Connected to {account_info.server}\nAccount: {account_info.login}\nBalance: ${account_info.balance:.2f}\nEquity: ${account_info.equity:.2f}\nMargin: ${account_info.margin:.2f}\nFree Margin: ${account_info.margin_free:.2f}\nTerminal: {terminal_info.name}")
                    messagebox.showinfo("Connection Test", msg)
                else:
                    msg = (f"✅ Connected to terminal but no account loaded\nTerminal: {terminal_info.name}\nPath: {terminal_info.path}")
                    messagebox.showinfo("Connection Test", msg)
            else:
                messagebox.showwarning("Connection Test", "❌ Not connected to MT5")
        except Exception as e:
            messagebox.showerror("Connection Test", f"Error: {str(e)}")

    def detect_mt5_path(self):
        common_paths = [
            "C:\\Program Files\\MetaTrader 5\\terminal.exe",
            "C:\\Program Files (x86)\\MetaTrader 5\\terminal.exe",
            os.path.expanduser("~\\AppData\\Roaming\\MetaQuotes\\Terminal\\Common\\terminal.exe"),
        ]
        for path in common_paths:
            if os.path.exists(path):
                self.mt5_path.delete(0, tk.END)
                self.mt5_path.insert(0, path)
                self.add_notification("MT5 Path", f"Found at: {path}", "success")
                return
        self.add_notification("MT5 Path", "Could not auto-detect MT5", "warning")

    def browse_mt5_path(self):
        filename = filedialog.askopenfilename(title="Select MetaTrader 5 Terminal", filetypes=[("Executable files", "*.exe"), ("All files", "*.*")])
        if filename:
            self.mt5_path.delete(0, tk.END)
            self.mt5_path.insert(0, filename)

    def save_broker_credentials(self, server, login, password):
        try:
            if not CRYPTO_AVAILABLE:
                self.add_notification("Credentials", "Cryptography library not installed. Install with: pip install cryptography", "warning")
                return False
            machine_id = hashlib.sha256(f"{platform.node()}{os.environ.get('USERNAME', '')}".encode()).digest()
            kdf = PBKDF2(algorithm=hashes.SHA256(), length=32, salt=b'uwezo_fx_salt', iterations=100000)
            key = base64.urlsafe_b64encode(kdf.derive(machine_id))
            cipher = Fernet(key)
            creds = {'server': server, 'login': login, 'password': password}
            encrypted = cipher.encrypt(json.dumps(creds).encode())
            with open(self.broker_credentials_file, 'wb') as f:
                f.write(encrypted)
            self.add_notification("Credentials", "Broker credentials saved securely", "success")
            self.load_saved_connections()
            return True
        except Exception as e:
            self.add_notification("Credentials", f"Failed to save: {str(e)}", "error")
            return False

    def load_saved_connections(self):
        try:
            if not CRYPTO_AVAILABLE:
                return []
            if not os.path.exists(self.broker_credentials_file):
                return []
            with open(self.broker_credentials_file, 'rb') as f:
                encrypted = f.read()
            machine_id = hashlib.sha256(f"{platform.node()}{os.environ.get('USERNAME', '')}".encode()).digest()
            kdf = PBKDF2(algorithm=hashes.SHA256(), length=32, salt=b'uwezo_fx_salt', iterations=100000)
            key = base64.urlsafe_b64encode(kdf.derive(machine_id))
            cipher = Fernet(key)
            decrypted = cipher.decrypt(encrypted)
            creds = json.loads(decrypted.decode())
            self.saved_connections_listbox.delete(0, tk.END)
            self.saved_connections_listbox.insert(tk.END, f"{creds['server']} - {creds['login']}")
            return [creds]
        except Exception as e:
            self.add_notification("Credentials", f"Failed to load: {str(e)}", "error")
            return []

    def load_saved_connection(self):
        selection = self.saved_connections_listbox.curselection()
        if not selection:
            return
        try:
            with open(self.broker_credentials_file, 'rb') as f:
                encrypted = f.read()
            machine_id = hashlib.sha256(f"{platform.node()}{os.environ.get('USERNAME', '')}".encode()).digest()
            kdf = PBKDF2(algorithm=hashes.SHA256(), length=32, salt=b'uwezo_fx_salt', iterations=100000)
            key = base64.urlsafe_b64encode(kdf.derive(machine_id))
            cipher = Fernet(key)
            decrypted = cipher.decrypt(encrypted)
            creds = json.loads(decrypted.decode())
            self.broker_server.delete(0, tk.END)
            self.broker_server.insert(0, creds['server'])
            self.broker_login.delete(0, tk.END)
            self.broker_login.insert(0, creds['login'])
            self.broker_password.delete(0, tk.END)
            self.broker_password.insert(0, creds['password'])
            self.add_notification("Credentials", "Connection loaded", "success")
        except Exception as e:
            self.add_notification("Credentials", f"Failed to load: {str(e)}", "error")

    def delete_saved_connection(self):
        if os.path.exists(self.broker_credentials_file):
            os.remove(self.broker_credentials_file)
            self.saved_connections_listbox.delete(0, tk.END)
            self.add_notification("Credentials", "Saved credentials deleted", "info")

    def toggle_reversal_mode(self):
        if not self.trading_system:
            messagebox.showerror("Error", "Trading system not initialized")
            return
        new_state = not self.reversal_mode_enabled
        if new_state:
            min_conf = float(self.min_confidence_var.get())
            if min_conf <= 0:
                warning_msg = ("⚠️ WARNING: Min Confidence is set to 0%\n\nThis means EVERY signal reversal will trigger 5 trades automatically,\nregardless of market conditions or indicator confirmations.\n\nThis is HIGH RISK and should only be used for testing.\n\nAre you sure you want to proceed?")
            else:
                warning_msg = (f"⚠️ WARNING: Enabling reversal trading will check 11 confirmation indicators before executing 5 trades on signal reversal.\n\nCurrent minimum confidence threshold: {min_conf}%\nThese trades bypass normal session limits and will only execute if confidence threshold is met.\n\nAre you sure you want to enable this feature?")
            confirm = messagebox.askyesno("Enable Reversal Trading", warning_msg, icon='warning')
            if not confirm:
                return
        self.reversal_mode_enabled = new_state
        if new_state:
            min_conf = float(self.min_confidence_var.get())
            if min_conf <= 0:
                button_text = "⚡ REVERSAL MODE: ON (0% - ALL SIGNALS)"
                self.reversal_button.config(text=button_text, bg=self.colors['accent_warning'])
                self.add_notification("⚡ Reversal Trading (0%)", "Reversal mode ENABLED with 0% confidence - ALL reversals will execute!", "warning")
            else:
                button_text = f"🟢 REVERSAL MODE: ON ({min_conf}%)"
                self.reversal_button.config(text=button_text, bg=self.colors['accent_success'])
                self.add_notification("⚡ Reversal Trading", f"Reversal mode ENABLED - Will check 10 confirmations (min {min_conf}%)", "warning")
        else:
            self.reversal_button.config(text="🔴 REVERSAL MODE: OFF", bg=self.colors['accent_danger'])
            self.add_notification("⚡ Reversal Trading", "Reversal mode DISABLED", "info")
        if self.trading_system:
            self.trading_system.toggle_reversal_mode(new_state)
        self.config.enable_reversal_trading = new_state
        self.save_config()

    def update_reversal_confidence(self, event=None):
        try:
            new_confidence = float(self.min_confidence_var.get())
            if hasattr(self, 'reversal_min_conf_var'):
                self.reversal_min_conf_var.set(str(new_confidence))
            if self.trading_system:
                self.trading_system.config.reversal_min_confidence_score = new_confidence
                self.trading_system.reversal_trader.config.reversal_min_confidence_score = new_confidence
            self.save_config()
        except ValueError:
            pass

    def refresh_reversal_stats(self):
        if self.trading_system and hasattr(self.trading_system, 'reversal_trader'):
            reversal_history = self.trading_system.reversal_trader.reversal_history
            total = len(reversal_history)
            executed = sum(1 for r in reversal_history if r.get('should_trade', False))
            skipped = total - executed
            avg_conf = np.mean([r.get('confidence', 0) for r in reversal_history]) if reversal_history else 0
            if hasattr(self, 'total_reversals_val'):
                self.total_reversals_val.config(text=str(total))
            if hasattr(self, 'executed_reversals_val'):
                self.executed_reversals_val.config(text=str(executed))
            if hasattr(self, 'skipped_reversals_val'):
                self.skipped_reversals_val.config(text=str(skipped))
            if hasattr(self, 'avg_confidence_val'):
                self.avg_confidence_val.config(text=f"{avg_conf:.1f}%")
            if hasattr(self, 'reversal_history_tree'):
                for item in self.reversal_history_tree.get_children():
                    self.reversal_history_tree.delete(item)
                for rev in reversed(reversal_history[-20:]):
                    values = (rev['timestamp'][11:19] if 'T' in rev['timestamp'] else rev['timestamp'], rev.get('old_signal', ''), rev.get('new_signal', ''), f"{rev.get('confidence', 0):.1f}%", "✅ EXECUTED" if rev.get('should_trade') else "❌ SKIPPED", f"{rev.get('passed_checks', 0)}/10")
                    item = self.reversal_history_tree.insert('', 0, values=values)
                    if rev.get('should_trade'):
                        self.reversal_history_tree.tag_configure('executed', foreground='#10b981')
                        self.reversal_history_tree.item(item, tags=('executed',))
                    else:
                        self.reversal_history_tree.tag_configure('skipped', foreground='#f59e0b')
                        self.reversal_history_tree.item(item, tags=('skipped',))

    def fetch_news(self):
        if self.trading_system and hasattr(self, 'sentiment_label'):
            self.sentiment_label.config(text="LOADING...", fg=self.colors['accent_warning'])
            self.root.update()
            news = self.trading_system.news_manager.fetch_news(force_refresh=True)
            self.display_news(news)

    def display_news(self, news_data):
        for widget in self.news_items_frame.winfo_children():
            widget.destroy()
        if isinstance(news_data, dict):
            news = news_data.get('news', [])
            sentiment = news_data.get('sentiment', {})
        else:
            news = news_data
            sentiment = self.trading_system.news_manager.get_market_sentiment() if self.trading_system else {}
        if sentiment:
            mood = sentiment.get('overall_sentiment', 'NEUTRAL')
            score = sentiment.get('sentiment_score', 0)
            confidence = sentiment.get('confidence', 'LOW')
            if mood == 'BULLISH':
                color = self.colors['accent_success']
            elif mood == 'BEARISH':
                color = self.colors['accent_danger']
            else:
                color = self.colors['text_secondary']
            self.sentiment_label.config(text=mood, fg=color)
            self.sentiment_score.config(text=f"Score: {score:.2f}")
            self.sentiment_confidence.config(text=f"Confidence: {confidence}")
        if not news:
            tk.Label(self.news_items_frame, text="No news available", fg=self.colors['text_secondary'], bg=self.colors['bg_dark'], font=('Segoe UI', 11)).pack(pady=20)
            return
        high_count = len([n for n in news if n.get('impact') == 'High'])
        medium_count = len([n for n in news if n.get('impact') == 'Medium'])
        bullish_count = len([n for n in news if n.get('sentiment', {}).get('label') in ['BULLISH', 'STRONG_BULLISH']])
        bearish_count = len([n for n in news if n.get('sentiment', {}).get('label') in ['BEARISH', 'STRONG_BEARISH']])
        self.high_impact_label.config(text=f"High Impact: {high_count}")
        self.medium_impact_label.config(text=f"Medium Impact: {medium_count}")
        self.bullish_label.config(text=f"Bullish: {bullish_count}")
        self.bearish_label.config(text=f"Bearish: {bearish_count}")
        if self.trading_system:
            recommendations = self.trading_system.news_manager.get_trading_recommendations()
            self.recommendations_text.delete(1.0, tk.END)
            for rec in recommendations[:5]:
                signal_color = self.colors['accent_success'] if rec['signal'] == 'BUY' else self.colors['accent_danger'] if rec['signal'] == 'SELL' else self.colors['text_secondary']
                self.recommendations_text.insert(tk.END, f"{rec['pair']}: ")
                self.recommendations_text.insert(tk.END, f"{rec['signal']} ", ('signal', signal_color))
                self.recommendations_text.insert(tk.END, f"({rec['strength']}) - {rec['entry_strategy']}\n")
                self.recommendations_text.insert(tk.END, f"   SL: {rec['stop_loss']} | TP: {rec['take_profit']}\n\n")
            self.recommendations_text.tag_configure('signal', foreground='green')
        for item in news:
            card = tk.Frame(self.news_items_frame, bg=self.colors['bg_card'])
            card.pack(fill=tk.X, pady=5)
            ModernUI.add_glow_effect(card, self.colors['accent_primary'])
            impact = item.get('impact', 'Medium')
            impact_color = self.colors['accent_danger'] if impact == 'High' else self.colors['accent_warning'] if impact == 'Medium' else self.colors['accent_info']
            title_frame = tk.Frame(card, bg=self.colors['bg_card'])
            title_frame.pack(fill=tk.X, padx=10, pady=(5,0))
            tk.Label(title_frame, text=item.get('event', 'Economic Event'), font=('Segoe UI', 12, 'bold'), fg=impact_color, bg=self.colors['bg_card']).pack(side=tk.LEFT)
            tk.Label(title_frame, text=f"  {item.get('time', '')}", fg=self.colors['text_secondary'], bg=self.colors['bg_card'], font=('Segoe UI', 10)).pack(side=tk.LEFT)
            info_frame = tk.Frame(card, bg=self.colors['bg_card'])
            info_frame.pack(anchor='w', padx=10, pady=2)
            tk.Label(info_frame, text=f"Country: {item.get('country', 'N/A')}", fg=self.colors['accent_info'], bg=self.colors['bg_card'], font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=5)
            sentiment = item.get('sentiment', {})
            sentiment_label = sentiment.get('label', 'NEUTRAL')
            sentiment_score = sentiment.get('score', 0)
            if sentiment_label in ['STRONG_BULLISH', 'BULLISH']:
                sent_color = self.colors['accent_success']
            elif sentiment_label in ['STRONG_BEARISH', 'BEARISH']:
                sent_color = self.colors['accent_danger']
            else:
                sent_color = self.colors['text_secondary']
            tk.Label(info_frame, text=f"Sentiment: {sentiment_label} ({sentiment_score:.2f})", fg=sent_color, bg=self.colors['bg_card'], font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=5)
            prediction = item.get('prediction', {})
            if prediction:
                pred_frame = tk.Frame(card, bg=self.colors['bg_card'])
                pred_frame.pack(anchor='w', padx=10, pady=2)
                direction = prediction.get('direction', 'VOLATILE')
                dir_color = self.colors['accent_success'] if direction == 'UP' else self.colors['accent_danger'] if direction == 'DOWN' else self.colors['accent_warning']
                tk.Label(pred_frame, text=f"Prediction: {direction} {prediction.get('expected_pips', 0)} pips", fg=dir_color, bg=self.colors['bg_card'], font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT, padx=5)
                tk.Label(pred_frame, text=f"Confidence: {prediction.get('confidence', 'LOW')}", fg=self.colors['text_secondary'], bg=self.colors['bg_card'], font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=5)
            forecast_frame = tk.Frame(card, bg=self.colors['bg_card'])
            forecast_frame.pack(anchor='w', padx=10, pady=2)
            tk.Label(forecast_frame, text=f"Forecast: {item.get('forecast', 'N/A')} | Previous: {item.get('previous', 'N/A')}", fg=self.colors['text_secondary'], bg=self.colors['bg_card'], font=('Segoe UI', 10)).pack(side=tk.LEFT)

    def on_news_frame_configure(self, event):
        self.news_canvas.configure(scrollregion=self.news_canvas.bbox('all'))

    def on_position_double_click(self, event):
        selection = self.positions_tree.selection()
        if selection:
            item = self.positions_tree.item(selection[0])
            values = item['values']
            if values:
                ticket = values[0]
                if messagebox.askyesno("Confirm", f"Close position #{ticket}?"):
                    success, msg = self.trading_system.close_position(ticket)
                    self.add_notification("Position Closed", msg, "success" if success else "error")

    def add_notification(self, title, message, level='info'):
        timestamp = datetime.now().strftime("%H:%M:%S")
        emoji_map = {'info': 'ℹ️', 'success': '✅', 'warning': '⚠️', 'error': '❌', 'critical': '🚨'}
        emoji = emoji_map.get(level, '📌')
        formatted_msg = f"{emoji} [{timestamp}] {title}"
        if message:
            lines = message.split('\n')
            formatted_msg += f"\n   {lines[0]}"
            for line in lines[1:]:
                formatted_msg += f"\n   {line}"
        self.notifications.insert(0, formatted_msg)
        if len(self.notifications) > 100:
            self.notifications.pop()
        self.notifications_list.delete(0, tk.END)
        for i, notif in enumerate(self.notifications[:15]):
            self.notifications_list.insert(tk.END, notif)
            if '❌' in notif or 'error' in notif.lower() or 'failed' in notif.lower():
                self.notifications_list.itemconfig(i, fg=self.colors['accent_danger'])
            elif '✅' in notif or 'success' in notif.lower():
                self.notifications_list.itemconfig(i, fg=self.colors['accent_success'])
            elif '⚠️' in notif or 'warning' in notif.lower():
                self.notifications_list.itemconfig(i, fg=self.colors['accent_warning'])
            elif 'ℹ️' in notif:
                self.notifications_list.itemconfig(i, fg=self.colors['accent_info'])
            else:
                self.notifications_list.itemconfig(i, fg=self.colors['text_primary'])
        self.notifications_list.yview_moveto(0)
        print(f"{emoji} {title}: {message}")

    def switch_section(self, section):
        self.current_section = section
        titles = {
            'dashboard': 'Dashboard',
            'trading': 'Trading Signal',
            'positions': 'Positions & Orders',
            'news': 'News & Sentiment',
            'settings': 'Settings',
            'trailing': 'Trailing Stop',
            'alerts': 'Alert System',
            'reversal': 'Reversal Statistics'
        }
        self.page_title.config(text=titles.get(section, 'Dashboard'))
        for s in self.sections.values():
            s.pack_forget()
        self.sections[section].pack(fill=tk.BOTH, expand=True)
        for s, btn in self.nav_vars.items():
            btn.config(fg=self.colors['accent_primary'] if s == section else self.colors['text_secondary'])
        if section == 'news':
            self.fetch_news()
        elif section == 'trailing':
            self.trailing_update_pending = True
        elif section == 'reversal':
            self.refresh_reversal_stats()

    def process_urgent_callbacks(self):
        try:
            for _ in range(10):
                try:
                    callback = self.callback_queue.get_nowait()
                    self.handle_urgent_callback(callback)
                except queue.Empty:
                    break
        except Exception as e:
            print(f"Callback processing error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.root.after(50, self.process_urgent_callbacks)

    def handle_urgent_callback(self, callback):
        if not self.is_logged_in:
            return
        try:
            if isinstance(callback, tuple) and len(callback) >= 2:
                cb_type, data = callback[0], callback[1]
                if cb_type == 'notification':
                    self.add_notification(data.get('title', 'Notification'), data.get('message', ''), data.get('priority', 'info').lower())
                elif cb_type == 'position_closed':
                    self._update_ui_from_system()
                    profit = data.get('profit', 0)
                    close_type = data.get('type', 'manual')
                    title = "🔴 Stop Loss Hit" if close_type == 'stop_loss' else "✅ Take Profit Hit" if close_type == 'take_profit' else "📊 Position Closed"
                    self.add_notification(title, f"Position #{data.get('ticket')} closed with P&L: ${profit:.2f}", 'info')
                    self.trailing_update_pending = True
                elif cb_type == 'trade_executed':
                    direction = data.get('direction', '')
                    volume = data.get('volume', 0)
                    price = data.get('price', 0)
                    msg = f"{direction} {volume} lots at {price:.2f}"
                    self.add_notification("✅ Trade Executed", msg, "success")
                    self._update_ui_from_system()
                    self.trailing_update_pending = True
                elif cb_type == 'signal_changed':
                    self._update_ui_from_system()
                    old_signal = data.get('old', 'NEUTRAL')
                    new_signal = data.get('new', 'NEUTRAL')
                    if old_signal != new_signal:
                        emoji = "🟢" if new_signal == 'BUY' else "🔴" if new_signal == 'SELL' else "⚪"
                        msg = f"{emoji} Signal changed: {old_signal} → {new_signal}"
                        self.add_notification("📊 Signal Changed", msg, 'info')
                elif cb_type == 'error':
                    self.add_notification("❌ Error", str(data), 'error')
                elif cb_type == 'system_ready':
                    if data.get('connected'):
                        self.connection_indicator.config(fg=self.colors['accent_success'])
                        self.connection_label.config(text="LIVE", fg=self.colors['accent_success'])
                        self.add_notification("✅ System Ready", "Connected to MT5 successfully", "success")
                    else:
                        self.connection_indicator.config(fg=self.colors['accent_warning'])
                        self.connection_label.config(text="SIMULATED", fg=self.colors['accent_warning'])
                        self.add_notification("⚠️ Limited Mode", "MT5 not connected - using simulated data", "warning")
                elif cb_type == 'trailing_stats_update':
                    stats = data.get('stats', {})
                    self.update_trailing_stats_from_data(stats)
                    self.trailing_update_pending = False
                elif cb_type == 'profit_locked':
                    ticket = data.get('ticket')
                    locked = data.get('locked_amount', 0)
                    self.add_notification("🔒 Profit Locked", f"Position {ticket}: ${locked:.2f} locked", "success")
                    self.trailing_update_pending = True
                elif cb_type == 'reversal_skipped':
                    reason = data.get('reason', '')
                    confidence = data.get('confidence', 0)
                    self.add_notification("⏸️ Reversal Skipped", f"{reason} (Confidence: {confidence:.1f}%)", "warning")
                elif cb_type == 'reversal_trade_executed':
                    trade_num = data.get('trade_number', 0)
                    total = data.get('total', 5)
                    direction = data.get('direction')
                    volume = data.get('volume')
                    price = data.get('price')
                    self.add_notification(f"⚡ Reversal Trade {trade_num}/{total}", f"{direction} {volume} lots at {price:.2f}", "success")
                    self.reversal_trades_count = trade_num
                    if hasattr(self, 'reversal_trades_label'):
                        self.reversal_trades_label.config(text=f"{trade_num}/{total}")
                
                elif cb_type == 'reversal_trade_failed':
                    trade_num = data.get('trade_number', 0)
                    total = data.get('total', 5)
                    direction = data.get('direction')
                    volume = data.get('volume')
                    price = data.get('price')
                    reason = data.get('reason', 'Unknown error')
                    confidence = data.get('confidence', 0)
                    timestamp = data.get('timestamp', datetime.now().isoformat())

                    # Add notification
                    self.add_notification(f"❌ Reversal Trade {trade_num}/{total} Failed",
                                        f"{direction} {volume} lots at {price:.2f}\nReason: {reason}",
                                        "error")

                    # Insert into reversal history tree
                    if hasattr(self, 'reversal_history_tree'):
                        time_str = timestamp[11:19] if 'T' in timestamp else timestamp
                        values = (time_str, f"REV{trade_num}", direction, f"{confidence:.1f}%",
                                "❌ REJECTED", reason[:50] + "..." if len(reason) > 50 else reason)
                        item = self.reversal_history_tree.insert('', 0, values=values)
                        self.reversal_history_tree.tag_configure('failed', foreground='#ef4444')
                        self.reversal_history_tree.item(item, tags=('failed',))

                elif cb_type == 'reversal_complete':
                    success_count = data.get('success_count', 0)
                    total = data.get('total', 5)
                    message = data.get('message', '')
                    if hasattr(self, 'last_reversal_label'):
                        self.last_reversal_label.config(text=datetime.now().strftime("%H:%M:%S"))
                    self.add_notification("✅ Reversal Complete", message, "success" if success_count > 0 else "warning")
                    self.refresh_reversal_stats()

                elif cb_type == 'pending_order_cancelled':
                    ticket = data.get('ticket')
                    symbol = data.get('symbol')
                    age = data.get('age', 0)
                    reason = data.get('reason', 'unknown')
                    self.add_notification("⏰ Pending Order Cancelled", 
                                        f"Order {ticket} ({symbol}) cancelled after {age:.0f}s - {reason}", 
                                        "warning")

                elif cb_type == 'data_update':
                    if isinstance(data, dict):
                        if 'dashboard' in data:
                            self.update_dashboard(data['dashboard'])
                            if 'current_price' in data['dashboard'] and hasattr(self, 'mini_chart'):
                                self.mini_chart.update_data(data['dashboard']['current_price'])
                        if 'positions' in data:
                            self.update_positions_display(data['positions'])
                        if 'dashboard' in data and 'trailing_stop_data' in data['dashboard']:
                            self.update_trailing_stats_from_data(data['dashboard']['trailing_stop_data'])
        except Exception as e:
            print(f"Error handling callback: {e}")
            import traceback
            traceback.print_exc()

    def periodic_refresh(self):
        """Auto-refresh loop - runs every second when logged in."""
        print(f"periodic_refresh: is_logged_in={self.is_logged_in}, time={time.time()}")
        if not self.is_logged_in:
            self.root.after(1000, self.periodic_refresh)
            return

        try:
            current_time = time.time()
            # Force a full reload every refresh_interval seconds
            if current_time - self.last_full_refresh >= self.refresh_interval:
                print("Executing full reload...")
                self._full_reload_data(silent=True)
                self.last_full_refresh = current_time
                self.pending_updates.clear()
                self.trailing_update_pending = False

            # ALWAYS update the refresh status label with the last refresh time
            if hasattr(self, 'refresh_status') and self.refresh_status:
                last_refresh_time = datetime.fromtimestamp(self.last_full_refresh).strftime('%H:%M:%S')
                self.refresh_status.config(text=f"Auto: {last_refresh_time}")
                print(f"Updated refresh status to Auto: {last_refresh_time}")
            else:
                print("refresh_status not available")

            # Handle pending updates and trailing stats
            if self.pending_updates:
                self.apply_pending_updates()
            if self.trailing_update_pending:
                if self.trading_system and self.trading_system.trailing_stop:
                    self.trading_system.force_trailing_stats_update()
                self.trailing_update_pending = False

        except Exception as e:
            print(f"Refresh error: {e}")
            import traceback
            traceback.print_exc()

        self.root.after(1000, self.periodic_refresh)

    def apply_pending_updates(self):
        if not self.is_logged_in:
            return
        try:
            if not isinstance(self.pending_updates, dict):
                self.pending_updates = {}
                return
            if 'dashboard' in self.pending_updates and self.pending_updates['dashboard']:
                if isinstance(self.pending_updates['dashboard'], dict):
                    self.update_dashboard(self.pending_updates['dashboard'])
                    if 'trailing_stop_data' in self.pending_updates['dashboard']:
                        self.update_trailing_stats_from_data(self.pending_updates['dashboard']['trailing_stop_data'])
            if 'positions' in self.pending_updates and self.pending_updates['positions']:
                if isinstance(self.pending_updates['positions'], list):
                    self.update_positions_display(self.pending_updates['positions'])
            if 'trailing' in self.pending_updates:
                if self.trading_system and self.trading_system.trailing_stop:
                    self.trading_system.force_trailing_stats_update()
                self.pending_updates.pop('trailing', None)
        except Exception as e:
            print(f"Pending updates error: {e}")
            import traceback
            traceback.print_exc()

    def remove_position_from_display(self, ticket):
        for item in self.positions_tree.get_children():
            values = self.positions_tree.item(item)['values']
            if values and values[0] == ticket:
                self.positions_tree.delete(item)
                break

    def update_signal_display(self, signal_data):
        new_signal = signal_data.get('new', 'NEUTRAL')
        if new_signal == 'BUY':
            self.signal_badge.config(text="BUY", fg=self.colors['accent_success'])
            self.trading_signal.config(text="BUY", fg=self.colors['accent_success'])
        elif new_signal == 'SELL':
            self.signal_badge.config(text="SELL", fg=self.colors['accent_danger'])
            self.trading_signal.config(text="SELL", fg=self.colors['accent_danger'])
        else:
            self.signal_badge.config(text="NEUTRAL", fg=self.colors['text_secondary'])
            self.trading_signal.config(text="NEUTRAL", fg=self.colors['text_secondary'])
        if signal_data.get('entry_price'):
            self.entry_price_label.config(text=f"{signal_data['entry_price']:.2f}")
        self.entry_type_label.config(text=signal_data.get('entry_type', '—'))
        self.signal_comment.config(text=signal_data.get('comment', '—'))
        self._last_signal_update = time.time()

    def update_dashboard(self, data):
        self.balance_val.config(text=f"${data.get('balance', 0):.2f}")
        self.equity_val.config(text=f"${data.get('equity', 0):.2f}")
        self.drawdown_val.config(text=f"{data.get('drawdown', 0):.2f}%")
        self.today_trades_val.config(text=str(data.get('today_trades', 0)))
        if not hasattr(self, '_last_signal_update') or time.time() - self._last_signal_update > 1:
            signal = data.get('current_signal', 'NEUTRAL')
            if signal == 'BUY':
                self.signal_badge.config(text="BUY", fg=self.colors['accent_success'])
                self.trading_signal.config(text="BUY", fg=self.colors['accent_success'])
            elif signal == 'SELL':
                self.signal_badge.config(text="SELL", fg=self.colors['accent_danger'])
                self.trading_signal.config(text="SELL", fg=self.colors['accent_danger'])
            else:
                self.signal_badge.config(text="NEUTRAL", fg=self.colors['text_secondary'])
                self.trading_signal.config(text="NEUTRAL", fg=self.colors['text_secondary'])
        status = data.get('status', 'STOPPED')
        status_color = self.colors['accent_success'] if status == 'RUNNING' else self.colors['accent_danger'] if status == 'STOPPED' else self.colors['accent_warning']
        self.bot_status.config(text=status, fg=status_color)
        self.auto_var.set(data.get('auto_trading', False))
        if not hasattr(self, '_last_signal_update') or self._last_signal_update < time.time() - 1:
            entry_price = data.get('current_entry_price')
            self.entry_price_label.config(text=f"{entry_price:.2f}" if entry_price else "—")
            self.entry_type_label.config(text=data.get('current_entry_type', '—'))
            trades_remaining = data.get('trades_remaining', 0)
            min_trades = data.get('min_trades_per_signal', 5)
            self.trades_remaining_label.config(text=f"{trades_remaining}/{min_trades}")
            self.aggressive_label.config(text="ACTIVE" if data.get('aggressive_mode', False) else "INACTIVE")
            self.signal_comment.config(text=data.get('signal_comment', '—'))
        self.sts_var.set(data.get('use_sts', False))
        self.alerts_var.set(data.get('alerts_enabled', True))
        if data.get('symbol'):
            self.symbol_display.config(text=f"Selected: {data['symbol']}")
        reversal_enabled = data.get('reversal_trading_enabled', False)
        if reversal_enabled != self.reversal_mode_enabled:
            self.reversal_mode_enabled = reversal_enabled
            if reversal_enabled:
                self.reversal_button.config(text="🟢 REVERSAL MODE: ON", bg=self.colors['accent_success'])
            else:
                self.reversal_button.config(text="🔴 REVERSAL MODE: OFF", bg=self.colors['accent_danger'])
        last_reversal = data.get('last_reversal_time')
        if last_reversal:
            try:
                rev_time = datetime.fromisoformat(last_reversal)
                self.last_reversal_label.config(text=rev_time.strftime("%H:%M:%S"))
            except:
                pass
        rev_executed = data.get('reversal_trades_executed', 0)
        max_rev = data.get('max_reversal_trades', 5)
        self.reversal_trades_label.config(text=f"{rev_executed}/{max_rev}")
        if 'reversal_min_confidence' in data and hasattr(self, 'confidence_meter'):
            self.confidence_meter.set_value(data['reversal_min_confidence'])

    def update_positions_display(self, positions):
        self.current_positions = positions
        for item in self.positions_tree.get_children():
            self.positions_tree.delete(item)
        if not positions:
            return
        for pos in positions:
            values = (pos['ticket'], pos['symbol'], pos['type'], f"{pos['volume']:.2f}", f"{pos['entry']:.2f}", f"{pos['current']:.2f}", f"${pos['profit']:.2f}", f"{pos['sl']:.2f}" if pos['sl'] else "None", f"{pos['tp']:.2f}" if pos['tp'] else "None", f"${pos['locked_profit']:.2f}" if pos.get('locked_profit') else "—")
            item = self.positions_tree.insert('', 'end', values=values)
            if pos['profit'] > 0:
                self.positions_tree.tag_configure('profit', foreground='#10b981')
                self.positions_tree.item(item, tags=('profit',))
            elif pos['profit'] < 0:
                self.positions_tree.tag_configure('loss', foreground='#ef4444')
                self.positions_tree.item(item, tags=('loss',))

    def update_orders_display(self, orders):
        for item in self.orders_tree.get_children():
            self.orders_tree.delete(item)
        if not orders:
            return
        for order in orders:
            values = (order['ticket'], order['symbol'], order['type'], f"{order['volume']:.2f}", f"{order['price']:.2f}", f"{order['sl']:.2f}" if order['sl'] else "None", f"{order['tp']:.2f}" if order['tp'] else "None", order['expiration'])
            self.orders_tree.insert('', 'end', values=values)

    def update_history_display(self, history):
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        if not history:
            return
        for trade in history[:50]:
            values = (trade.get('ticket', ''), trade.get('symbol', ''), trade.get('type', ''), f"{trade.get('volume', 0):.2f}", f"{trade.get('entry_price', 0):.2f}", f"${trade.get('profit', 0):.2f}", trade.get('entry_time', '')[:16] if trade.get('entry_time') else '')
            item = self.history_tree.insert('', 'end', values=values)
            if trade.get('profit', 0) > 0:
                self.history_tree.tag_configure('profit', foreground='#10b981')
                self.history_tree.item(item, tags=('profit',))
            elif trade.get('profit', 0) < 0:
                self.history_tree.tag_configure('loss', foreground='#ef4444')
                self.history_tree.item(item, tags=('loss',))

    def update_trailing_stats_from_data(self, stats):
        if not stats:
            return
        if 'managed_positions' in self.trailing_stats:
            self.trailing_stats['managed_positions'].config(text=str(stats.get('open_positions_count', 0)))
        if 'trailing_win_rate' in self.trailing_stats:
            self.trailing_stats['trailing_win_rate'].config(text=f"{stats.get('win_rate', 0):.1f}%")
        if 'trailing_profit' in self.trailing_stats:
            perf = stats.get('performance_metrics', {})
            self.trailing_stats['trailing_profit'].config(text=f"${perf.get('total_profit', 0):.2f}")
        if 'trailing_profit_factor' in self.trailing_stats:
            perf = stats.get('performance_metrics', {})
            self.trailing_stats['trailing_profit_factor'].config(text=f"{perf.get('profit_factor', 0):.2f}")
        if hasattr(self, 'trailing_positions_tree') and 'open_positions' in stats:
            for item in self.trailing_positions_tree.get_children():
                self.trailing_positions_tree.delete(item)
            for pos in stats['open_positions']:
                values = (pos.get('ticket', ''), pos.get('symbol', ''), pos.get('type', ''), f"${pos.get('pnl', 0):.2f}", f"${pos.get('total_locked_profit', 0):.2f}", f"${pos.get('at_risk', 0):.2f}", f"{pos.get('trailing_stop', 0):.5f}" if pos.get('trailing_stop') else "None")
                item = self.trailing_positions_tree.insert('', 'end', values=values)
                if pos.get('pnl', 0) > 0:
                    self.trailing_positions_tree.tag_configure('profit', foreground='#10b981')
                    self.trailing_positions_tree.item(item, tags=('profit',))
                elif pos.get('pnl', 0) < 0:
                    self.trailing_positions_tree.tag_configure('loss', foreground='#ef4444')
                    self.trailing_positions_tree.item(item, tags=('loss',))
        self.last_trailing_stats = stats

    def _full_reload_data(self, silent=False):
        if not self.trading_system or not self.trading_system.running:
            return
        def do_reload():
            try:
                # Symbol scanning removed – no longer interferes with typing
                if self.trading_system.config.symbol:
                    self.trading_system.get_symbol_properties()
                self.trading_system._preload_indicators(100)
                if self.trading_system.config.enable_trailing_stop_loss:
                    self.trading_system.sync_existing_positions_with_trailing()
                self.trading_system.update_account_info()
                if self.trading_system.config.enable_trailing_stop_loss:
                    self.trading_system.force_trailing_stats_update()
                self.root.after(0, self._update_ui_from_system)
                if self.current_section == 'reversal':
                    self.root.after(0, self.refresh_reversal_stats)
                elif self.current_section == 'news':
                    self.root.after(0, self.fetch_news)
                if not silent:
                    self.root.after(0, lambda: self.add_notification("🔄 Refresh Complete", "All data reloaded successfully", "success"))
            except Exception as e:
                if not silent:
                    self.root.after(0, lambda: self.add_notification("❌ Refresh Error", str(e), "error"))
                import traceback
                traceback.print_exc()
        threading.Thread(target=do_reload, daemon=True).start()

    def _update_ui_from_system(self):
        if not self.trading_system:
            return
        with self.trading_system.trading_lock:
            dashboard_data = self.trading_system.get_dashboard_data()
            positions = self.trading_system.get_open_positions()
            orders = self.trading_system.get_pending_orders()
            history = self.trading_system.get_recent_trades()
        self.update_dashboard(dashboard_data)
        self.update_positions_display(positions)
        self.update_orders_display(orders)
        self.update_history_display(history)
        if 'trailing_stop_data' in dashboard_data:
            self.update_trailing_stats_from_data(dashboard_data['trailing_stop_data'])
        self.active_positions_count.config(text=f"Active Trades: {len(positions)}")
        self.pending_orders_count.config(text=f"Pending Orders: {len(orders)}")
        if dashboard_data.get('mt5_connected'):
            self.connection_indicator.config(fg=self.colors['accent_success'])
            self.connection_label.config(text="LIVE", fg=self.colors['accent_success'])
        else:
            self.connection_indicator.config(fg=self.colors['accent_warning'])
            self.connection_label.config(text="SIMULATED", fg=self.colors['accent_warning'])
        if 'trailing_stop_data' in dashboard_data and dashboard_data['trailing_stop_data']:
            if hasattr(self, 'market_trades_label'):
                self.market_trades_label.config(text=f"Market: {dashboard_data.get('trades_taken_current_session', 0)}/5")
            if hasattr(self, 'pending_orders_label'):
                self.pending_orders_label.config(text=f"Pending: {dashboard_data.get('pending_orders', 0)}/5")
        if 'reversal_min_confidence' in dashboard_data:
            conf = dashboard_data['reversal_min_confidence']
            if hasattr(self, 'confidence_meter'):
                self.confidence_meter.set_value(conf)
            if hasattr(self, 'reversal_meter'):
                self.reversal_meter.set_value(conf)
        self.current_positions = positions

    def refresh_application(self):
        self.refresh_button.config(state=tk.DISABLED, text="🔄 Refreshing...")
        self.refresh_status.config(text="Refreshing...", fg=self.colors['accent_warning'])
        def on_complete():
            self.refresh_button.config(state=tk.NORMAL, text="🔄 Refresh")
            self.refresh_status.config(text=f"Last: {datetime.now().strftime('%H:%M:%S')}", fg=self.colors['accent_success'])
        self._full_reload_data(silent=False)
        self.root.after(2000, on_complete)

    def perform_full_refresh(self):
        if not self.trading_system or not self.trading_system.running:
            return
        try:
            with self.trading_system.trading_lock:
                dashboard_data = self.trading_system.get_dashboard_data()
                positions = self.trading_system.get_open_positions()
                orders = self.trading_system.get_pending_orders()
                history = self.trading_system.get_recent_trades()
            self.update_dashboard(dashboard_data)
            self.update_positions_display(positions)
            self.update_orders_display(orders)
            self.update_history_display(history)
            if 'trailing_stop_data' in dashboard_data:
                self.update_trailing_stats_from_data(dashboard_data['trailing_stop_data'])
            self.active_positions_count.config(text=f"Active Trades: {len(positions)}")
            self.pending_orders_count.config(text=f"Pending Orders: {len(orders)}")
            if dashboard_data.get('mt5_connected'):
                self.connection_indicator.config(fg=self.colors['accent_success'])
                self.connection_label.config(text="LIVE", fg=self.colors['accent_success'])
            else:
                self.connection_indicator.config(fg=self.colors['accent_warning'])
                self.connection_label.config(text="SIMULATED", fg=self.colors['accent_warning'])
            if 'trailing_stop_data' in dashboard_data and dashboard_data['trailing_stop_data']:
                if hasattr(self, 'market_trades_label'):
                    self.market_trades_label.config(text=f"Market: {dashboard_data.get('trades_taken_current_session', 0)}/5")
                if hasattr(self, 'pending_orders_label'):
                    self.pending_orders_label.config(text=f"Pending: {dashboard_data.get('pending_orders', 0)}/5")
            if 'reversal_min_confidence' in dashboard_data:
                conf = dashboard_data['reversal_min_confidence']
                if hasattr(self, 'confidence_meter'):
                    self.confidence_meter.set_value(conf)
                if hasattr(self, 'reversal_meter'):
                    self.reversal_meter.set_value(conf)
            self.current_positions = positions
        except Exception as e:
            print(f"Full refresh error: {e}")
            import traceback
            traceback.print_exc()

    def logout(self):
        if messagebox.askyesno("Logout", "Are you sure you want to logout?"):
            self.is_logged_in = False
            self.stop_trading_system()
            self.app_frame.pack_forget()
            if hasattr(self, 'login_screen') and self.login_screen:
                self.login_screen.destroy()
                self.login_screen = None
            self.current_user = None
            self.show_animated_login_screen()

    def stop_trading_system(self):
        self.trading_running = False
        if self.trading_system:
            self.trading_system.running = False

    def save_config(self):
        try:
            config_dict = asdict(self.config)
            config_dict.pop('reversal_stop_loss_pips', None)
            config_dict.pop('reversal_take_profit_pips', None)
            with open("trading_config.json", "w") as f:
                json.dump(config_dict, f, indent=4)
        except Exception as e:
            print(f"Error saving config: {e}")

    def on_close(self):
        if messagebox.askokcancel("Quit", "Do you want to quit?"):
            try:
                mt5.shutdown()
            except:
                pass
            self.stop_trading_system()
            self.root.quit()
            self.root.destroy()
