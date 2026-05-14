"""脚本管理模块：脚本的增删改查、序列化"""

import json
import os
import time
from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field, asdict


import sys

# 脚本存储目录：打包后在_internal下，开发时在项目根目录下
if getattr(sys, 'frozen', False):
    SCRIPTS_DIR = os.path.join(os.path.dirname(sys.executable), '_internal', 'scripts')
    BASE_DIR = os.path.join(os.path.dirname(sys.executable), '_internal')
else:
    SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _to_relative(abs_path: str) -> str:
    """将绝对路径转为相对于 BASE_DIR 的相对路径"""
    try:
        return os.path.relpath(abs_path, BASE_DIR).replace("\\", "/")
    except ValueError:
        return abs_path


def _to_absolute(rel_path: str) -> str:
    """将相对路径转为绝对路径；如果已经是绝对路径则直接返回"""
    if os.path.isabs(rel_path):
        return rel_path
    return os.path.join(BASE_DIR, rel_path.replace("/", os.sep))


@dataclass
class StepConfig:
    """步骤配置"""
    id: int = 0
    image_path: str = ""          # 模板图片路径
    click_count: int = 1          # 每个匹配点点击次数
    click_interval: float = 0.3   # 多匹配点之间的点击间隔(秒)
    match_threshold: float = 0.8  # 匹配阈值
    multi_match: bool = True      # 是否匹配多个
    post_delay: float = 1.0       # 步骤执行后等待时间(秒)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["image_path"] = _to_relative(self.image_path)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StepConfig":
        if "image_path" in data:
            data["image_path"] = _to_absolute(data["image_path"])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ActionGroupConfig:
    """动作组配置"""
    loop_count: int = 1                 # 循环次数
    loop_interval: float = 0.5          # 轮次间隔(秒)
    on_fail: str = "skip"               # 失败策略: skip / retry_3 / abort
    completion_check: bool = True        # 完成度检查：主循环结束后，用步骤1的模板检测是否还有遗漏
    steps: List[StepConfig] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "loop_count": self.loop_count,
            "loop_interval": self.loop_interval,
            "on_fail": self.on_fail,
            "completion_check": self.completion_check,
            "steps": [s.to_dict() for s in self.steps],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ActionGroupConfig":
        steps = [StepConfig.from_dict(s) for s in data.get("steps", [])]
        return cls(
            loop_count=data.get("loop_count", 1),
            loop_interval=data.get("loop_interval", 0.5),
            on_fail=data.get("on_fail", "skip"),
            completion_check=data.get("completion_check", True),
            steps=steps,
        )


@dataclass
class ScriptConfig:
    """脚本配置"""
    name: str = "未命名脚本"
    target_window_title: str = ""      # 目标窗口标题
    target_window_class: str = ""      # 目标窗口类名
    action_group: ActionGroupConfig = field(default_factory=ActionGroupConfig)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "target_window_title": self.target_window_title,
            "target_window_class": self.target_window_class,
            "action_group": self.action_group.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScriptConfig":
        return cls(
            name=data.get("name", "未命名脚本"),
            target_window_title=data.get("target_window_title", ""),
            target_window_class=data.get("target_window_class", ""),
            action_group=ActionGroupConfig.from_dict(data.get("action_group", {})),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


class ScriptManager:
    """脚本管理器"""

    def __init__(self, scripts_dir: Optional[str] = None):
        self.scripts_dir = scripts_dir or SCRIPTS_DIR
        os.makedirs(self.scripts_dir, exist_ok=True)

    def list_scripts(self) -> List[str]:
        """列出所有已保存的脚本名称"""
        scripts = []
        if os.path.exists(self.scripts_dir):
            for f in os.listdir(self.scripts_dir):
                if f.endswith(".json"):
                    scripts.append(f[:-5])  # 去掉.json后缀
        return sorted(scripts)

    def save_script(self, script: ScriptConfig) -> str:
        """保存脚本，返回文件路径"""
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        if not script.created_at:
            script.created_at = now
        script.updated_at = now

        filepath = os.path.join(self.scripts_dir, f"{script.name}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(script.to_dict(), f, ensure_ascii=False, indent=2)
        return filepath

    def load_script(self, name: str) -> Optional[ScriptConfig]:
        """加载脚本"""
        filepath = os.path.join(self.scripts_dir, f"{name}.json")
        if not os.path.exists(filepath):
            return None
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ScriptConfig.from_dict(data)

    def delete_script(self, name: str) -> bool:
        """删除脚本"""
        filepath = os.path.join(self.scripts_dir, f"{name}.json")
        if os.path.exists(filepath):
            os.remove(filepath)
            return True
        return False

    def rename_script(self, old_name: str, new_name: str) -> bool:
        """重命名脚本"""
        old_path = os.path.join(self.scripts_dir, f"{old_name}.json")
        new_path = os.path.join(self.scripts_dir, f"{new_name}.json")
        if os.path.exists(old_path) and not os.path.exists(new_path):
            script = self.load_script(old_name)
            if script:
                script.name = new_name
                os.remove(old_path)
                self.save_script(script)
                return True
        return False
