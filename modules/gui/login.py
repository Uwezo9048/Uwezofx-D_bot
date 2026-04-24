# modules/gui/login.py
import tkinter as tk
from modules.gui.widgets import ModernUI, ModernCard

class ModernLoginScreen:
    def __init__(self, parent, colors, on_login_callback, on_create_account, on_password_reset):
        self.parent = parent
        self.colors = colors
        self.on_login_callback = on_login_callback
        self.on_create_account = on_create_account
        self.on_password_reset = on_password_reset
        self.setup_ui()

    def setup_ui(self):
        self.container = tk.Frame(self.parent, bg=self.colors['bg_dark'])
        self.container.place(relx=0, rely=0, relwidth=1, relheight=1)

        self.login_card = ModernCard(self.container, title=None)
        self.login_card.place(relx=0.5, rely=0.5, anchor='center', width=400, height=450)

        form = tk.Frame(self.login_card.content, bg=self.colors['bg_card'])
        form.pack(pady=20)

        # Username
        tk.Label(form, text="Username", fg=self.colors['text_secondary'], bg=self.colors['bg_card']).grid(row=0, column=0, padx=5, pady=5, sticky='w')
        self.username_entry = tk.Entry(form, width=25, bg=self.colors['bg_sidebar'], fg='white', insertbackground='white', bd=0)
        self.username_entry.grid(row=0, column=1, padx=5, pady=5)
        ModernUI.add_glow_effect(self.username_entry)

        # Login Code
        tk.Label(form, text="Login Code", fg=self.colors['text_secondary'], bg=self.colors['bg_card']).grid(row=1, column=0, padx=5, pady=5, sticky='w')
        self.code_entry = tk.Entry(form, width=25, show="*", bg=self.colors['bg_sidebar'], fg='white', insertbackground='white', bd=0)
        self.code_entry.grid(row=1, column=1, padx=5, pady=5)
        ModernUI.add_glow_effect(self.code_entry)

        # Buttons
        btn_frame = tk.Frame(self.login_card.content, bg=self.colors['bg_card'])
        btn_frame.pack(pady=10)

        self.login_btn = ModernUI.create_gradient_button(btn_frame, "Login", self.handle_login, 'primary')
        self.login_btn.pack(side=tk.LEFT, padx=5)
        create_btn = ModernUI.create_gradient_button(btn_frame, "Create Account", self.on_create_account, 'success')
        create_btn.pack(side=tk.LEFT, padx=5)
        forgot_btn = ModernUI.create_gradient_button(btn_frame, "Forgot Password?", self.on_password_reset, 'info')
        forgot_btn.pack(side=tk.LEFT, padx=5)

        self.message_label = tk.Label(self.login_card.content, text="", fg=self.colors['accent_danger'], bg=self.colors['bg_card'])
        self.message_label.pack(pady=10)

        # --- Keyboard navigation ---
        # Enter key triggers login
        self.username_entry.bind('<Return>', lambda e: self.handle_login())
        self.code_entry.bind('<Return>', lambda e: self.handle_login())
        # Also bind to container for when focus is on buttons (optional)
        self.container.bind('<Return>', lambda e: self.handle_login())

        # Up/Down arrow keys to move between the two entries
        self.username_entry.bind('<Down>', lambda e: self.code_entry.focus_set())
        self.code_entry.bind('<Up>', lambda e: self.username_entry.focus_set())
        # Optional: also move from code to username with Down
        self.code_entry.bind('<Down>', lambda e: self.username_entry.focus_set())
        self.username_entry.bind('<Up>', lambda e: self.code_entry.focus_set())

        # Set initial focus
        self.username_entry.focus_set()

    def handle_login(self):
        username = self.username_entry.get().strip()
        code = self.code_entry.get().strip()
        if not username or not code:
            self.message_label.config(text="Username and login code required")
            return
        self.on_login_callback(username, code)

    def shake_login_form(self):
        def shake(step=0):
            if step > 10:
                self.login_card.place(relx=0.5, rely=0.5, anchor='center', width=400, height=450)
                return
            offset = 5 if step % 2 == 0 else -5
            x_abs = self.login_card.winfo_x()
            self.login_card.place_configure(x=x_abs + offset)
            self.parent.after(50, lambda: shake(step + 1))
        shake()

    def destroy(self):
        self.container.destroy()