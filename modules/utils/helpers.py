# modules/utils/helpers.py
import sys
import os
import ctypes
from PIL import Image, ImageTk

def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller."""
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_path, relative_path)

def writable_path(relative_path):
    """Get absolute path for writable files (logs, saved configs)."""
    if getattr(sys, 'frozen', False):
        base_path = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'UWEZO-Deriv-Bot')
        if not os.path.exists(base_path):
            os.makedirs(base_path)
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_path, relative_path)

def set_app_icon(root):
    try:
        if sys.platform == "win32":
            icon_ico = resource_path("icon.ico")
            if os.path.exists(icon_ico):
                myappid = 'uwezo.fx.deriv.bot.6.0'
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
                root.iconbitmap(default=icon_ico)
                return icon_ico
    except Exception:
        pass
    return None

def load_logo():
    try:
        icon_png = resource_path("icon.png")
        if os.path.exists(icon_png):
            img = Image.open(icon_png)
            img = img.resize((64, 64), Image.Resampling.LANCZOS)
            return ImageTk.PhotoImage(img)
    except Exception:
        pass
    return None

def darken_color(hex_color, factor=0.8):
    hex_color = hex_color.lstrip('#')
    rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    darkened = tuple(max(0, int(c * factor)) for c in rgb)
    return f'#{darkened[0]:02x}{darkened[1]:02x}{darkened[2]:02x}'