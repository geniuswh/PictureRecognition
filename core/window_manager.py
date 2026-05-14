"""窗口管理模块：枚举窗口、截图、获取窗口信息"""

import ctypes
import ctypes.wintypes
from typing import List, Optional, Tuple

import win32gui
import win32ui
import win32con
from PIL import Image
import numpy as np


class WindowInfo:
    """窗口信息"""

    def __init__(self, hwnd: int, title: str, class_name: str):
        self.hwnd = hwnd
        self.title = title
        self.class_name = class_name

    def __str__(self):
        return f"{self.title} [{self.class_name}] (hwnd={self.hwnd})"

    def __repr__(self):
        return self.__str__()


class WindowManager:
    """管理目标窗口的查找、截图等操作"""

    @staticmethod
    def enumerate_windows() -> List[WindowInfo]:
        """枚举所有可见窗口"""
        windows = []

        def callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                class_name = win32gui.GetClassName(hwnd)
                if title:  # 过滤掉无标题窗口
                    windows.append(WindowInfo(hwnd, title, class_name))
            return True

        win32gui.EnumWindows(callback, None)
        return windows

    @staticmethod
    def find_window_by_title(title: str) -> Optional[WindowInfo]:
        """根据标题模糊查找窗口"""
        windows = WindowManager.enumerate_windows()
        for w in windows:
            if title.lower() in w.title.lower():
                return w
        return None

    @staticmethod
    def get_window_rect(hwnd: int) -> Tuple[int, int, int, int]:
        """获取窗口矩形 (left, top, right, bottom)"""
        return win32gui.GetWindowRect(hwnd)

    @staticmethod
    def _cleanup_bitmap(save_dc, mfc_dc, hwnd_dc, hwnd, bitmap):
        """安全清理GDI资源"""
        try:
            save_dc.DeleteDC()
        except Exception:
            pass
        try:
            mfc_dc.DeleteDC()
        except Exception:
            pass
        try:
            win32gui.ReleaseDC(hwnd, hwnd_dc)
        except Exception:
            pass
        try:
            win32gui.DeleteObject(bitmap.GetHandle())
        except Exception:
            pass

    @staticmethod
    def capture_window(hwnd: int) -> np.ndarray:
        """截取指定窗口的截图，返回BGR格式的numpy数组

        对浏览器等使用硬件加速渲染的窗口，直接使用屏幕截图更可靠。
        """
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        width = right - left
        height = bottom - top

        if width <= 0 or height <= 0:
            raise ValueError(f"窗口尺寸异常: {width}x{height}")

        # 直接截取屏幕上窗口对应区域（最可靠，能捕获浏览器硬件加速内容）
        return WindowManager.capture_screen_region(left, top, width, height)

    @staticmethod
    def capture_screen_region(x: int, y: int, width: int, height: int) -> np.ndarray:
        """截取屏幕指定区域"""
        hwnd_dc = win32gui.GetWindowDC(0)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()

        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bitmap)

        save_dc.BitBlt((0, 0), (width, height), mfc_dc, (x, y), win32con.SRCCOPY)

        bmp_info = bitmap.GetInfo()
        bmp_str = bitmap.GetBitmapBits(True)

        img = np.frombuffer(bmp_str, dtype=np.uint8)
        img = img.reshape((bmp_info['bmHeight'], bmp_info['bmWidth'], 4))
        img_bgr = img[:, :, :3].copy()

        WindowManager._cleanup_bitmap(save_dc, mfc_dc, hwnd_dc, 0, bitmap)
        return img_bgr

    @staticmethod
    def capture_window_region(hwnd: int, x: int, y: int, width: int, height: int) -> np.ndarray:
        """截取窗口内指定区域（x,y相对于窗口左上角）"""
        full = WindowManager.capture_window(hwnd)
        h, w = full.shape[:2]
        # 裁剪，确保不越界
        x1 = max(0, x)
        y1 = max(0, y)
        x2 = min(w, x + width)
        y2 = min(h, y + height)
        return full[y1:y2, x1:x2].copy()
