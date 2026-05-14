"""自动测试脚本：刷新Edge中的红包测试页面，执行脚本2，验证执行时间"""

import os
import sys
import time

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT_DIR)

from core.execution_engine import ExecutionEngine
from core.script_manager import ScriptManager
from core.window_manager import WindowManager
import win32gui
import win32con
import win32api
import win32clipboard


def set_clipboard_text(text):
    """设置剪贴板文本"""
    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
    win32clipboard.CloseClipboard()


def navigate_to_url(hwnd, url):
    """在Edge地址栏通过剪贴板粘贴URL并回车导航"""
    try:
        set_clipboard_text(url)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        # Ctrl+L 聚焦地址栏
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(0x4C, 0, 0, 0)  # L key
        time.sleep(0.05)
        win32api.keybd_event(0x4C, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.3)
        # Ctrl+A 全选地址栏内容
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(0x41, 0, 0, 0)  # A key
        time.sleep(0.05)
        win32api.keybd_event(0x41, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.1)
        # Ctrl+V 粘贴URL
        win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(0x56, 0, 0, 0)  # V key
        time.sleep(0.05)
        win32api.keybd_event(0x56, 0, win32con.KEYEVENTF_KEYUP, 0)
        win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(0.2)
        # 按回车
        win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)
        time.sleep(0.05)
        win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(3.0)
    except Exception:
        pass


def main():
    result_file = os.path.join(ROOT_DIR, "test_result.txt")

    script_config = ScriptManager().load_script("脚本2")
    if not script_config:
        with open(result_file, "w", encoding="utf-8") as f:
            f.write("错误: 找不到脚本2\n")
        return

    target_title = script_config.target_window_title
    window = WindowManager.find_window_by_title(target_title)
    if not window:
        with open(result_file, "w", encoding="utf-8") as f:
            f.write(f"错误: 找不到窗口 '{target_title}'\n")
            windows = WindowManager.enumerate_windows()
            for w in windows:
                if w.title:
                    f.write(f"  - [{w.hwnd}] {w.title}\n")
        return

    hwnd = window.hwnd

    # 通过地址栏重新导航页面来重置红包状态
    html_path = os.path.join(ROOT_DIR, "test_red_packet.html")
    file_url = "file:///" + html_path.replace("\\", "/")
    navigate_to_url(hwnd, file_url)

    # 窗口置前
    try:
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.5)
    except Exception:
        pass

    # 执行脚本
    engine = ExecutionEngine()
    result = engine.execute(script_config, hwnd)

    # 读取最新日志获取耗时
    log_dir = os.path.join(ROOT_DIR, "logs")
    log_files = sorted(
        [f for f in os.listdir(log_dir) if f.startswith("execution_") and f.endswith(".log")],
        reverse=True
    )
    log_content = ""
    elapsed_str = "未知"
    if log_files:
        latest_log = os.path.join(log_dir, log_files[0])
        with open(latest_log, "r", encoding="utf-8") as f:
            log_content = f.read()
        for line in log_content.split("\n"):
            if "总耗时" in line:
                elapsed_str = line.strip()

    with open(result_file, "w", encoding="utf-8") as f:
        f.write(f"执行结果: {'成功' if result else '失败'}\n")
        f.write(f"{elapsed_str}\n\n")
        f.write("=== 关键日志 ===\n")
        for line in log_content.split("\n"):
            line = line.strip()
            if any(k in line for k in ["总耗时", "完成度检查", "补漏", "已抢", "脚本执行", "步骤1", "步骤2", "匹配", "点击"]):
                f.write(f"  {line}\n")


if __name__ == "__main__":
    main()
