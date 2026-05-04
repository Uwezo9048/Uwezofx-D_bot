# modules/gui/widgets.py
import tkinter as tk
from tkinter import ttk
import threading
import random
import queue
import time
from PIL import Image, ImageTk, ImageDraw
from datetime import datetime

# Helper functions (darken_color, lighten_color) are already defined elsewhere,
# but we'll import them from utils.helpers.
from modules.utils.helpers import darken_color, lighten_color

class ModernUI:
    """Helper class for modern UI elements and effects"""
    COLORS = {
        'bg_dark': '#0A0F1E',
        'bg_card': '#151F32',
        'bg_sidebar': '#1A253C',
        'text_primary': '#FFFFFF',
        'text_secondary': '#8A99B8',
        'text_muted': '#5D6B89',
        'accent_primary': '#4F7DF3',
        'accent_success': '#2ECC71',
        'accent_danger': '#E74C3C',
        'accent_warning': '#F39C12',
        'accent_info': '#3498DB',
        'accent_purple': '#9B59B6',
        'border': '#2A3650',
        'hover': '#2E3D5E',
        'gradient_start': '#1A253C',
        'gradient_end': '#0F1A2C',
    }
    
    @staticmethod
    def create_gradient(width, height, color1, color2, orientation='vertical'):
        image = Image.new('RGB', (width, height), color1)
        draw = ImageDraw.Draw(image)
        
        if orientation == 'vertical':
            for i in range(height):
                ratio = i / height
                r = int(int(color1[1:3], 16) * (1 - ratio) + int(color2[1:3], 16) * ratio)
                g = int(int(color1[3:5], 16) * (1 - ratio) + int(color2[3:5], 16) * ratio)
                b = int(int(color1[5:7], 16) * (1 - ratio) + int(color2[5:7], 16) * ratio)
                draw.line([(0, i), (width, i)], fill=(r, g, b))
        else:
            for i in range(width):
                ratio = i / width
                r = int(int(color1[1:3], 16) * (1 - ratio) + int(color2[1:3], 16) * ratio)
                g = int(int(color1[3:5], 16) * (1 - ratio) + int(color2[3:5], 16) * ratio)
                b = int(int(color1[5:7], 16) * (1 - ratio) + int(color2[5:7], 16) * ratio)
                draw.line([(i, 0), (i, height)], fill=(r, g, b))
        
        return ImageTk.PhotoImage(image)
    
    @staticmethod
    def create_rounded_rectangle(width, height, radius, color, outline=None):
        image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            [(0, 0), (width-1, height-1)],
            radius=radius,
            fill=color,
            outline=outline
        )
        return ImageTk.PhotoImage(image)
    
    @staticmethod
    def create_circular_image(image_path, size):
        try:
            img = Image.open(image_path)
            img = img.resize((size, size), Image.Resampling.LANCZOS)
            mask = Image.new('L', (size, size), 0)
            draw = ImageDraw.Draw(mask)
            draw.ellipse((0, 0, size, size), fill=255)
            result = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            result.paste(img, (0, 0), mask)
            return ImageTk.PhotoImage(result)
        except:
            return None
    
    @staticmethod
    def add_glow_effect(widget, color='#4F7DF3', radius=10):
        def on_enter(e):
            widget.config(highlightbackground=color, highlightthickness=2)
        def on_leave(e):
            widget.config(highlightbackground=ModernUI.COLORS['border'], highlightthickness=1)
        widget.bind('<Enter>', on_enter)
        widget.bind('<Leave>', on_leave)
        widget.config(highlightbackground=ModernUI.COLORS['border'], highlightthickness=1)
        return widget
    
    @staticmethod
    def create_animated_button(parent, text, command, style='primary', width=None):
        colors = {
            'primary': ModernUI.COLORS['accent_primary'],
            'success': ModernUI.COLORS['accent_success'],
            'danger': ModernUI.COLORS['accent_danger'],
            'warning': ModernUI.COLORS['accent_warning'],
            'info': ModernUI.COLORS['accent_info'],
        }
        btn = tk.Button(
            parent,
            text=text,
            bg=colors.get(style, ModernUI.COLORS['accent_primary']),
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            bd=0,
            padx=20,
            pady=10,
            cursor='hand2',
            command=command
        )
        if width:
            btn.config(width=width)
        def on_enter(e):
            btn.config(bg=darken_color(colors.get(style, ModernUI.COLORS['accent_primary'])))
        def on_leave(e):
            btn.config(bg=colors.get(style, ModernUI.COLORS['accent_primary']))
        btn.bind('<Enter>', on_enter)
        btn.bind('<Leave>', on_leave)
        return btn

class LoadingAnimation:
    def __init__(self, parent, message="Loading..."):
        self.parent = parent
        self.overlay = None
        self.animation_frame = None
        self.message = message
        self.animation_id = None
        self.loading = False
        self.progress_value = 0
        self.progress_stop = False
        self._lock = threading.Lock()
    
    def show(self):
        with self._lock:
            if self.loading:
                return
            self.loading = True
            self.progress_stop = False
            self.overlay = tk.Toplevel(self.parent)
            self.overlay.overrideredirect(True)
            self.overlay.attributes('-alpha', 0.9)
            self.overlay.configure(bg='#0A0F1E')
            x = self.parent.winfo_x() + (self.parent.winfo_width() // 2) - 150
            y = self.parent.winfo_y() + (self.parent.winfo_height() // 2) - 100
            self.overlay.geometry(f"300x200+{x}+{y}")
            self.animation_frame = tk.Frame(self.overlay, bg='#0A0F1E')
            self.animation_frame.pack(expand=True, fill=tk.BOTH)
            title = tk.Label(self.animation_frame, text="UWEZO-FX", 
                             font=('Montserrat', 16, 'bold'),
                             fg='#4F7DF3', bg='#0A0F1E')
            title.pack(pady=10)
            msg_label = tk.Label(self.animation_frame, text=self.message,
                                 font=('Segoe UI', 11),
                                 fg='#FFFFFF', bg='#0A0F1E')
            msg_label.pack(pady=5)
            self.dots_label = tk.Label(self.animation_frame, text="● ● ●",
                                       font=('Segoe UI', 20),
                                       fg='#4F7DF3', bg='#0A0F1E')
            self.dots_label.pack(pady=10)
            self.progress = AnimatedProgressBar(self.animation_frame, width=200, height=4)
            self.progress.pack(pady=10)
            self.animate_dots()
            self.animate_progress()
            self.overlay.grab_set()
            self.overlay.update()
    
    def animate_dots(self, count=0):
        if not self.loading or self.progress_stop:
            return
        dots = ["● ● ○", "● ● ●", "○ ● ●", "● ○ ●"]
        self.dots_label.config(text=dots[count % len(dots)])
        self.animation_id = self.overlay.after(300, lambda: self.animate_dots(count + 1))
    
    def animate_progress(self, value=0):
        if not self.loading or self.progress_stop:
            return
        if value <= 100:
            self.progress.set_value(value)
            self.progress_value = value
            self.animation_id = self.overlay.after(50, lambda: self.animate_progress(value + 2))
        else:
            self.progress_value = 0
    
    def hide(self):
        with self._lock:
            self.progress_stop = True
            self.loading = False
            if self.animation_id and self.overlay:
                self.overlay.after_cancel(self.animation_id)
            if self.overlay:
                self.overlay.destroy()
                self.overlay = None

class ButtonAnimation:
    @staticmethod
    def animate_click(button, command, *args):
        def animate():
            original_bg = button.cget('bg') if button.winfo_exists() else None
            original_fg = button.cget('fg') if button.winfo_exists() else None
            try:
                if button.winfo_exists():
                    button.config(bg='#FFFFFF', fg='#4F7DF3')
                    button.update()
            except:
                pass
            def restore():
                try:
                    if button.winfo_exists() and original_bg:
                        button.config(bg=original_bg, fg=original_fg)
                except:
                    pass
                if args:
                    command(*args)
                else:
                    command()
            button.after(100, restore)
        return animate

class HelpCenterBot:
    def __init__(self, parent, colors):
        self.parent = parent
        self.colors = colors
        self.window = None
        self.chat_history = []
        self.responses = {
            "how to trade": "To trade, first select a symbol from Settings, then use the BUY/SELL buttons in Dashboard or Trading Signal section.",
            "what is reversal": "Reversal trading automatically executes trades when signals change from BUY to SELL or vice versa, with 11 confirmation indicators.",
            "stop loss": "Stop loss protects your position by automatically closing if price moves against you. Set in pips in Settings.",
            "take profit": "Take profit closes your position at a predetermined profit level. Set in pips in Settings.",
            "trailing stop": "Trailing stop moves your stop loss as price moves in your favor, locking in profits.",
            "mt5 connection": "Connect to MT5 via Settings > Broker Connection. You need your broker's server, login, and password.",
            "help": "I can help with: trading, reversal, stop loss, take profit, trailing stop, MT5 connection, symbols, positions.",
            "symbol": "Select a symbol from the dropdown in Settings or use the search function.",
            "position": "Your open positions are shown in the Positions section. Double-click to close.",
            "news": "Economic news and sentiment are available in the News section.",
        }
    
    def open(self):
        from tkinter import messagebox
        try:
            if self.window and self.window.winfo_exists():
                self.window.lift()
                return
            self.window = tk.Toplevel(self.parent)
            self.window.title("Help Center")
            self.window.geometry("500x600")
            self.window.configure(bg=self.colors['bg_dark'])
            self.window.transient(self.parent)
            self.window.protocol("WM_DELETE_WINDOW", self.on_close)
            self.window.update_idletasks()
            x = self.parent.winfo_x() + (self.parent.winfo_width() // 2) - 250
            y = self.parent.winfo_y() + (self.parent.winfo_height() // 2) - 300
            self.window.geometry(f"+{x}+{y}")
            header = tk.Frame(self.window, bg=self.colors['accent_primary'], height=80)
            header.pack(fill=tk.X)
            header.pack_propagate(False)
            tk.Label(header, text="🤖 Help Center", 
                     font=('Montserrat', 18, 'bold'),
                     fg='white', bg=self.colors['accent_primary']).pack(pady=20)
            chat_frame = tk.Frame(self.window, bg=self.colors['bg_dark'])
            chat_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            self.chat_display = tk.Text(chat_frame, bg=self.colors['bg_card'],
                                        fg=self.colors['text_primary'],
                                        font=('Segoe UI', 11), wrap=tk.WORD,
                                        height=20, state=tk.DISABLED)
            self.chat_display.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar = tk.Scrollbar(chat_frame, command=self.chat_display.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            self.chat_display.config(yscrollcommand=scrollbar.set)
            input_frame = tk.Frame(self.window, bg=self.colors['bg_card'])
            input_frame.pack(fill=tk.X, padx=10, pady=10)
            self.input_entry = tk.Entry(input_frame, bg=self.colors['bg_sidebar'],
                                        fg=self.colors['text_primary'],
                                        font=('Segoe UI', 11), bd=0)
            self.input_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5, pady=5)
            self.input_entry.bind('<Return>', lambda e: self.send_message())
            send_btn = ModernUI.create_animated_button(
                input_frame, "Send", self.send_message, 'primary'
            )
            send_btn.pack(side=tk.RIGHT, padx=5)
            btn_frame = tk.Frame(self.window, bg=self.colors['bg_dark'])
            btn_frame.pack(fill=tk.X, padx=10, pady=5)
            telegram_btn = ModernUI.create_animated_button(
                btn_frame, "💬 Telegram Support", self.connect_telegram, 'info'
            )
            telegram_btn.pack(side=tk.LEFT, padx=5, pady=5)
            email_btn = ModernUI.create_animated_button(
                btn_frame, "✉️ Email Support", self.open_email, 'info'
            )
            email_btn.pack(side=tk.LEFT, padx=5, pady=5)
            faq_btn = ModernUI.create_animated_button(
                btn_frame, "📚 FAQ", self.show_faq, 'info'
            )
            faq_btn.pack(side=tk.LEFT, padx=5, pady=5)
            self.add_bot_message("👋 Hello! I'm your UWEZO-FX assistant. How can I help you today?\n\n"
                                 "You can ask me about:\n"
                                 "• How to trade\n"
                                 "• Reversal trading\n"
                                 "• Stop loss / Take profit\n"
                                 "• Trailing stop\n"
                                 "• MT5 connection\n"
                                 "• Symbols and positions\n\n"
                                 "Need live help? Click Telegram Support or Email Support!")
        except Exception as e:
            print(f"Error opening help center: {e}")
            messagebox.showerror("Error", "Could not open Help Center")
    
    def on_close(self):
        if self.window:
            self.window.destroy()
            self.window = None
    
    def send_message(self):
        message = self.input_entry.get().strip()
        if not message:
            return
        self.add_user_message(message)
        self.input_entry.delete(0, tk.END)
        response = self.get_response(message.lower())
        self.add_bot_message(response)
    
    def get_response(self, message):
        for key, response in self.responses.items():
            if key in message:
                return response
        return ("I'm not sure about that. Try asking about:\n"
                "• how to trade\n"
                "• reversal trading\n"
                "• stop loss\n"
                "• take profit\n"
                "• trailing stop\n"
                "• MT5 connection\n\n"
                "Or click Telegram Support for live help!")
    
    def add_user_message(self, message):
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"You: {message}\n\n", 'user')
        self.chat_display.tag_config('user', foreground=self.colors['accent_success'])
        self.chat_display.see(tk.END)
        self.chat_display.config(state=tk.DISABLED)
    
    def add_bot_message(self, message):
        self.chat_display.config(state=tk.NORMAL)
        self.chat_display.insert(tk.END, f"🤖 Bot: {message}\n\n", 'bot')
        self.chat_display.tag_config('bot', foreground=self.colors['accent_primary'])
        self.chat_display.see(tk.END)
        self.chat_display.config(state=tk.DISABLED)
    
    def connect_telegram(self):
        import webbrowser
        webbrowser.open("https://t.me/UwezoFXSupport")
        self.add_bot_message("Opening Telegram support channel. A live agent will assist you shortly!")
    
    def open_email(self):
        import webbrowser
        webbrowser.open("mailto:support@uwezofx.com?subject=UWEZO-FX%20Support%20Request")
        self.add_bot_message("Opening email client. Please describe your issue and we'll respond within 24 hours.")
    
    def show_faq(self):
        faq_window = tk.Toplevel(self.window)
        faq_window.title("FAQ - Frequently Asked Questions")
        faq_window.geometry("500x400")
        faq_window.configure(bg=self.colors['bg_dark'])
        faq_window.update_idletasks()
        x = self.window.winfo_x() + (self.window.winfo_width() // 2) - 250
        y = self.window.winfo_y() + (self.window.winfo_height() // 2) - 200
        faq_window.geometry(f"+{x}+{y}")
        main_frame = tk.Frame(faq_window, bg=self.colors['bg_dark'])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        text = tk.Text(main_frame, bg=self.colors['bg_card'],
                       fg=self.colors['text_primary'],
                       font=('Segoe UI', 11), wrap=tk.WORD)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        text.config(yscrollcommand=scrollbar.set)
        faq_content = """
        📚 FREQUENTLY ASKED QUESTIONS

        1. How do I start trading?
        • First, connect to MT5 in Settings > Broker Connection
        • Select a symbol from the dropdown
        • Use BUY/SELL buttons in Dashboard or Trading Signal section

        2. What is Reversal Trading?
        • Automatically executes trades when signals reverse
        • Uses 11 confirmation indicators before trading
        • Can be enabled/disabled in Settings

        3. How does Trailing Stop work?
        • Moves stop loss as price moves in your favor
        • Locks in profits progressively ($3 for every $4 profit)
        • Configurable in Settings > Trailing Stop

        4. What are the maximum trades?
        • Maximum 5 trades per session
        • Maximum 5 pending orders per session
        • Can reset counters using Reset buttons

        5. How do I get support?
        • Click Telegram Support for live chat
        • Use Email Support for detailed inquiries
        • Ask the bot for quick help

        6. What are the 10 reversal confirmations?
        1. Price Retest with candle pattern
        2. Volatility within optimal range
        3. Volume spike confirmation
        4. Momentum filter
        5. Support/Resistance level
        6. News filter (avoid high impact)
        7. Time filter (trading hours)
        8. Higher timeframe alignment
        9. Candlestick pattern recognition
        10. Fibonacci level retracement
        """
        text.insert(tk.END, faq_content)
        text.config(state=tk.DISABLED)

class AboutSection:
    def __init__(self, parent, colors):
        self.parent = parent
        self.colors = colors
        self.window = None
    
    def open(self):
        if self.window and self.window.winfo_exists():
            self.window.lift()
            return
        self.window = tk.Toplevel(self.parent)
        self.window.title("About UWEZO-FX")
        self.window.geometry("600x500")
        self.window.configure(bg=self.colors['bg_dark'])
        self.window.transient(self.parent)
        self.window.update_idletasks()
        x = self.parent.winfo_x() + (self.parent.winfo_width() // 2) - 300
        y = self.parent.winfo_y() + (self.parent.winfo_height() // 2) - 250
        self.window.geometry(f"+{x}+{y}")
        main_frame = tk.Frame(self.window, bg=self.colors['bg_dark'])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        content = tk.Frame(main_frame, bg=self.colors['bg_dark'])
        content.pack(fill=tk.BOTH, expand=True)
        logo = tk.Label(content, text="UWEZO-FX",
                        font=('Montserrat', 24, 'bold'),
                        fg=self.colors['accent_primary'],
                        bg=self.colors['bg_dark'])
        logo.pack(pady=10)
        subtitle = tk.Label(content, text="Enhanced Reversal Trading System",
                            font=('Segoe UI', 12),
                            fg=self.colors['text_secondary'],
                            bg=self.colors['bg_dark'])
        subtitle.pack()
        sep = tk.Frame(content, bg=self.colors['border'], height=2)
        sep.pack(fill=tk.X, pady=20)
        text_frame = tk.Frame(content, bg=self.colors['bg_dark'])
        text_frame.pack(fill=tk.BOTH, expand=True)
        description = tk.Text(text_frame, bg=self.colors['bg_card'],
                              fg=self.colors['text_primary'],
                              font=('Segoe UI', 11), wrap=tk.WORD,
                              height=15, width=50)
        description.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=description.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        description.config(yscrollcommand=scrollbar.set)
        about_text = """
        📊 UWEZO-FX TRADING SYSTEM

        Version: 2.0 - Enhanced Reversal Edition

        A professional trading system designed for MetaTrader 5 with advanced reversal detection and automated trade management.

        🎯 KEY FEATURES:

        • 11 confirmation indicators for Reversal Trading
        • Smart Money Structure (SMS) & ICT Concepts
        • Automatic Trade Execution with Trailing Stop
        • Progressive Profit Locking ($3 per $4 profit)
        • Myfxbook News Integration & Sentiment Analysis
        • Modern Glass-morphism UI with Animations
        • Maximum 5 Trades & 5 Orders per Session

        ⚡ REVERSAL TRADING CONFIRMATIONS:

        1. Price Retest with Candle Pattern
        2. Volatility Filter (ATR-based)
        3. Volume Spike Confirmation
        4. Momentum Filter
        5. Support/Resistance Level
        6. News Filter (High Impact Avoidance)
        7. Time Filter (Trading Hours)
        8. Higher Timeframe Alignment
        9. Candlestick Pattern Recognition
        10. Fibonacci Level Retracement

        🔧 TECHNICAL DETAILS:

        • Python-based with MetaTrader 5 integration
        • Supabase user authentication
        • Brevo email notifications
        • Telegram & Email support integration
        • Encrypted credential storage

        © 2026 UWEZO-FX Trading System
        All rights reserved.
        """
        description.insert(tk.END, about_text)
        description.config(state=tk.DISABLED)
        close_btn = ModernUI.create_animated_button(
            content, "Close", self.window.destroy, 'primary'
        )
        close_btn.pack(pady=10)

class AnimatedProgressBar(tk.Canvas):
    def __init__(self, parent, width=200, height=8, bg_color='#2A3650', 
                 fg_color='#4F7DF3', value=0, **kwargs):
        super().__init__(parent, width=width, height=height, bg=bg_color, 
                         highlightthickness=0, **kwargs)
        self.width = width
        self.height = height
        self.fg_color = fg_color
        self.value = value
        self.target_value = value
        self.animation_id = None
        self.animating = False
        self._destroyed = False
        self.progress = self.create_rectangle(0, 0, 0, height, fill=fg_color, width=0)
        self.update_progress(value)
    
    def set_value(self, value, animate=True):
        self.target_value = max(0, min(100, value))
        if animate:
            if self.animation_id:
                self.after_cancel(self.animation_id)
            self.animating = True
            self.animate_progress()
        else:
            self.update_progress(self.target_value)
    
    def update_progress(self, value):
        width = (value / 100) * self.width
        self.coords(self.progress, 0, 0, width, self.height)
    
    def animate_progress(self):
        if self._destroyed or not self.animating:
            return
        current = self.value
        target = self.target_value
        if abs(current - target) < 0.5:
            self.value = target
            self.update_progress(target)
            self.animating = False
            return
        step = (target - current) * 0.1
        self.value = current + step
        self.update_progress(self.value)
        self.animation_id = self.after(50, self.animate_progress)
    
    def destroy(self):
        self._destroyed = True
        self.animating = False
        if self.animation_id:
            self.after_cancel(self.animation_id)
        super().destroy()

class FloatingActionButton(tk.Canvas):
    def __init__(self, parent, text, command, size=60, color='#4F7DF3', **kwargs):
        super().__init__(parent, width=size, height=size, highlightthickness=0, **kwargs)
        self.size = size
        self.color = color
        self.command = command
        self.animation_id = None
        self.create_oval(2, 2, size-2, size-2, fill=color, outline='')
        self.create_text(size//2, size//2, text=text, fill='white', 
                         font=('Segoe UI', int(size*0.4), 'bold'))
        self.bind('<Enter>', self.on_enter)
        self.bind('<Leave>', self.on_leave)
        self.bind('<Button-1>', self.on_click)
    
    def on_enter(self, event):
        self.scale('all', self.size//2, self.size//2, 1.1, 1.1)
    
    def on_leave(self, event):
        self.scale('all', self.size//2, self.size//2, 1/1.1, 1/1.1)
    
    def on_click(self, event):
        if self.animation_id:
            return
        self.flash_animation()
        self.command()
    
    def flash_animation(self):
        self.itemconfig(1, fill=lighten_color(self.color))
        self.after(100, self.reset_color)
    
    def reset_color(self):
        self.itemconfig(1, fill=self.color)
        self.animation_id = None

class ModernCard(tk.Frame):
    def __init__(self, parent, title=None, width=None, height=None, **kwargs):
        super().__init__(parent, bg=ModernUI.COLORS['bg_card'], **kwargs)
        if width:
            self.config(width=width)
        if height:
            self.config(height=height)
        self.config(highlightbackground=ModernUI.COLORS['border'], highlightthickness=1)
        if title:
            title_frame = tk.Frame(self, bg=ModernUI.COLORS['bg_card'])
            title_frame.pack(fill='x', padx=15, pady=(15, 5))
            tk.Label(title_frame, text=title, font=('Segoe UI', 12, 'bold'),
                     fg=ModernUI.COLORS['text_primary'], 
                     bg=ModernUI.COLORS['bg_card']).pack(side='left')
        self.content = tk.Frame(self, bg=ModernUI.COLORS['bg_card'])
        self.content.pack(fill='both', expand=True, padx=15, pady=15)
        self.bind('<Enter>', self.on_enter)
        self.bind('<Leave>', self.on_leave)
    
    def on_enter(self, event):
        self.config(highlightbackground=ModernUI.COLORS['accent_primary'])
    
    def on_leave(self, event):
        self.config(highlightbackground=ModernUI.COLORS['border'])

class MiniChart(tk.Canvas):
    def __init__(self, parent, width=200, height=60, **kwargs):
        super().__init__(parent, width=width, height=height, 
                         bg=ModernUI.COLORS['bg_card'], 
                         highlightthickness=0, **kwargs)
        self.width = width
        self.height = height
        self.points = []
        self.update_animation_id = None
        self._destroyed = False
        self.draw_grid()
        self.animate()
    
    def draw_grid(self):
        for i in range(1, 4):
            y = i * self.height // 4
            self.create_line(0, y, self.width, y, fill=ModernUI.COLORS['border'], width=1)
        for i in range(1, 5):
            x = i * self.width // 5
            self.create_line(x, 0, x, self.height, fill=ModernUI.COLORS['border'], width=1)
    
    def update_data(self, price):
        try:
            if price is None or not isinstance(price, (int, float)):
                return
            self.points.append(price)
            if len(self.points) > 50:
                self.points.pop(0)
            self.delete('all')
            self.draw_grid()
            self.draw_chart()
        except Exception as e:
            print(f"Chart update error: {e}")
            self.points = []
    
    def draw_chart(self):
        if len(self.points) < 2:
            return
        min_price = min(self.points)
        max_price = max(self.points)
        price_range = max_price - min_price or 1
        points_coords = []
        for i, price in enumerate(self.points):
            x = (i / (len(self.points) - 1)) * self.width
            y = self.height - ((price - min_price) / price_range) * (self.height - 10) - 5
            points_coords.extend([x, y])
        self.create_line(points_coords, fill=ModernUI.COLORS['accent_primary'], width=2, smooth=True)
        if len(points_coords) >= 4:
            fill_coords = [0, self.height] + points_coords + [self.width, self.height]
            self.create_polygon(fill_coords, fill=ModernUI.COLORS['accent_primary'],
                                stipple='gray50', outline='')
    
    def animate(self):
        if self._destroyed:
            return
        if self.points:
            last = self.points[-1]
            change = random.uniform(-0.5, 0.5)
            new_price = last + change
        else:
            new_price = 100 + random.uniform(-1, 1)
        self.update_data(new_price)
        self.update_animation_id = self.after(1000, self.animate)
    
    def destroy(self):
        self._destroyed = True
        if self.update_animation_id:
            self.after_cancel(self.update_animation_id)
        super().destroy()

class ScrollableFrame(tk.Frame):
    def __init__(self, container, *args, **kwargs):
        super().__init__(container, *args, **kwargs)
        self.canvas = tk.Canvas(self, bg=ModernUI.COLORS['bg_dark'], highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.scrollable_frame = tk.Frame(self.canvas, bg=ModernUI.COLORS['bg_dark'])
        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )
        self.canvas_window = self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.canvas.bind('<Configure>', self._on_canvas_configure)
    
    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)
    
    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")