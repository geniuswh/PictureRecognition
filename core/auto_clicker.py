"""自动点击模块：模拟鼠标点击"""

import time
from typing import Tuple, Optional, Callable

import win32api
import win32con
import win32gui

from .window_manager import WindowManager


class AutoClicker:
    """自动点击器"""

    def __init__(self):
        self._running = False
        self._paused = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    def stop(self):
        self._running = False
        self._paused = False

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    @staticmethod
    def click_position(hwnd: int, x: int, y: int, button: str = "left"):
        """
        在窗口的指定坐标点击（坐标相对于窗口左上角）

        Args:
            hwnd: 窗口句柄
            x: 相对于窗口左上角的x坐标
            y: 相对于窗口左上角的y坐标
            button: 鼠标按钮 "left" / "right"
        """
        # 将窗口内坐标转换为屏幕坐标
        left, top, _, _ = win32gui.GetWindowRect(hwnd)
        screen_x = left + x
        screen_y = top + y

        # 将窗口置前
        try:
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.01)
        except Exception:
            pass

        # 移动鼠标并点击
        win32api.SetCursorPos((screen_x, screen_y))
        time.sleep(0.01)

        if button == "left":
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, screen_x, screen_y, 0, 0)
            time.sleep(0.01)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, screen_x, screen_y, 0, 0)
        elif button == "right":
            win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, screen_x, screen_y, 0, 0)
            time.sleep(0.01)
            win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, screen_x, screen_y, 0, 0)

    @staticmethod
    def click_screen(x: int, y: int, button: str = "left"):
        """点击屏幕绝对坐标"""
        win32api.SetCursorPos((x, y))
        time.sleep(0.01)

        if button == "left":
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, x, y, 0, 0)
            time.sleep(0.01)
            win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, x, y, 0, 0)
        elif button == "right":
            win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, x, y, 0, 0)
            time.sleep(0.01)
            win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, x, y, 0, 0)
