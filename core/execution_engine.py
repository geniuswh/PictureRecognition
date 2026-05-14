"""执行引擎：根据脚本配置执行图像识别和自动点击"""

import os
import time
from typing import Optional, Callable
import cv2
import numpy as np

from .window_manager import WindowManager
from .image_matcher import ImageMatcher, MatchResult
from .auto_clicker import AutoClicker
from .script_manager import ScriptConfig, StepConfig, ActionGroupConfig

import sys

# 调试截图保存目录
if getattr(sys, 'frozen', False):
    DEBUG_DIR = os.path.join(os.path.dirname(sys.executable), '_internal', 'debug_screenshots')
else:
    DEBUG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "debug_screenshots")


def _imread_chinese(path: str):
    """读取图片，支持中文路径（cv2.imread不支持中文路径）"""
    try:
        data = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        return img
    except Exception:
        return None


class ExecutionEngine:
    """脚本执行引擎"""

    # 日志目录
    if getattr(sys, 'frozen', False):
        LOG_DIR = os.path.join(os.path.dirname(sys.executable), '_internal', 'logs')
    else:
        LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")

    def __init__(self):
        self._running = False
        self._paused = False
        self._clicker = AutoClicker()
        self._on_log: Optional[Callable[[str], None]] = None
        self._on_step_start: Optional[Callable[[int, int], None]] = None  # step_id, round
        self._on_match_found: Optional[Callable[[int, list], None]] = None  # step_id, matches
        self._on_click: Optional[Callable[[int, int, int], None]] = None  # step_id, x, y
        self._on_round_start: Optional[Callable[[int, int], None]] = None  # round, total
        self._log_file = None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    def set_callbacks(
        self,
        on_log: Optional[Callable[[str], None]] = None,
        on_step_start: Optional[Callable[[int, int], None]] = None,
        on_match_found: Optional[Callable[[int, list], None]] = None,
        on_click: Optional[Callable[[int, int, int], None]] = None,
        on_round_start: Optional[Callable[[int, int], None]] = None,
    ):
        self._on_log = on_log
        self._on_step_start = on_step_start
        self._on_match_found = on_match_found
        self._on_click = on_click
        self._on_round_start = on_round_start

    def log(self, msg: str):
        timestamp = time.strftime("%H:%M:%S")
        full_msg = f"[{timestamp}] {msg}"
        if self._on_log:
            self._on_log(msg)
        # 写入日志文件（非阻塞，减少IO等待）
        try:
            if self._log_file is not None:
                self._log_file.write(full_msg + "\n")
                # 不每次flush，减少IO等待，在execute结束时统一flush
        except Exception:
            pass

    def stop(self):
        self._running = False
        self._paused = False
        self._clicker.stop()

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def _wait_if_paused(self):
        """等待暂停恢复"""
        while self._paused and self._running:
            time.sleep(0.1)

    def execute(self, script: ScriptConfig, hwnd: int) -> bool:
        """
        执行脚本

        Args:
            script: 脚本配置
            hwnd: 目标窗口句柄

        Returns:
            是否成功完成
        """
        self._running = True
        self._paused = False
        self._step1_clicked = set()  # 步骤1（抢）点击过的坐标，格式: (x, y)
        self._opened_positions = set()  # 已完成全流程（抢+开）的步骤1坐标
        self._supplemented_positions = set()  # 补漏已尝试过的坐标，避免重复补漏

        # 每次执行创建独立的日志文件
        try:
            os.makedirs(self.LOG_DIR, exist_ok=True)
            log_filename = time.strftime("execution_%Y%m%d_%H%M%S.log")
            log_path = os.path.join(self.LOG_DIR, log_filename)
            self._log_file = open(log_path, "w", encoding="utf-8")
            self.log(f"日志文件: {log_path}")
        except Exception as e:
            self._log_file = None

        group = script.action_group
        total_rounds = group.loop_count
        start_time = time.time()

        try:
            for round_idx in range(total_rounds):
                if not self._running:
                    self.log("执行已停止")
                    return False

                self._wait_if_paused()

                self.log(f"=== 第 {round_idx + 1}/{total_rounds} 轮 ===")
                if self._on_round_start:
                    self._on_round_start(round_idx + 1, total_rounds)

                round_success = self._execute_round(group, hwnd, round_idx)

                if not round_success and group.on_fail == "abort":
                    self.log("遇到失败，终止执行")
                    return False

                # 轮次间隔
                if round_idx < total_rounds - 1 and self._running:
                    time.sleep(group.loop_interval)

            # 完成度检查：主循环结束后，检测是否还有步骤1的遗漏目标
            if group.completion_check and group.steps and self._running:
                self._completion_check(group, hwnd)

            self.log("脚本执行完成")
            elapsed = time.time() - start_time
            self.log(f"总耗时: {elapsed:.2f}秒")
            return True

        finally:
            self._running = False
            if self._log_file:
                try:
                    self._log_file.close()
                except Exception:
                    pass
                self._log_file = None

    def _execute_round(self, group: ActionGroupConfig, hwnd: int, round_idx: int) -> bool:
        """执行一轮动作组"""
        self._step1_did_click = False  # 每轮开始时重置
        self._current_step1_pos = None  # 本轮步骤1点击的坐标
        prev_step = None
        prev_click_pos = None
        for step in group.steps:
            if not self._running:
                return False

            self._wait_if_paused()

            if self._on_step_start:
                self._on_step_start(step.id, round_idx + 1)

            success = self._execute_step(step, hwnd, prev_step=prev_step, prev_click_pos=prev_click_pos)

            if not success:
                if group.on_fail == "skip":
                    self.log(f"步骤{step.id}未匹配，跳过")
                elif group.on_fail.startswith("retry_"):
                    retry_times = int(group.on_fail.split("_")[1])
                    retried = False
                    for r in range(retry_times):
                        self.log(f"步骤{step.id}重试 {r + 1}/{retry_times}")
                        time.sleep(0.5)
                        success = self._execute_step(step, hwnd, prev_step=prev_step, prev_click_pos=prev_click_pos)
                        if success:
                            retried = True
                            break
                    if not retried:
                        self.log(f"步骤{step.id}重试{retry_times}次仍失败")
                        if group.on_fail == "abort":
                            return False
                elif group.on_fail == "abort":
                    self.log(f"步骤{step.id}未匹配，终止执行")
                    return False

            # 步骤1点击成功后，记录坐标供后续步骤使用，短暂等待弹窗渲染
            if step.id == group.steps[0].id and self._step1_did_click:
                self._current_step1_pos = getattr(self, '_last_click_pos', None)
                time.sleep(0.05)  # 弹窗开始渲染，步骤2会有重试兜底

            # 步骤2成功后，短暂等待弹窗关闭动画
            if step.id != group.steps[0].id and success:
                time.sleep(0.1)  # 等弹窗关闭动画（JS中400ms，但只要overlay消失即可）
                if self._current_step1_pos:
                    self._opened_positions.add(self._current_step1_pos)
                    self.log(f"标记步骤1坐标{self._current_step1_pos}已完成全流程")

            # 步骤2失败时，移除步骤1的点击记录，让补漏时可以重新完整执行
            if step.id != group.steps[0].id and not success and self._current_step1_pos:
                self._remove_clicked_position(self._current_step1_pos[0], self._current_step1_pos[1])
                self.log(f"步骤2失败，移除步骤1坐标{self._current_step1_pos}的点击记录，等待补漏")

            # 获取本步骤最后点击坐标，供下一步骤做消失检测
            prev_click_pos = getattr(self, '_last_click_pos', None)
            prev_step = step

            # 步骤1（首个步骤）如果没有实际产生点击，跳过本轮后续步骤
            if step.id == group.steps[0].id and not self._step1_did_click:
                self.log(f"步骤1未产生新点击，跳过本轮后续步骤")
                return True

        return True

    def _is_position_clicked(self, x: int, y: int, step_id: int) -> bool:
        """检查某个坐标是否已被步骤1点击过（容差20像素）"""
        if step_id != 1:
            return False
        for (cx, cy) in self._step1_clicked:
            if abs(cx - x) <= 20 and abs(cy - y) <= 20:
                return True
        return False

    def _is_position_opened(self, x: int, y: int) -> bool:
        """检查某个步骤1坐标对应的红包是否已经点过"开"了（容差20像素匹配）"""
        for (ox, oy) in self._opened_positions:
            if abs(ox - x) <= 20 and abs(oy - y) <= 20:
                return True
        return False

    def _record_clicked_position(self, x: int, y: int, step_id: int):
        """记录步骤1点击过的坐标"""
        if step_id == 1:
            self._step1_clicked.add((x, y))

    def _remove_clicked_position(self, x: int, y: int):
        """移除步骤1的点击记录（容差20像素），让该位置可以重新被点击"""
        to_remove = None
        for (cx, cy) in self._step1_clicked:
            if abs(cx - x) <= 20 and abs(cy - y) <= 20:
                to_remove = (cx, cy)
                break
        if to_remove:
            self._step1_clicked.discard(to_remove)

    def _execute_step(self, step: StepConfig, hwnd: int, prev_step: Optional[StepConfig] = None,
                      prev_click_pos: Optional[tuple] = None) -> bool:
        """执行单个步骤，返回是否匹配成功
        
        步骤1（无prev_step）：始终做多匹配，使用点击记录过滤已点击过的位置。
        后续步骤（有prev_step）：匹配失败时持续轮询，同时检测上一步骤点击坐标处的模板是否消失，
        若消失则停止等待返回False。
        
        Args:
            prev_click_pos: 上一步骤点击的坐标 (x, y)，用于精确检测该位置的目标是否消失
        """
        template = _imread_chinese(step.image_path)
        if template is None:
            self.log(f"无法读取模板图片: {step.image_path}")
            return False

        # 加载上一步骤的模板用于消失检测
        prev_template = None
        if prev_step is not None:
            prev_template = _imread_chinese(prev_step.image_path)

        # ========== 阶段1：找到目标 ==========
        step2_retry = 0  # 步骤2重试点击步骤1的次数
        while self._running:
            self._wait_if_paused()

            try:
                screenshot = WindowManager.capture_window(hwnd)
            except Exception as e:
                self.log(f"截图失败: {e}")
                return False

            # 步骤1：始终做多匹配，然后过滤已点击的，但每轮只点一个
            if prev_step is None:
                matches = ImageMatcher.match_template(
                    screenshot,
                    template,
                    threshold=step.match_threshold,
                    multi_match=True,  # 始终多匹配
                )
                if matches:
                    # 过滤：只保留没点过步骤1的
                    unclicked = [m for m in matches if not self._is_position_clicked(m.center[0], m.center[1], step.id)]
                    if unclicked:
                        # 每轮只取第一个未点击的目标，其余留给后续轮次处理
                        self.log(f"步骤{step.id}: 找到{len(matches)}个匹配，{len(unclicked)}个未点击，本轮处理1个")
                        matches = [unclicked[0]]
                        self._step1_did_click = True  # 标记步骤1本轮将产生点击
                        break
                    # 所有匹配都已点过，跳过本轮
                    self.log(f"步骤{step.id}: 找到{len(matches)}个匹配，均已点击过，跳过")
                    return True
                # 没有匹配，没有红包可点
                self.log(f"步骤{step.id}: 未找到匹配")
                return True  # 不算失败，只是没有目标了
            else:
                # 步骤2：在弹窗区域搜索"开"字，先搜索弹窗中心区域（更快速）
                h, w = screenshot.shape[:2]
                # 弹窗在屏幕中央，大约占窗口60%的区域
                margin_x = w // 5
                margin_y = h // 5
                roi = screenshot[margin_y:h-margin_y, margin_x:w-margin_x]
                
                roi_matches = ImageMatcher.match_template(
                    roi,
                    template,
                    threshold=step.match_threshold,
                    multi_match=False,
                )
                
                # ROI匹配结果的坐标需要加上偏移
                if roi_matches:
                    for m in roi_matches:
                        m.x += margin_x
                        m.y += margin_y
                    matches = roi_matches
                else:
                    # ROI没找到，全屏搜索
                    matches = ImageMatcher.match_template(
                        screenshot,
                        template,
                        threshold=step.match_threshold,
                        multi_match=False,
                    )

            if matches:
                break

            # 步骤2找不到目标时的重试逻辑
            if prev_step is not None and prev_click_pos is not None:
                step2_retry += 1
                if step2_retry == 1:
                    # 第1次没找到，可能弹窗还在渲染，等一下再试
                    time.sleep(0.05)
                    continue
                elif step2_retry <= 4:
                    # 等一下还是没找到，重试点击步骤1位置触发弹窗
                    self.log(f"步骤{step.id}: 未匹配到目标，重新点击步骤1位置({prev_click_pos[0]},{prev_click_pos[1]})触发弹窗（第{step2_retry - 1}次）")
                    AutoClicker.click_position(hwnd, prev_click_pos[0], prev_click_pos[1])
                    time.sleep(0.08)
                    continue
                else:
                    # 重试3次后，再检测上一步骤目标是否真的消失了
                    if prev_template is not None and prev_click_pos is not None:
                        px, py = prev_click_pos
                        th, tw = prev_template.shape[:2]
                        h, w = screenshot.shape[:2]
                        y1 = max(0, py - th)
                        y2 = min(h, py + th)
                        x1 = max(0, px - tw)
                        x2 = min(w, px + tw)
                        roi = screenshot[y1:y2, x1:x2]
                        if roi.size > 0:
                            local_matches = ImageMatcher.match_template(
                                roi, prev_template,
                                threshold=prev_step.match_threshold,
                                multi_match=False,
                            )
                            if not local_matches:
                                self.log(f"步骤{step.id}: 上一步骤点击位置目标已消失，停止等待")
                                self._save_debug_screenshot(screenshot, template, step.id)
                                return False
                    self.log(f"步骤{step.id}: 重试3次后仍未匹配，停止等待")
                    self._save_debug_screenshot(screenshot, template, step.id)
                    return False

        else:
            return False

        # ========== 阶段2：点击匹配目标 ==========
        self.log(f"步骤{step.id}: 找到 {len(matches)} 个匹配")
        if self._on_match_found:
            self._on_match_found(step.id, matches)

        last_click_pos = None
        for i, match in enumerate(matches):
            if not self._running:
                return False

            self._wait_if_paused()

            cx, cy = match.center
            cx, cy = int(cx), int(cy)
            last_click_pos = (cx, cy)
            self.log(f"步骤{step.id}: 点击第{i + 1}个匹配 ({cx}, {cy}) 置信度={match.confidence:.2f}")

            # 记录步骤1的点击位置
            self._record_clicked_position(cx, cy, step.id)

            if self._on_click:
                self._on_click(step.id, cx, cy)

            for click_idx in range(step.click_count):
                AutoClicker.click_position(hwnd, cx, cy)
                if click_idx < step.click_count - 1:
                    time.sleep(0.05)

            if i < len(matches) - 1:
                time.sleep(step.click_interval)

        # 保存本步骤最后点击的坐标，供下一步骤做消失检测
        self._last_click_pos = last_click_pos

        # 步骤执行后等待
        if step.post_delay > 0:
            time.sleep(step.post_delay)

        return True

    def preview_matches(
        self, hwnd: int, image_path: str, threshold: float = 0.8, multi_match: bool = True
    ) -> tuple:
        """
        预览匹配结果（不执行点击）

        Returns:
            (annotated_image_bgr, matches_list)
        """
        screenshot = WindowManager.capture_window(hwnd)
        template = _imread_chinese(image_path)

        if template is None:
            return screenshot, []

        matches = ImageMatcher.match_template(
            screenshot, template, threshold=threshold, multi_match=multi_match
        )

        annotated = ImageMatcher.draw_matches(screenshot, matches)
        return annotated, matches

    def _save_debug_screenshot(self, screenshot: np.ndarray, template: np.ndarray, step_id: int):
        """保存调试截图到debug_screenshots目录"""
        try:
            os.makedirs(DEBUG_DIR, exist_ok=True)
            timestamp = time.strftime("%H%M%S")
            # 保存截图
            shot_path = os.path.join(DEBUG_DIR, f"step{step_id}_{timestamp}_screenshot.png")
            cv2.imencode('.png', screenshot)[1].tofile(shot_path)
            # 保存模板
            tmpl_path = os.path.join(DEBUG_DIR, f"step{step_id}_{timestamp}_template.png")
            cv2.imencode('.png', template)[1].tofile(tmpl_path)
            self.log(f"调试截图已保存: {shot_path}")
        except Exception as e:
            self.log(f"保存调试截图失败: {e}")

    def _wait_popup_disappear(self, step: StepConfig, hwnd: int, step1_pos: tuple = None, step1_image: str = None, max_wait: float = 0.5):
        """步骤2点击后，轮询等待弹窗关闭并确认红包已被抢走。
        
        等待步骤1的目标（"抢"字）在点击位置消失，确认红包真正被抢走。
        使用短间隔轮询，一旦"抢"字消失立即继续，最大等待max_wait秒。
        """
        if step1_pos is None or step1_image is None:
            time.sleep(0.2)
            return

        step1_template = _imread_chinese(step1_image)
        if step1_template is None:
            time.sleep(0.2)
            return

        sx, sy = step1_pos
        th, tw = step1_template.shape[:2]
        start = time.time()
        while time.time() - start < max_wait:
            time.sleep(0.03)
            try:
                screenshot = WindowManager.capture_window(hwnd)
            except Exception:
                break
            h, w = screenshot.shape[:2]
            y1 = max(0, sy - th)
            y2 = min(h, sy + th)
            x1 = max(0, sx - tw)
            x2 = min(w, sx + tw)
            roi = screenshot[y1:y2, x1:x2]
            if roi.size == 0:
                return
            local_matches = ImageMatcher.match_template(
                roi, step1_template,
                threshold=0.8,
                multi_match=False,
            )
            if not local_matches:
                return
        # 超时也继续

    def _completion_check(self, group: ActionGroupConfig, hwnd: int):
        """完成度检查：页面上还有"抢"字就补漏。

        逻辑：
        1. 截图找屏幕上的"抢"字
        2. 过滤掉主循环已完成（抢+开都成功了）的和补漏已尝试过的
        3. 剩下的才是真正遗漏的目标
        4. 每次只处理1个遗漏目标，重新执行完整的抢→开流程
        """
        max_supplement_rounds = 10
        first_step = group.steps[0]

        template = _imread_chinese(first_step.image_path)
        if template is None:
            return

        for supplement_idx in range(max_supplement_rounds):
            if not self._running:
                return

            self._wait_if_paused()

            self.log(f"--- 完成度检查第 {supplement_idx + 1} 次 ---")

            # 截图找屏幕上还有的"抢"字
            try:
                screenshot = WindowManager.capture_window(hwnd)
            except Exception as e:
                self.log(f"截图失败: {e}")
                break

            matches = ImageMatcher.match_template(
                screenshot, template,
                threshold=first_step.match_threshold,
                multi_match=True,
            )

            if not matches:
                self.log("完成度检查通过，页面上无遗漏目标")
                break

            # 只过滤补漏已尝试过的，不再用_opened_positions过滤
            # 因为_opened_positions不可靠：步骤2返回True不代表红包真的抢到了
            # 页面上还有"抢"字就说明还没抢完
            unprocessed = []
            for m in matches:
                mx, my = int(m.center[0]), int(m.center[1])
                already = False
                for (sx, sy) in self._supplemented_positions:
                    if abs(sx - mx) <= 20 and abs(sy - my) <= 20:
                        already = True
                        break
                if already:
                    continue  # 补漏已尝试过
                unprocessed.append(m)

            if not unprocessed:
                supplemented_count = len(matches) - len(unprocessed)
                self.log(f"完成度检查通过，{len(matches)}个抢字可见，{supplemented_count}个已补漏尝试")
                break

            self.log(f"发现 {len(unprocessed)} 个遗漏目标，补漏1个")

            # 每次只处理1个，重新执行完整流程
            target = unprocessed[0]
            cx, cy = target.center
            cx, cy = int(cx), int(cy)

            self.log(f"补漏: 重新执行完整流程 ({cx}, {cy}) 置信度={target.confidence:.2f}")

            # 记录补漏尝试
            self._supplemented_positions.add((cx, cy))

            # 执行步骤1的点击
            self._record_clicked_position(cx, cy, first_step.id)
            for click_idx in range(first_step.click_count):
                AutoClicker.click_position(hwnd, cx, cy)
                if click_idx < first_step.click_count - 1:
                    time.sleep(0.03)
            if first_step.post_delay > 0:
                time.sleep(first_step.post_delay)
            else:
                time.sleep(0.06)  # 等弹窗渲染

            # 执行后续步骤
            prev = first_step
            prev_cpos = (cx, cy)
            for step in group.steps[1:]:
                if not self._running:
                    return
                self._wait_if_paused()
                success = self._execute_step(step, hwnd, prev_step=prev, prev_click_pos=prev_cpos)
                if not success and group.on_fail != "abort":
                    self.log(f"补漏: 步骤{step.id}未匹配，跳过")
                elif not success:
                    return
                # 步骤2成功，短暂等待弹窗关闭动画
                if success:
                    time.sleep(0.1)
                    self._opened_positions.add((cx, cy))
                    self.log(f"标记步骤1坐标({cx}, {cy})已完成全流程")
                if step.post_delay > 0:
                    time.sleep(step.post_delay)
                prev = step
                prev_cpos = getattr(self, '_last_click_pos', prev_cpos)
