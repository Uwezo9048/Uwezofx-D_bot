# modules/gui/widgets.py
import tkinter as tk
from tkinter import ttk
from modules.utils.helpers import darken_color

class ModernUI:
    COLORS = {
        'bg_dark': '#05070B',
        'bg_card': '#101722',
        'bg_sidebar': '#0B111A',
        'bg_panel': '#151F2E',
        'text_primary': '#F6F8FB',
        'text_secondary': '#B8C2D6',
        'text_muted': '#77849A',
        'accent_primary': '#00E0A4',
        'accent_success': '#13D67F',
        'accent_danger': '#FF4D67',
        'accent_warning': '#F5B84B',
        'accent_info': '#38BDF8',
        'border': '#263244',
        'hover': '#1F3046',
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
            'primary': ('#00E0A4', '#00B987'),
            'success': ('#13D67F', '#0FB169'),
            'danger': ('#FF4D67', '#D93A52'),
            'warning': ('#F5B84B', '#D89828'),
            'info': ('#38BDF8', '#1593D1'),
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

    @staticmethod
    def configure_ttk_styles(root):
        style = ttk.Style(root)
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        colors = ModernUI.COLORS
        style.configure(
            'TNotebook',
            background=colors['bg_dark'],
            borderwidth=0,
            tabmargins=(0, 0, 0, 0),
        )
        style.configure(
            'TNotebook.Tab',
            background='#E8EBF2',
            foreground='#162033',
            padding=(14, 8),
            font=('Segoe UI', 9, 'bold'),
            borderwidth=0,
        )
        style.map(
            'TNotebook.Tab',
            background=[('selected', '#FFFFFF'), ('active', '#F5F7FB')],
            foreground=[('selected', '#0B111A'), ('active', '#0B111A')],
        )
        style.configure(
            'Treeview',
            background=colors['bg_sidebar'],
            fieldbackground=colors['bg_sidebar'],
            foreground=colors['text_primary'],
            rowheight=28,
            bordercolor=colors['border'],
            borderwidth=0,
            font=('Segoe UI', 9),
        )
        style.configure(
            'Treeview.Heading',
            background='#F3F5F8',
            foreground='#111827',
            relief='flat',
            font=('Segoe UI', 9, 'bold'),
            padding=(8, 6),
        )
        style.map(
            'Treeview',
            background=[('selected', colors['hover'])],
            foreground=[('selected', colors['text_primary'])],
        )
        style.configure(
            'TCombobox',
            fieldbackground=colors['bg_sidebar'],
            background=colors['bg_sidebar'],
            foreground=colors['text_primary'],
            arrowcolor=colors['accent_primary'],
            bordercolor=colors['border'],
            lightcolor=colors['border'],
            darkcolor=colors['border'],
        )

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
