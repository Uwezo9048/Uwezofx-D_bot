# modules/gui/widgets.py
import tkinter as tk
from tkinter import ttk
from modules.utils.helpers import darken_color

class ModernUI:
    COLORS = {
        'bg_dark': '#0B0F1A',
        'bg_card': '#1A233A',
        'bg_sidebar': '#111B2E',
        'text_primary': '#FFFFFF',
        'text_secondary': '#A0B4D9',
        'text_muted': '#6B7FA3',
        'accent_primary': '#6C63FF',
        'accent_success': '#00D9A5',
        'accent_danger': '#FF5E7D',
        'accent_warning': '#FFB443',
        'accent_info': '#3FA2F7',
        'border': '#2E3F66',
        'hover': '#3D5690',
    }

    @staticmethod
    def add_glow_effect(widget, color='#6C63FF'):
        def on_enter(e):
            widget.config(highlightbackground=color, highlightthickness=2)
        def on_leave(e):
            widget.config(highlightbackground=ModernUI.COLORS['border'], highlightthickness=1)
        widget.bind('<Enter>', on_enter)
        widget.bind('<Leave>', on_leave)
        widget.config(highlightbackground=ModernUI.COLORS['border'], highlightthickness=1)
        return widget

    @staticmethod
    def create_gradient_button(parent, text, command, style='primary'):
        colors = {
            'primary': ('#6C63FF', '#4A42D9'),
            'success': ('#00D9A5', '#00B38A'),
            'danger': ('#FF5E7D', '#E64A6B'),
            'warning': ('#FFB443', '#E69A30'),
            'info': ('#3FA2F7', '#2E8CE0'),
        }
        start, end = colors.get(style, colors['primary'])
        btn = tk.Button(parent, text=text, bg=start, fg='white',
                        font=('Segoe UI', 10, 'bold'), bd=0, padx=20, pady=10,
                        cursor='hand2', activebackground=end, activeforeground='white',
                        command=command)
        def on_enter(e):
            btn.config(bg=end)
        def on_leave(e):
            btn.config(bg=start)
        btn.bind('<Enter>', on_enter)
        btn.bind('<Leave>', on_leave)
        return btn

class ModernCard(tk.Frame):
    def __init__(self, parent, title=None, **kwargs):
        super().__init__(parent, bg=ModernUI.COLORS['bg_card'], **kwargs)
        self.config(highlightbackground=ModernUI.COLORS['border'], highlightthickness=1)
        if title:
            title_frame = tk.Frame(self, bg=ModernUI.COLORS['bg_card'])
            title_frame.pack(fill='x', padx=15, pady=(15,5))
            tk.Label(title_frame, text=title, font=('Segoe UI', 13, 'bold'),
                     fg=ModernUI.COLORS['text_primary'], bg=ModernUI.COLORS['bg_card']).pack(side='left')
        self.content = tk.Frame(self, bg=ModernUI.COLORS['bg_card'])
        self.content.pack(fill='both', expand=True, padx=15, pady=15)