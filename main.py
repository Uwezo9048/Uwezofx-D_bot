# main.py
import sys
import os

# ---- Windows 7 DLL Path Fix (for frozen executables) ----
if sys.platform == "win32":
    if hasattr(sys, 'frozen'):
        base_path = sys._MEIPASS
        os.environ['PATH'] = base_path + ';' + os.environ.get('PATH', '')

# ---- Normal imports ----
import tkinter as tk
from modules.gui.app import DerivUwezoApp

def main():
    root = tk.Tk()
    app = DerivUwezoApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()