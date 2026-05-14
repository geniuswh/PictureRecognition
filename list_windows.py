"""枚举所有可见窗口"""
import win32gui

results = []
def callback(hwnd, _):
    if win32gui.IsWindowVisible(hwnd):
        title = win32gui.GetWindowText(hwnd)
        if title:
            results.append((hwnd, title))
    return True

win32gui.EnumWindows(callback, None)
for hwnd, title in results:
    print(f"[{hwnd}] {title}")
