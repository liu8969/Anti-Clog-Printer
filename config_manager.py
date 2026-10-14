"""配置持久化管理模块"""

import copy
import json
import os
import threading
from datetime import datetime

DEFAULT_CONFIG = {
    "printer": {
        "ip": "",
        "port": 631,
        "ipp_path": "/ipp/print",
    },
    "schedule": {
        "frequency": "daily",  # daily / every_2 / every_3 / every_5 / every_7
        "hour": 9,
        "minute": 0,
        "enabled": False,
    },
    "content": {
        "custom_text": "",
        # 图案：None=自动（新版默认 coverage 全喷嘴斜线覆盖页；
        #       若同时有旧的 test_mode=True 则仍是 link_test，行为不突变）
        #       coverage=全喷嘴斜线覆盖页 | classic=经典彩色页 | link_test=细色带自检
        "pattern": None,
        # 覆盖强度（coverage 图案）：每个喷孔每趟走纸连续吐的点数
        #   eco≈4点(省墨) / standard≈8点(默认) / strong≈16点(已轻微堵塞时用)
        "duty": "standard",
        "k_boost": True,   # 黑墨加强（颜料黑最易堵：K 斜线幕与竖条都加倍）
        "bars": True,      # 每个色块加一条满高实心竖条
        "ruler": True,     # 左侧毫米标尺（缺口位置定位用）
        "dpi": 300,        # 200 | 300（300 与打印机 URF RS300 一致，线条最锐利）
        "test_mode": False,  # 旧开关：True=只打印一条细色带（仅验证打印链路，不防堵）
        "test_rotate": False,  # True=测试页预先旋转90°（补偿打印机竖排处理）
    },
}


class ConfigManager:
    """管理 JSON 配置文件读写，支持点号路径访问。

    线程安全：set/save 持有 RLock；落盘使用"临时文件 + os.replace"原子写，
    避免写一半断电/崩溃导致 JSON 损坏。
    """

    def __init__(self, config_path=None):
        if config_path is None:
            # 可用环境变量 CONFIG_PATH 指定配置位置（如 Docker 挂载卷）
            config_path = os.environ.get("CONFIG_PATH") or os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "config.json"
            )
        self._config_path = config_path
        self._lock = threading.RLock()
        self._config = self._load()

    @property
    def config_path(self):
        """当前配置文件路径"""
        return self._config_path

    def _load(self):
        if os.path.exists(self._config_path):
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                # 深拷贝，避免污染模块级 DEFAULT_CONFIG
                merged = copy.deepcopy(DEFAULT_CONFIG)
                self._deep_merge(merged, saved)
                return merged
            except (json.JSONDecodeError, OSError) as e:
                self._backup_corrupt(e)
        return copy.deepcopy(DEFAULT_CONFIG)

    def _backup_corrupt(self, err):
        """配置文件损坏：把坏文件改名备份并给出醒目告警（静默丢失配置是最危险的）。

        典型场景：写一半断电 → JSON 损坏 → 若静默回退默认值，
        打印 IP 与计划会悄悄丢失，24x7 防堵在重启后静默失效。
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = f"{self._config_path}.corrupt_{ts}"
        try:
            os.replace(self._config_path, backup)
            print(
                f"⚠️ 警告: 配置文件 {self._config_path} 已损坏（{err}）。\n"
                f"   已备份到 {backup}，当前使用默认配置。\n"
                f"   请检查打印机 IP 与打印计划是否需要从备份恢复！",
                flush=True,
            )
        except OSError:
            print(
                f"⚠️ 警告: 配置文件 {self._config_path} 已损坏（{err}），"
                f"无法备份，当前使用默认配置。请人工检查！",
                flush=True,
            )

    @staticmethod
    def _deep_merge(base, override):
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                ConfigManager._deep_merge(base[key], value)
            else:
                base[key] = value

    def save(self):
        with self._lock:
            self._save_locked()

    def _save_locked(self):
        """原子写入：先写临时文件再 os.replace。调用方需已持有 self._lock。"""
        directory = os.path.dirname(os.path.abspath(self._config_path))
        tmp = self._config_path + ".tmp"
        try:
            os.makedirs(directory, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._config_path)
        except OSError as e:
            print(f"保存配置失败: {e}", flush=True)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass

    def get(self, key, default=None):
        """点号路径取值, 如 config.get('printer.ip')"""
        keys = key.split(".")
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default

    def set(self, key, value):
        """点号路径设值，自动保存（线程安全）"""
        keys = key.split(".")
        with self._lock:
            target = self._config
            for k in keys[:-1]:
                if k not in target:
                    target[k] = {}
                target = target[k]
            target[keys[-1]] = value
            self._save_locked()

    @property
    def ipp_uri(self):
        ip = self.get("printer.ip", "")
        if not ip:
            return ""
        port = self.get("printer.port", 631)
        path = self.get("printer.ipp_path", "/ipp/print")
        return f"ipp://{ip}:{port}{path}"
