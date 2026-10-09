from pywinauto.application import Application
from pywinauto import Desktop
import time
import sys

print("Connecting to SportCamComparator...")
try:
    app = Application(backend="uia").connect(title="SportCamComparator", timeout=10)
    dlg = app.window(title="SportCamComparator")
except Exception as e:
    print(f"Connection failed: {e}")
    sys.exit(1)

print("Connected!")
time.sleep(2)
try:
    btn = dlg.child_window(title="Export", control_type="Button") # Assuming button text is Export or something similar.
    # Actually wait, let's just find the Export button
    btn = dlg.child_window(auto_id="btn_export") # Wait, is there auto_id? PySide6 doesn't always expose it nicely to UIA.
    # Let's print controls
    dlg.print_control_identifiers(depth=2)
except Exception as e:
    print(e)
