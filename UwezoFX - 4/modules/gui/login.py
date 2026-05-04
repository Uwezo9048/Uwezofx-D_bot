# modules/gui/login.py
import json
import tkinter as tk
import threading
import time
from datetime import datetime
from .widgets import ModernUI, AnimatedProgressBar, LoadingAnimation

class LoadingStep:
    def __init__(self, name: str, weight: int = 1):
        self.name = name
        self.weight = weight
        self.completed = False
        self.current = False
        self.message = ""
        self.start_time = None
        self.end_time = None

class ModernLoginScreen:
    def __init__(self, parent, colors, on_login_callback, on_create_account, on_password_reset):
        self.parent = parent
        self.colors = colors
        self.on_login_callback = on_login_callback
        self.on_create_account = on_create_account
        self.on_password_reset = on_password_reset
        
        self.loading_steps = [
            LoadingStep("Initializing MetaTrader 5 API", weight=15),
            LoadingStep("Loading Trading Configuration", weight=10),
            LoadingStep("Connecting to Supabase Database", weight=15),
            LoadingStep("Initializing News Manager", weight=10),
            LoadingStep("Loading Indicator Systems", weight=15),
            LoadingStep("Preloading Market Data", weight=10),
            LoadingStep("Compiling ICT/SMS Indicators", weight=15),
            LoadingStep("Preparing Reversal Engine", weight=10),
            LoadingStep("Finalizing System", weight=5),
        ]
        
        self.current_step = 0
        self.total_weight = sum(step.weight for step in self.loading_steps)
        self.current_progress = 0
        
        self.animation_id = None
        self.heartbeat_scale = 1.0
        self.heartbeat_direction = 1
        
        self.setup_ui()
        self.start_loading_animation()

    def on_window_resize(self, event):
        if event.widget == self.parent and hasattr(self, 'login_card') and self.login_card.winfo_exists():
            self.login_card.place(relx=0.5, rely=0.5, anchor='center', width=500, height=600)

    def setup_ui(self):
        self.container = tk.Frame(self.parent, bg=self.colors['bg_dark'])
        self.container.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.login_card = tk.Frame(
            self.container, 
            bg=self.colors['bg_card'],
            highlightbackground=self.colors['accent_primary'],
            highlightthickness=2
        )
        self.login_card.place(relx=0.5, rely=0.5, anchor='center', width=500, height=600)
        self.parent.bind('<Configure>', self.on_window_resize)
        
        self.logo_frame = tk.Frame(self.login_card, bg=self.colors['bg_card'])
        self.logo_frame.pack(pady=(40, 20))
        self.logo_label = tk.Label(
            self.logo_frame,
            text="UWEZO-FX",
            font=('Montserrat', 48, 'bold'),
            fg=self.colors['accent_primary'],
            bg=self.colors['bg_card']
        )
        self.logo_label.pack()
        self.subtitle_label = tk.Label(
            self.logo_frame,
            text="Professional Trading System",
            font=('Segoe UI', 12),
            fg=self.colors['text_secondary'],
            bg=self.colors['bg_card']
        )
        self.subtitle_label.pack(pady=(5, 0))
        
        self.loading_frame = tk.Frame(self.login_card, bg=self.colors['bg_card'])
        self.loading_frame.pack(fill=tk.X, padx=30, pady=20)
        self.progress_bar = AnimatedProgressBar(
            self.loading_frame,
            width=440,
            height=6,
            fg_color=self.colors['accent_primary'],
            bg_color=self.colors['border']
        )
        self.progress_bar.pack(pady=(10, 20))
        self.status_text = tk.Label(
            self.loading_frame,
            text="Initializing system...",
            font=('Segoe UI', 10),
            fg=self.colors['text_secondary'],
            bg=self.colors['bg_card']
        )
        self.status_text.pack(pady=(0, 10))
        
        self.steps_frame = tk.Frame(self.loading_frame, bg=self.colors['bg_card'])
        self.steps_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        self.step_labels = []
        for i, step in enumerate(self.loading_steps):
            step_frame = tk.Frame(self.steps_frame, bg=self.colors['bg_card'])
            step_frame.pack(fill=tk.X, pady=3)
            status_icon = tk.Label(
                step_frame,
                text="○",
                font=('Segoe UI', 12),
                fg=self.colors['text_muted'],
                bg=self.colors['bg_card']
            )
            status_icon.pack(side=tk.LEFT, padx=(0, 10))
            name_label = tk.Label(
                step_frame,
                text=step.name,
                font=('Segoe UI', 10),
                fg=self.colors['text_secondary'],
                bg=self.colors['bg_card']
            )
            name_label.pack(side=tk.LEFT)
            self.step_labels.append({
                'frame': step_frame,
                'icon': status_icon,
                'name': name_label,
                'step': step
            })
        
        self.login_form_frame = tk.Frame(self.login_card, bg=self.colors['bg_card'])
        username_frame = tk.Frame(self.login_form_frame, bg=self.colors['bg_card'])
        username_frame.pack(fill=tk.X, pady=10)
        tk.Label(
            username_frame,
            text="Username",
            font=('Segoe UI', 11),
            fg=self.colors['text_secondary'],
            bg=self.colors['bg_card']
        ).pack(anchor='w')
        self.username_entry = tk.Entry(
            username_frame,
            width=40,
            bg=self.colors['bg_sidebar'],
            fg=self.colors['text_primary'],
            insertbackground=self.colors['text_primary'],
            bd=0,
            font=('Segoe UI', 11)
        )
        self.username_entry.pack(fill=tk.X, pady=(5, 0))
        ModernUI.add_glow_effect(self.username_entry, self.colors['accent_primary'])
        
        code_frame = tk.Frame(self.login_form_frame, bg=self.colors['bg_card'])
        code_frame.pack(fill=tk.X, pady=10)
        tk.Label(
            code_frame,
            text="Login Code",
            font=('Segoe UI', 11),
            fg=self.colors['text_secondary'],
            bg=self.colors['bg_card']
        ).pack(anchor='w')
        self.code_entry = tk.Entry(
            code_frame,
            width=40,
            show="*",
            bg=self.colors['bg_sidebar'],
            fg=self.colors['text_primary'],
            insertbackground=self.colors['text_primary'],
            bd=0,
            font=('Segoe UI', 11)
        )
        self.code_entry.pack(fill=tk.X, pady=(5, 0))
        ModernUI.add_glow_effect(self.code_entry, self.colors['accent_primary'])
        
        info_label = tk.Label(
            self.login_form_frame,
            text="Login code is provided by admin after account approval",
            font=('Segoe UI', 9),
            fg=self.colors['text_muted'],
            bg=self.colors['bg_card']
        )
        info_label.pack(pady=(10, 5))
        
        button_frame = tk.Frame(self.login_form_frame, bg=self.colors['bg_card'])
        button_frame.pack(pady=20)
        self.login_button = ModernUI.create_animated_button(
            button_frame,
            "Login",
            self.handle_login,
            'primary'
        )
        self.login_button.pack(side=tk.LEFT, padx=5)
        self.create_button = ModernUI.create_animated_button(
            button_frame,
            "Create Account",
            self.on_create_account,
            'success'
        )
        self.create_button.pack(side=tk.LEFT, padx=5)
        
        forgot_link = tk.Label(
            self.login_form_frame,
            text="Forgot Password?",
            fg=self.colors['accent_info'],
            bg=self.colors['bg_card'],
            cursor='hand2',
            font=('Segoe UI', 9, 'underline')
        )
        forgot_link.pack(pady=(5, 0))
        forgot_link.bind('<Button-1>', lambda e: self.on_password_reset())
        
        self.message_label = tk.Label(
            self.login_form_frame,
            text="",
            font=('Segoe UI', 10),
            fg=self.colors['accent_danger'],
            bg=self.colors['bg_card']
        )
        self.message_label.pack(pady=10)
        
        self.start_heartbeat_animation()
    
    def start_heartbeat_animation(self):
        def animate_heartbeat():
            if not hasattr(self, 'logo_label') or not self.logo_label.winfo_exists():
                return
            if self.heartbeat_direction == 1:
                self.heartbeat_scale += 0.02
                if self.heartbeat_scale >= 1.1:
                    self.heartbeat_direction = -1
            else:
                self.heartbeat_scale -= 0.02
                if self.heartbeat_scale <= 0.95:
                    self.heartbeat_direction = 1
            try:
                new_size = int(48 * self.heartbeat_scale)
                self.logo_label.config(font=('Montserrat', new_size, 'bold'))
            except:
                pass
            self.animation_id = self.parent.after(30, animate_heartbeat)
        self.animation_id = self.parent.after(30, animate_heartbeat)
    
    def start_loading_animation(self):
        def load_step(step_index):
            if step_index >= len(self.loading_steps):
                self.loading_complete()
                return
            step = self.loading_steps[step_index]
            step.current = True
            step.start_time = datetime.now()
            self.update_step_display(step_index, "loading")
            self.status_text.config(text=f"🔄 {step.name}...")
            def do_work():
                try:
                    self.perform_loading_step(step_index)
                    step.completed = True
                    step.end_time = datetime.now()
                    step.current = False
                    self.update_progress()
                    self.update_step_display(step_index, "completed")
                    duration = (step.end_time - step.start_time).total_seconds()
                    self.status_text.config(text=f"✅ {step.name} completed in {duration:.1f}s")
                    self.parent.after(100, lambda: load_step(step_index + 1))
                except Exception as e:
                    self.status_text.config(text=f"❌ Error: {str(e)}")
                    self.update_step_display(step_index, "error")
                    self.parent.after(3000, lambda: load_step(step_index + 1))
            threading.Thread(target=do_work, daemon=True).start()
        self.parent.after(500, lambda: load_step(0))
    
    def perform_loading_step(self, step_index: int):
        step = self.loading_steps[step_index]
        if step.name == "Initializing MetaTrader 5 API":
            import MetaTrader5 as mt5
            if not mt5.initialize():
                raise Exception(f"MT5 initialization failed: {mt5.last_error()}")
            time.sleep(0.5)
        elif step.name == "Loading Trading Configuration":
            try:
                with open("trading_config.json", 'r') as f:
                    config_data = json.load(f)
                time.sleep(0.3)
            except:
                time.sleep(0.3)
        elif step.name == "Connecting to Supabase Database":
            time.sleep(0.5)
        elif step.name == "Initializing News Manager":
            time.sleep(0.4)
        elif step.name == "Loading Indicator Systems":
            time.sleep(0.6)
        elif step.name == "Preloading Market Data":
            time.sleep(0.4)
        elif step.name == "Compiling ICT/SMS Indicators":
            time.sleep(0.5)
        elif step.name == "Preparing Reversal Engine":
            time.sleep(0.3)
        elif step.name == "Finalizing System":
            time.sleep(0.2)
    
    def update_step_display(self, step_index: int, status: str):
        if step_index >= len(self.step_labels):
            return
        step_data = self.step_labels[step_index]
        icon = step_data['icon']
        name_label = step_data['name']
        if status == "loading":
            icon.config(text="◉", fg=self.colors['accent_warning'])
            name_label.config(fg=self.colors['accent_warning'])
        elif status == "completed":
            icon.config(text="✓", fg=self.colors['accent_success'])
            name_label.config(fg=self.colors['accent_success'])
        elif status == "error":
            icon.config(text="✗", fg=self.colors['accent_danger'])
            name_label.config(fg=self.colors['accent_danger'])
    
    def update_progress(self):
        completed_weight = sum(step.weight for step in self.loading_steps if step.completed)
        self.current_progress = (completed_weight / self.total_weight) * 100
        self.progress_bar.set_value(self.current_progress, animate=True)
    
    def loading_complete(self):
        if self.animation_id:
            self.parent.after_cancel(self.animation_id)
            self.animation_id = None
        self.logo_label.config(font=('Montserrat', 48, 'bold'))
        self.status_text.config(
            text="✨ System ready! Please log in to continue ✨",
            fg=self.colors['accent_success']
        )
        self.show_welcome_message()
        self.steps_frame.pack_forget()
        self.login_form_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=20)
        self.fade_in_form()
        self.username_entry.focus()
    
    def show_welcome_message(self):
        welcome_frame = tk.Frame(self.login_card, bg=self.colors['bg_card'])
        welcome_frame.pack(pady=(0, 10))
        welcome_label = tk.Label(
            welcome_frame,
            text="🚀 Ready to Trade!",
            font=('Montserrat', 14, 'bold'),
            fg=self.colors['accent_success'],
            bg=self.colors['bg_card']
        )
        welcome_label.pack()
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
            welcome_frame.destroy()
        self.parent.after(2000, lambda: threading.Thread(target=fade_out, daemon=True).start())
    
    def fade_in_form(self):
        elements = [self.login_form_frame]
        for widget in self.login_form_frame.winfo_children():
            elements.append(widget)
        def animate_fade(index=0):
            if index >= len(elements):
                return
            try:
                elements[index].config(fg=self.colors['text_primary'])
            except:
                pass
            self.parent.after(50, lambda: animate_fade(index + 1))
        animate_fade()
    
    def handle_login(self):
        username = self.username_entry.get().strip()
        login_code = self.code_entry.get().strip()
        if not username or not login_code:
            self.message_label.config(text="Username and login code are required")
            self.shake_login_form()
            return
        self.login_button.config(state='disabled')
        self.create_button.config(state='disabled')
        self.status_text.config(text="🔐 Authenticating...", fg=self.colors['accent_warning'])
        def do_login():
            time.sleep(1.5)
            self.parent.after(0, lambda: self.on_login_callback(username, login_code))
        threading.Thread(target=do_login, daemon=True).start()
    
    def shake_login_form(self):
        # Store the original placement parameters
        original_relx = 0.5
        original_rely = 0.5
        original_width = 500
        original_height = 600
        
        def shake(step=0):
            if step > 10:
                # Restore original centered position
                self.login_card.place(relx=original_relx, rely=original_rely, anchor='center',
                                    width=original_width, height=original_height)
                return
            offset = 5 if step % 2 == 0 else -5
            # Temporarily move by absolute pixels (doesn't affect relative placement)
            current_x = self.login_card.winfo_x()
            self.login_card.place_configure(x=current_x + offset)
            self.after(50, lambda: shake(step + 1))
        shake()
        
    def destroy(self):
        if self.animation_id:
            try:
                self.parent.after_cancel(self.animation_id)
            except:
                pass
        try:
            self.container.destroy()
        except:
            pass