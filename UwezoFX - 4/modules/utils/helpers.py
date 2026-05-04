# modules/utils/helpers.py
import sys
import os
import platform
import ctypes
from PIL import Image

def resource_path(relative_path):
    """Get absolute path to a static resource (bundled with the EXE)."""
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_path, relative_path)

def writable_path(relative_path):
    """Get absolute path for writable files (logs, saved configs) – next to EXE."""
    if getattr(sys, 'frozen', False):
        base_path = os.path.dirname(sys.executable)
    else:
        base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_path, relative_path)

def darken_color(hex_color, factor=0.8):
    hex_color = hex_color.lstrip('#')
    rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    darkened = tuple(max(0, int(c * factor)) for c in rgb)
    return f'#{darkened[0]:02x}{darkened[1]:02x}{darkened[2]:02x}'

def lighten_color(hex_color, factor=1.2):
    hex_color = hex_color.lstrip('#')
    rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    lightened = tuple(min(255, int(c * factor)) for c in rgb)
    return f'#{lightened[0]:02x}{lightened[1]:02x}{lightened[2]:02x}'

def get_windows_version():
    """Detect Windows version for compatibility handling"""
    import sys
    if sys.platform != 'win32':
        return None
    
    try:
        import platform
        version = platform.version()
        
        if '10.0' in version:
            major = int(version.split('.')[0])
            if major >= 22000:
                return '11'
            else:
                return '10'
        elif '6.3' in version:
            return '8.1'
        elif '6.2' in version:
            return '8'
        elif '6.1' in version:
            return '7'
        else:
            return 'unknown'
    except Exception:
        return 'unknown'

def is_windows_7_or_8():
    """Check if running on Windows 7 or 8"""
    version = get_windows_version()
    return version in ['7', '8', '8.1']

def set_app_icon(root):
    """Set the window icon (top‑left corner and taskbar) from a PNG file in the root folder."""
    try:
        if sys.platform == "win32":
            # Get the root folder (where main.py is)
            root_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
            icon_png = os.path.join(root_dir, "icon.png")
            
            if os.path.exists(icon_png):
                # Convert PNG to ICO and save as temporary file
                img = Image.open(icon_png)
                ico_path = os.path.join(root_dir, "temp_icon.ico")
                img.save(ico_path, format='ICO', sizes=[(32,32), (64,64), (128,128), (256,256)])
                
                # Set the Windows AppUserModelID (optional, for taskbar grouping)
                myappid = 'uwezo.fx.trading.system.2.0'
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
                
                # Apply the icon to the Tkinter window
                root.iconbitmap(default=os.path.abspath(ico_path))
                return ico_path
            else:
                print("⚠️ No icon.png found in root folder. Using default Tk icon.")
    except Exception as e:
        print(f"Icon loading error: {e}")
    return None