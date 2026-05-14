"""主窗口UI"""

import os
import sys
import time
import shutil
from typing import Optional, List

import cv2
import numpy as np
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QSpinBox, QDoubleSpinBox,
    QGroupBox, QListWidget, QListWidgetItem, QFileDialog,
    QMessageBox, QLineEdit, QInputDialog, QSplitter,
    QAbstractItemView, QApplication, QStatusBar, QMenuBar,
    QAction, QToolBar, QTabWidget, QTextEdit, QGridLayout,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer
from PyQt5.QtGui import QPixmap, QImage, QIcon, QFont

# 添加项目根目录到路径
import sys
if getattr(sys, 'frozen', False):
    ROOT_DIR = os.path.join(os.path.dirname(sys.executable), '_internal')
else:
    ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from core.window_manager import WindowManager, WindowInfo
from core.image_matcher import ImageMatcher, MatchResult
from core.auto_clicker import AutoClicker
from core.script_manager import ScriptConfig, StepConfig, ActionGroupConfig, ScriptManager
from core.execution_engine import ExecutionEngine

TEMPLATES_DIR = os.path.join(ROOT_DIR, "templates")


def _qpixmap_from_path(path: str, width: int = 0, height: int = 0) -> QPixmap:
    """从路径加载QPixmap，支持中文路径"""
    try:
        # 方式1: 通过cv2读取再转换（支持中文路径）
        data = np.fromfile(path, dtype=np.uint8)
        cv_img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if cv_img is not None:
            pixmap = cv2_to_qpixmap(cv_img)
            if width > 0 or height > 0:
                pixmap = pixmap.scaled(
                    width if width > 0 else 4096,
                    height if height > 0 else 4096,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            return pixmap
    except Exception:
        pass
    # 方式2: 直接用QPixmap加载
    pixmap = QPixmap(path)
    if width > 0 or height > 0:
        pixmap = pixmap.scaled(
            width if width > 0 else 4096,
            height if height > 0 else 4096,
            Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
    return pixmap


def cv2_to_qpixmap(cv_img: np.ndarray) -> QPixmap:
    """将OpenCV图像(BGR)转换为QPixmap"""
    if len(cv_img.shape) == 2:
        h, w = cv_img.shape
        bytes_per_line = w
        qimg = QImage(cv_img.data.tobytes(), w, h, bytes_per_line, QImage.Format_Grayscale8)
    else:
        h, w, ch = cv_img.shape
        rgb = cv2.cvtColor(cv_img, cv2.COLOR_BGR2RGB)
        bytes_per_line = ch * w
        qimg = QImage(rgb.data.tobytes(), w, h, bytes_per_line, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg.copy())


class ExecutionThread(QThread):
    """执行脚本的线程"""
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool)
    round_signal = pyqtSignal(int, int)
    step_signal = pyqtSignal(int, int)
    match_signal = pyqtSignal(int, list)
    click_signal = pyqtSignal(int, int, int)

    def __init__(self, engine: ExecutionEngine, script: ScriptConfig, hwnd: int):
        super().__init__()
        self.engine = engine
        self.script = script
        self.hwnd = hwnd

    def run(self):
        self.engine.set_callbacks(
            on_log=lambda msg: self.log_signal.emit(msg),
            on_round_start=lambda r, t: self.round_signal.emit(r, t),
            on_step_start=lambda s, r: self.step_signal.emit(s, r),
            on_match_found=lambda s, m: self.match_signal.emit(s, m),
            on_click=lambda s, x, y: self.click_signal.emit(s, x, y),
        )
        result = self.engine.execute(self.script, self.hwnd)
        self.finished_signal.emit(result)


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("图片识别自动点击器")
        self.setMinimumSize(800, 550)

        # 状态
        self._current_hwnd: Optional[int] = None
        self._steps: List[StepConfig] = []
        self._step_images: dict = {}  # step_id -> image_path
        self._next_step_id = 1
        self._script_manager = ScriptManager()
        self._engine = ExecutionEngine()
        self._exec_thread: Optional[ExecutionThread] = None
        self._selected_step_id: Optional[int] = None

        # 确保模板目录存在
        os.makedirs(TEMPLATES_DIR, exist_ok=True)

        self._init_ui()
        self._refresh_windows()
        self._refresh_scripts()

        # 定时刷新窗口列表
        self._timer = QTimer()
        self._timer.timeout.connect(self._refresh_windows)
        self._timer.start(5000)

    def _init_ui(self):
        """初始化界面"""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # ===== 左侧面板 =====
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        # 模板图片列表
        img_group = QGroupBox("步骤列表（拖拽排序）")
        img_layout = QVBoxLayout(img_group)

        self.step_list = QListWidget()
        self.step_list.setIconSize(QSize(40, 40))
        self.step_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.step_list.currentRowChanged.connect(self._on_step_selected)
        img_layout.addWidget(self.step_list)

        btn_row = QHBoxLayout()
        self.btn_add_image = QPushButton("添加图片")
        self.btn_add_image.clicked.connect(self._add_step)
        self.btn_remove_image = QPushButton("删除选中")
        self.btn_remove_image.clicked.connect(self._remove_step)
        self.btn_move_up = QPushButton("上移")
        self.btn_move_up.clicked.connect(lambda: self._move_step(-1))
        self.btn_move_down = QPushButton("下移")
        self.btn_move_down.clicked.connect(lambda: self._move_step(1))
        btn_row.addWidget(self.btn_add_image)
        btn_row.addWidget(self.btn_remove_image)
        btn_row.addWidget(self.btn_move_up)
        btn_row.addWidget(self.btn_move_down)
        img_layout.addLayout(btn_row)

        left_layout.addWidget(img_group)

        # 步骤参数
        step_param_group = QGroupBox("步骤参数")
        step_param_layout = QGridLayout(step_param_group)

        step_param_layout.addWidget(QLabel("点击次数:"), 0, 0)
        self.spin_click_count = QSpinBox()
        self.spin_click_count.setRange(1, 100)
        self.spin_click_count.setValue(1)
        step_param_layout.addWidget(self.spin_click_count, 0, 1)

        step_param_layout.addWidget(QLabel("点击间隔(秒):"), 1, 0)
        self.spin_click_interval = QDoubleSpinBox()
        self.spin_click_interval.setRange(0.0, 60.0)
        self.spin_click_interval.setValue(0.3)
        self.spin_click_interval.setSingleStep(0.1)
        step_param_layout.addWidget(self.spin_click_interval, 1, 1)

        step_param_layout.addWidget(QLabel("匹配阈值:"), 2, 0)
        self.spin_threshold = QDoubleSpinBox()
        self.spin_threshold.setRange(0.1, 1.0)
        self.spin_threshold.setValue(0.8)
        self.spin_threshold.setSingleStep(0.05)
        step_param_layout.addWidget(self.spin_threshold, 2, 1)

        step_param_layout.addWidget(QLabel("多匹配:"), 3, 0)
        self.combo_multi_match = QComboBox()
        self.combo_multi_match.addItems(["逐个点击", "仅点击第一个"])
        step_param_layout.addWidget(self.combo_multi_match, 3, 1)

        step_param_layout.addWidget(QLabel("执行后等待(秒):"), 4, 0)
        self.spin_post_delay = QDoubleSpinBox()
        self.spin_post_delay.setRange(0.0, 60.0)
        self.spin_post_delay.setValue(1.0)
        self.spin_post_delay.setSingleStep(0.1)
        step_param_layout.addWidget(self.spin_post_delay, 4, 1)

        self.btn_apply_step = QPushButton("应用步骤参数")
        self.btn_apply_step.clicked.connect(self._apply_step_params)
        step_param_layout.addWidget(self.btn_apply_step, 5, 0, 1, 2)

        # 参数变化时自动应用
        self.spin_click_count.valueChanged.connect(self._apply_step_params)
        self.spin_click_interval.valueChanged.connect(self._apply_step_params)
        self.spin_threshold.valueChanged.connect(self._apply_step_params)
        self.combo_multi_match.currentIndexChanged.connect(self._apply_step_params)
        self.spin_post_delay.valueChanged.connect(self._apply_step_params)

        left_layout.addWidget(step_param_group)

        # ===== 中间面板 =====
        mid_panel = QWidget()
        mid_layout = QVBoxLayout(mid_panel)

        # 预览区
        preview_group = QGroupBox("预览区")
        preview_layout = QVBoxLayout(preview_group)

        self.preview_label = QLabel("选择目标窗口后点击\"识别预览\"")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(300, 200)
        self.preview_label.setStyleSheet("border: 1px solid #ccc; background: #1a1a2e;")
        preview_layout.addWidget(self.preview_label)

        self.btn_preview = QPushButton("识别预览")
        self.btn_preview.clicked.connect(self._do_preview)
        preview_layout.addWidget(self.btn_preview)

        mid_layout.addWidget(preview_group)

        # ===== 右侧面板 =====
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        # 目标窗口
        win_group = QGroupBox("目标窗口")
        win_layout = QVBoxLayout(win_group)

        self.combo_windows = QComboBox()
        win_layout.addWidget(self.combo_windows)

        self.btn_refresh_windows = QPushButton("刷新窗口列表")
        self.btn_refresh_windows.clicked.connect(self._refresh_windows)
        win_layout.addWidget(self.btn_refresh_windows)

        right_layout.addWidget(win_group)

        # 动作组参数
        group_param = QGroupBox("动作组参数")
        group_layout = QGridLayout(group_param)

        group_layout.addWidget(QLabel("循环次数:"), 0, 0)
        self.spin_loop_count = QSpinBox()
        self.spin_loop_count.setRange(1, 9999)
        self.spin_loop_count.setValue(1)
        group_layout.addWidget(self.spin_loop_count, 0, 1)

        group_layout.addWidget(QLabel("轮次间隔(秒):"), 1, 0)
        self.spin_loop_interval = QDoubleSpinBox()
        self.spin_loop_interval.setRange(0.0, 60.0)
        self.spin_loop_interval.setValue(0.5)
        self.spin_loop_interval.setSingleStep(0.1)
        group_layout.addWidget(self.spin_loop_interval, 1, 1)

        group_layout.addWidget(QLabel("失败策略:"), 2, 0)
        self.combo_on_fail = QComboBox()
        self.combo_on_fail.addItems(["跳过继续", "重试3次", "终止执行"])
        group_layout.addWidget(self.combo_on_fail, 2, 1)

        group_layout.addWidget(QLabel("完成度检查:"), 3, 0)
        self.combo_completion_check = QComboBox()
        self.combo_completion_check.addItems(["开启", "关闭"])
        self.combo_completion_check.setToolTip("主循环结束后，自动检测步骤1是否还有遗漏目标并补上")
        group_layout.addWidget(self.combo_completion_check, 3, 1)

        right_layout.addWidget(group_param)

        # 脚本管理
        script_group = QGroupBox("脚本管理")
        script_layout = QVBoxLayout(script_group)

        self.combo_scripts = QComboBox()
        script_layout.addWidget(self.combo_scripts)

        script_btn_row1 = QHBoxLayout()
        self.btn_save_script = QPushButton("保存当前")
        self.btn_save_script.clicked.connect(self._save_script)
        self.btn_load_script = QPushButton("加载选中")
        self.btn_load_script.clicked.connect(self._load_script)
        script_btn_row1.addWidget(self.btn_save_script)
        script_btn_row1.addWidget(self.btn_load_script)
        script_layout.addLayout(script_btn_row1)

        script_btn_row2 = QHBoxLayout()
        self.btn_delete_script = QPushButton("删除选中")
        self.btn_delete_script.clicked.connect(self._delete_script)
        self.btn_rename_script = QPushButton("重命名")
        self.btn_rename_script.clicked.connect(self._rename_script)
        script_btn_row2.addWidget(self.btn_delete_script)
        script_btn_row2.addWidget(self.btn_rename_script)
        script_layout.addLayout(script_btn_row2)

        right_layout.addWidget(script_group)

        right_layout.addStretch()

        # ===== 底部 =====
        bottom_panel = QWidget()
        bottom_layout = QVBoxLayout(bottom_panel)

        # 控制按钮
        ctrl_row = QHBoxLayout()
        self.btn_start = QPushButton("▶ 开始执行")
        self.btn_start.setStyleSheet("font-size: 16px; padding: 8px; background-color: #4CAF50; color: white;")
        self.btn_start.clicked.connect(self._start_execution)

        self.btn_pause = QPushButton("⏸ 暂停")
        self.btn_pause.setStyleSheet("font-size: 16px; padding: 8px;")
        self.btn_pause.clicked.connect(self._pause_execution)
        self.btn_pause.setEnabled(False)

        self.btn_stop = QPushButton("⏹ 停止")
        self.btn_stop.setStyleSheet("font-size: 16px; padding: 8px; background-color: #f44336; color: white;")
        self.btn_stop.clicked.connect(self._stop_execution)
        self.btn_stop.setEnabled(False)

        ctrl_row.addWidget(self.btn_start)
        ctrl_row.addWidget(self.btn_pause)
        ctrl_row.addWidget(self.btn_stop)
        bottom_layout.addLayout(ctrl_row)

        # 日志
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(150)
        self.log_text.setStyleSheet("background: #1a1a2e; color: #00ff00; font-family: Consolas, monospace;")
        bottom_layout.addWidget(self.log_text)

        # 使用 QSplitter 组织布局
        top_splitter = QSplitter(Qt.Horizontal)
        top_splitter.addWidget(left_panel)
        top_splitter.addWidget(mid_panel)
        top_splitter.addWidget(right_panel)
        top_splitter.setStretchFactor(0, 1)
        top_splitter.setStretchFactor(1, 2)
        top_splitter.setStretchFactor(2, 1)

        main_v_splitter = QSplitter(Qt.Vertical)
        main_v_splitter.addWidget(top_splitter)
        main_v_splitter.addWidget(bottom_panel)
        main_v_splitter.setStretchFactor(0, 3)
        main_v_splitter.setStretchFactor(1, 1)

        main_layout.addWidget(main_v_splitter)

        # 状态栏
        self.statusBar().showMessage("就绪")

        # 快捷键提示
        self._append_log("提示: F6 开始执行 | F7 暂停/恢复 | F8 停止")

    # ==================== 窗口管理 ====================

    def _refresh_windows(self):
        """刷新窗口列表"""
        current_text = self.combo_windows.currentText()
        self.combo_windows.clear()
        windows = WindowManager.enumerate_windows()
        for w in windows:
            self.combo_windows.addItem(w.title, w.hwnd)
        # 尝试恢复之前的选择
        idx = self.combo_windows.findText(current_text)
        if idx >= 0:
            self.combo_windows.setCurrentIndex(idx)

    def _get_selected_hwnd(self) -> Optional[int]:
        """获取选中的窗口句柄"""
        idx = self.combo_windows.currentIndex()
        if idx < 0:
            return None
        return self.combo_windows.itemData(idx)

    # ==================== 步骤管理 ====================

    def _add_step(self):
        """添加一个步骤"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择模板图片", "", "图片文件 (*.png *.jpg *.bmp *.jpeg)"
        )
        if not file_path:
            return

        # 复制图片到 templates 目录
        filename = os.path.basename(file_path)
        dest_path = os.path.join(TEMPLATES_DIR, f"{int(time.time())}_{filename}")
        shutil.copy2(file_path, dest_path)

        step = StepConfig(
            id=self._next_step_id,
            image_path=dest_path,
            click_count=1,
            click_interval=0.3,
            match_threshold=0.8,
            multi_match=True,
            post_delay=1.0,
        )
        self._next_step_id += 1
        self._steps.append(step)
        self._step_images[step.id] = dest_path

        # 添加到列表
        item = QListWidgetItem(f"步骤{step.id}: {filename}")
        item.setData(Qt.UserRole, step.id)
        # 设置缩略图
        pixmap = _qpixmap_from_path(dest_path, 40, 40)
        item.setIcon(QIcon(pixmap))
        self.step_list.addItem(item)
        self.step_list.setCurrentRow(self.step_list.count() - 1)

        self._append_log(f"添加步骤{step.id}: {filename}")

    def _remove_step(self):
        """删除选中的步骤"""
        row = self.step_list.currentRow()
        if row < 0:
            return
        item = self.step_list.takeItem(row)
        step_id = item.data(Qt.UserRole)
        self._steps = [s for s in self._steps if s.id != step_id]
        self._step_images.pop(step_id, None)
        self._append_log(f"删除步骤{step_id}")

    def _move_step(self, direction: int):
        """移动步骤，direction: -1上移, +1下移"""
        row = self.step_list.currentRow()
        if row < 0:
            return
        new_row = row + direction
        if new_row < 0 or new_row >= self.step_list.count():
            return
        item = self.step_list.takeItem(row)
        self.step_list.insertItem(new_row, item)
        self.step_list.setCurrentRow(new_row)
        # 同步 _steps 列表顺序
        self._sync_steps_order()

    def _sync_steps_order(self):
        """同步步骤列表顺序与UI显示一致"""
        ordered = []
        for i in range(self.step_list.count()):
            item = self.step_list.item(i)
            step_id = item.data(Qt.UserRole)
            for s in self._steps:
                if s.id == step_id:
                    ordered.append(s)
                    break
        self._steps = ordered

    def _on_step_selected(self, row: int):
        """选中步骤时，加载参数到编辑区"""
        if row < 0:
            self._selected_step_id = None
            return
        # 通过UserRole获取step_id，而非直接用row索引
        item = self.step_list.item(row)
        if item is None:
            return
        step_id = item.data(Qt.UserRole)
        step = next((s for s in self._steps if s.id == step_id), None)
        if step is None:
            return

        self._selected_step_id = step.id

        # 临时断开信号，避免设置值时触发 _apply_step_params 导致参数互相覆盖
        self.spin_click_count.valueChanged.disconnect(self._apply_step_params)
        self.spin_click_interval.valueChanged.disconnect(self._apply_step_params)
        self.spin_threshold.valueChanged.disconnect(self._apply_step_params)
        self.combo_multi_match.currentIndexChanged.disconnect(self._apply_step_params)
        self.spin_post_delay.valueChanged.disconnect(self._apply_step_params)

        self.spin_click_count.setValue(step.click_count)
        self.spin_click_interval.setValue(step.click_interval)
        self.spin_threshold.setValue(step.match_threshold)
        self.combo_multi_match.setCurrentIndex(0 if step.multi_match else 1)
        self.spin_post_delay.setValue(step.post_delay)

        # 恢复信号连接
        self.spin_click_count.valueChanged.connect(self._apply_step_params)
        self.spin_click_interval.valueChanged.connect(self._apply_step_params)
        self.spin_threshold.valueChanged.connect(self._apply_step_params)
        self.combo_multi_match.currentIndexChanged.connect(self._apply_step_params)
        self.spin_post_delay.valueChanged.connect(self._apply_step_params)

        # 预览模板图片
        if step.image_path and os.path.exists(step.image_path):
            pixmap = _qpixmap_from_path(step.image_path, 400, 300)
            self.preview_label.setPixmap(pixmap)

    def _apply_step_params(self):
        """将编辑区的参数应用到选中的步骤"""
        if self._selected_step_id is None:
            return
        for step in self._steps:
            if step.id == self._selected_step_id:
                step.click_count = self.spin_click_count.value()
                step.click_interval = self.spin_click_interval.value()
                step.match_threshold = self.spin_threshold.value()
                step.multi_match = self.combo_multi_match.currentIndex() == 0
                step.post_delay = self.spin_post_delay.value()
                break

    # ==================== 预览 ====================

    def _do_preview(self):
        """预览匹配结果"""
        hwnd = self._get_selected_hwnd()
        if hwnd is None:
            QMessageBox.warning(self, "提示", "请先选择目标窗口")
            return

        if not self._steps:
            QMessageBox.warning(self, "提示", "请先添加步骤图片")
            return

        try:
            # 用第一个选中的步骤来预览
            row = self.step_list.currentRow()
            if row < 0:
                row = 0
            step = self._steps[row] if row < len(self._steps) else self._steps[0]

            annotated, matches = self._engine.preview_matches(
                hwnd, step.image_path, step.match_threshold, step.multi_match
            )

            if matches:
                self._append_log(f"找到 {len(matches)} 个匹配")
            else:
                self._append_log("未找到匹配")

            # 显示标注后的图像
            pixmap = cv2_to_qpixmap(annotated)
            scaled = pixmap.scaled(
                self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.preview_label.setPixmap(scaled)

        except Exception as e:
            QMessageBox.warning(self, "预览失败", str(e))

    # ==================== 执行控制 ====================

    def _build_script(self) -> Optional[ScriptConfig]:
        """根据当前UI配置构建脚本"""
        hwnd = self._get_selected_hwnd()
        if hwnd is None:
            QMessageBox.warning(self, "提示", "请先选择目标窗口")
            return None

        if not self._steps:
            QMessageBox.warning(self, "提示", "请先添加至少一个步骤")
            return None

        self._sync_steps_order()

        fail_map = {"跳过继续": "skip", "重试3次": "retry_3", "终止执行": "abort"}
        on_fail = fail_map.get(self.combo_on_fail.currentText(), "skip")

        group = ActionGroupConfig(
            loop_count=self.spin_loop_count.value(),
            loop_interval=self.spin_loop_interval.value(),
            on_fail=on_fail,
            completion_check=self.combo_completion_check.currentIndex() == 0,
            steps=list(self._steps),
        )

        idx = self.combo_windows.currentIndex()
        window_title = self.combo_windows.currentText()

        script = ScriptConfig(
            name="临时脚本",
            target_window_title=window_title,
            action_group=group,
        )
        return script

    def _start_execution(self):
        """开始执行"""
        script = self._build_script()
        if script is None:
            return

        hwnd = self._get_selected_hwnd()
        self._engine = ExecutionEngine()
        self._exec_thread = ExecutionThread(self._engine, script, hwnd)
        self._exec_thread.log_signal.connect(self._append_log)
        self._exec_thread.finished_signal.connect(self._on_execution_finished)
        self._exec_thread.round_signal.connect(
            lambda r, t: self.statusBar().showMessage(f"执行中 - 第 {r}/{t} 轮")
        )

        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_stop.setEnabled(True)

        self._append_log("=== 开始执行 ===")
        self._exec_thread.start()

    def _pause_execution(self):
        """暂停/恢复执行"""
        if self._engine.paused:
            self._engine.resume()
            self.btn_pause.setText("⏸ 暂停")
            self._append_log("已恢复执行")
        else:
            self._engine.pause()
            self.btn_pause.setText("▶ 恢复")
            self._append_log("已暂停")

    def _stop_execution(self):
        """停止执行"""
        self._engine.stop()
        self._append_log("正在停止...")

    def _on_execution_finished(self, success: bool):
        """执行完成回调"""
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.btn_pause.setText("⏸ 暂停")
        self.statusBar().showMessage("就绪")
        self._append_log("执行已结束")

    # ==================== 脚本管理 ====================

    def _refresh_scripts(self):
        """刷新脚本列表"""
        self.combo_scripts.clear()
        scripts = self._script_manager.list_scripts()
        for name in scripts:
            self.combo_scripts.addItem(name)

    def _save_script(self):
        """保存当前配置为脚本"""
        script = self._build_script()
        if script is None:
            return

        name, ok = QInputDialog.getText(
            self, "保存脚本", "脚本名称:", text=f"脚本{len(self._script_manager.list_scripts()) + 1}"
        )
        if not ok or not name.strip():
            return

        script.name = name.strip()
        self._script_manager.save_script(script)
        self._refresh_scripts()
        self._append_log(f"脚本 '{name}' 已保存")

    def _load_script(self):
        """加载选中的脚本"""
        name = self.combo_scripts.currentText()
        if not name:
            return

        script = self._script_manager.load_script(name)
        if script is None:
            QMessageBox.warning(self, "提示", f"无法加载脚本 '{name}'")
            return

        # 恢复窗口选择
        idx = self.combo_windows.findText(script.target_window_title)
        if idx >= 0:
            self.combo_windows.setCurrentIndex(idx)

        # 恢复动作组参数
        group = script.action_group
        self.spin_loop_count.setValue(group.loop_count)
        self.spin_loop_interval.setValue(group.loop_interval)
        fail_map = {"skip": 0, "retry_3": 1, "abort": 2}
        self.combo_on_fail.setCurrentIndex(fail_map.get(group.on_fail, 0))
        self.combo_completion_check.setCurrentIndex(0 if group.completion_check else 1)

        # 恢复步骤列表
        self._steps.clear()
        self._step_images.clear()
        self.step_list.clear()
        self._next_step_id = 1

        for step in group.steps:
            if not os.path.exists(step.image_path):
                self._append_log(f"警告: 模板图片不存在 {step.image_path}")
                continue
            self._steps.append(step)
            self._step_images[step.id] = step.image_path
            self._next_step_id = max(self._next_step_id, step.id + 1)

            filename = os.path.basename(step.image_path)
            item = QListWidgetItem(f"步骤{step.id}: {filename}")
            item.setData(Qt.UserRole, step.id)
            pixmap = _qpixmap_from_path(step.image_path, 40, 40)
            item.setIcon(QIcon(pixmap))
            self.step_list.addItem(item)

        self._append_log(f"脚本 '{name}' 已加载")

    def _delete_script(self):
        """删除选中的脚本"""
        name = self.combo_scripts.currentText()
        if not name:
            return
        reply = QMessageBox.question(self, "确认删除", f"确定要删除脚本 '{name}' 吗？")
        if reply == QMessageBox.Yes:
            self._script_manager.delete_script(name)
            self._refresh_scripts()
            self._append_log(f"脚本 '{name}' 已删除")

    def _rename_script(self):
        """重命名选中的脚本"""
        old_name = self.combo_scripts.currentText()
        if not old_name:
            return
        new_name, ok = QInputDialog.getText(self, "重命名脚本", "新名称:", text=old_name)
        if not ok or not new_name.strip():
            return
        if self._script_manager.rename_script(old_name, new_name.strip()):
            self._refresh_scripts()
            self._append_log(f"脚本 '{old_name}' 重命名为 '{new_name}'")
        else:
            QMessageBox.warning(self, "提示", "重命名失败")

    # ==================== 日志 ====================

    def _append_log(self, msg: str):
        """添加日志"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {msg}")
        # 自动滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ==================== 键盘事件 ====================

    def keyPressEvent(self, event):
        """快捷键处理"""
        if event.key() == Qt.Key_F6:
            self._start_execution()
        elif event.key() == Qt.Key_F7:
            self._pause_execution()
        elif event.key() == Qt.Key_F8:
            self._stop_execution()
        else:
            super().keyPressEvent(event)

    # ==================== 窗口关闭 ====================

    def closeEvent(self, event):
        """关闭窗口时停止执行"""
        if self._engine.running:
            self._engine.stop()
            if self._exec_thread and self._exec_thread.isRunning():
                self._exec_thread.wait(2000)
        self._timer.stop()
        event.accept()
