"""图像匹配模块：基于OpenCV模板匹配"""

from typing import List, Tuple, Optional
import cv2
import numpy as np


class MatchResult:
    """匹配结果"""

    def __init__(self, x: int, y: int, w: int, h: int, confidence: float):
        self.x = x  # 匹配区域左上角x
        self.y = y  # 匹配区域左上角y
        self.w = w  # 模板宽度
        self.h = h  # 模板高度
        self.confidence = confidence  # 置信度

    @property
    def center(self) -> Tuple[int, int]:
        """匹配区域中心点"""
        return (self.x + self.w // 2, self.y + self.h // 2)

    def __repr__(self):
        return f"MatchResult(center={self.center}, confidence={self.confidence:.3f})"


class ImageMatcher:
    """图像模板匹配"""

    @staticmethod
    def _nms_iou(candidates: List[MatchResult], iou_threshold: float = 0.5) -> List[MatchResult]:
        """基于IoU的非极大值抑制

        IoU阈值越高，允许的重叠越多；阈值越低，抑制越严格。
        对于模板匹配，0.5是一个合理的值——两个匹配框重叠超过50%才算重复。
        """
        if not candidates:
            return []

        filtered = []
        for candidate in candidates:
            should_keep = True
            for existing in filtered:
                # 计算IoU
                x1 = max(candidate.x, existing.x)
                y1 = max(candidate.y, existing.y)
                x2 = min(candidate.x + candidate.w, existing.x + existing.w)
                y2 = min(candidate.y + candidate.h, existing.y + existing.h)

                intersection = max(0, x2 - x1) * max(0, y2 - y1)
                area1 = candidate.w * candidate.h
                area2 = existing.w * existing.h
                union = area1 + area2 - intersection

                if union > 0:
                    iou = intersection / union
                    if iou > iou_threshold:
                        should_keep = False
                        break

            if should_keep:
                filtered.append(candidate)

        return filtered

    @staticmethod
    def _match_template_single_scale(
        source_gray: np.ndarray,
        template_gray: np.ndarray,
        template_shape: Tuple[int, int],
        threshold: float,
        multi_match: bool,
    ) -> List[MatchResult]:
        """在单个尺度下执行模板匹配"""
        result = cv2.matchTemplate(source_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        matches = []
        tw, th = template_shape

        if not multi_match:
            if max_val >= threshold:
                matches.append(MatchResult(max_loc[0], max_loc[1], tw, th, float(max_val)))
        else:
            locations = np.where(result >= threshold)
            candidates = []
            for pt in zip(*locations[::-1]):
                confidence = result[pt[1], pt[0]]
                candidates.append(MatchResult(pt[0], pt[1], tw, th, float(confidence)))

            candidates.sort(key=lambda m: m.confidence, reverse=True)
            matches = ImageMatcher._nms_iou(candidates, iou_threshold=0.5)

        matches.sort(key=lambda m: (m.y, m.x))
        return matches

    @staticmethod
    def match_template(
        source: np.ndarray,
        template: np.ndarray,
        threshold: float = 0.8,
        multi_match: bool = True,
        min_distance: int = 10,
    ) -> List[MatchResult]:
        """
        在源图像中查找模板图像的所有匹配位置

        当原始尺度匹配失败时，自动尝试多尺度匹配（±30%），
        以应对不同DPI/缩放导致的模板与截图尺寸不一致问题。

        优化策略：先快速检测原始尺度最高置信度，
        仅当置信度在"接近但不达标"区间时才启动多尺度搜索。

        Args:
            source: 源图像(BGR格式)
            template: 模板图像(BGR格式)
            threshold: 匹配阈值(0~1)
            multi_match: 是否查找多个匹配
            min_distance: 多匹配时，两个匹配中心的最小像素距离（已弃用，保留兼容）

        Returns:
            匹配结果列表，按从左到右、从上到下排序
        """
        if source is None or template is None:
            return []

        if template.shape[0] > source.shape[0] or template.shape[1] > source.shape[1]:
            return []

        source_gray = cv2.cvtColor(source, cv2.COLOR_BGR2GRAY)
        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

        # 先尝试原始尺度匹配
        matches = ImageMatcher._match_template_single_scale(
            source_gray, template_gray,
            (template.shape[1], template.shape[0]),
            threshold, multi_match
        )

        if matches:
            return matches

        # 原始尺度未达标，快速检查最大置信度
        result = cv2.matchTemplate(source_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(result)

        # 如果最大置信度极低（<0.4），说明截图中根本不存在目标，无需多尺度
        if max_val < 0.4:
            return []

        # 置信度在 0.4~threshold 之间，可能是缩放导致的尺寸偏差，启动多尺度搜索
        # 优化：用1/3分辨率快速粗搜，再用1/2分辨率精搜
        # 1/3粗搜：极快，定位大致尺度
        third_source = cv2.resize(
            source_gray, (source_gray.shape[1] // 3, source_gray.shape[0] // 3),
            interpolation=cv2.INTER_AREA
        )
        coarse_scales = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]
        best_coarse_conf = 0
        best_coarse_scale = 1.0

        for scale in coarse_scales:
            new_w = int(template.shape[1] * scale // 3)
            new_h = int(template.shape[0] * scale // 3)
            if new_w <= 2 or new_h <= 2 or new_w > third_source.shape[1] or new_h > third_source.shape[0]:
                continue

            scaled_gray = cv2.resize(template_gray, (new_w, new_h), interpolation=cv2.INTER_AREA)
            r = cv2.matchTemplate(third_source, scaled_gray, cv2.TM_CCOEFF_NORMED)
            _, mv, _, _ = cv2.minMaxLoc(r)
            # 低分辨率匹配置信度略低，用0.93修正
            mv_adj = mv * 0.93
            if mv_adj > best_coarse_conf:
                best_coarse_conf = mv_adj
                best_coarse_scale = scale

        # 如果粗搜最佳仍低于阈值，放弃
        if best_coarse_conf < threshold:
            return []

        # 1/2分辨率精搜：在粗搜最佳尺度±0.08范围，步长0.02
        half_source = cv2.resize(
            source_gray, (source_gray.shape[1] // 2, source_gray.shape[0] // 2),
            interpolation=cv2.INTER_AREA
        )
        fine_scales = [round(s, 2) for s in np.arange(
            max(0.5, best_coarse_scale - 0.08),
            min(1.5, best_coarse_scale + 0.10),
            0.02
        )]

        best_fine_conf = 0
        best_fine_scale = best_coarse_scale

        for scale in fine_scales:
            new_w = int(template.shape[1] * scale // 2)
            new_h = int(template.shape[0] * scale // 2)
            if new_w <= 3 or new_h <= 3 or new_w > half_source.shape[1] or new_h > half_source.shape[0]:
                continue

            scaled_gray = cv2.resize(template_gray, (new_w, new_h), interpolation=cv2.INTER_AREA)
            r = cv2.matchTemplate(half_source, scaled_gray, cv2.TM_CCOEFF_NORMED)
            _, mv, _, _ = cv2.minMaxLoc(r)
            if mv > best_fine_conf:
                best_fine_conf = mv
                best_fine_scale = scale

        if best_fine_conf < threshold:
            return []

        # 用最佳精搜尺度在原始分辨率做一次完整匹配
        final_w = int(template.shape[1] * best_fine_scale)
        final_h = int(template.shape[0] * best_fine_scale)
        final_gray = cv2.resize(template_gray, (final_w, final_h), interpolation=cv2.INTER_AREA)

        return ImageMatcher._match_template_single_scale(
            source_gray, final_gray, (final_w, final_h),
            threshold, multi_match
        )

    @staticmethod
    def match_template_with_scales(
        source: np.ndarray,
        template: np.ndarray,
        threshold: float = 0.8,
        scales: Optional[List[float]] = None,
        multi_match: bool = True,
        min_distance: int = 10,
    ) -> List[MatchResult]:
        """
        多尺度模板匹配，适配不同DPI下的窗口截图

        Args:
            source: 源图像
            template: 模板图像
            threshold: 匹配阈值
            scales: 缩放比例列表，默认[0.8, 0.9, 1.0, 1.1, 1.2]
        """
        if scales is None:
            scales = [0.8, 0.9, 1.0, 1.1, 1.2]

        all_matches = []
        best_confidence = 0

        for scale in scales:
            if scale == 1.0:
                scaled_template = template
            else:
                new_w = int(template.shape[1] * scale)
                new_h = int(template.shape[0] * scale)
                if new_w <= 0 or new_h <= 0:
                    continue
                scaled_template = cv2.resize(template, (new_w, new_h), interpolation=cv2.INTER_AREA)

            matches = ImageMatcher.match_template(
                source, scaled_template, threshold, multi_match, min_distance
            )

            if matches:
                # 记录最佳置信度
                max_conf = max(m.confidence for m in matches)
                if max_conf > best_confidence:
                    best_confidence = max_conf
                    all_matches = matches

        return all_matches

    @staticmethod
    def draw_matches(
        source: np.ndarray, matches: List[MatchResult], color: Tuple[int, int, int] = (0, 0, 255)
    ) -> np.ndarray:
        """在源图像上绘制匹配结果（红框标注）"""
        img = source.copy()
        for m in matches:
            cv2.rectangle(img, (m.x, m.y), (m.x + m.w, m.y + m.h), color, 2)
            cv2.putText(
                img,
                f"{m.confidence:.2f}",
                (m.x, m.y - 5),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.4,
                color,
                1,
            )
        return img
