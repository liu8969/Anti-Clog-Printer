"""配置持久化管理模块"""

import copy
import json
import os

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
        "test_mode": False,  # True=省墨测试模式（只打印一条细色带）
        "test_rotate": False,  # True=测试页预先旋转90°（补偿打印机竖排处理）
    },
}


class ConfigManager:
    """管理 JSON 配置文件读写，支持点号路径访问"""

    def __init__(self, config_path=None):
        if config_path is None:
            # 可用环境变量 CONFIG_PATH 指定配置位置（如 Docker 挂载卷）
            config_path = os.environ.get("CONFIG_PATH") or os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "config.json"
            )
        self._config_path = config_path
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
            except (json.JSONDecodeError, OSError):
                pass
        return copy.deepcopy(DEFAULT_CONFIG)

    @staticmethod
    def _deep_merge(base, override):
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                ConfigManager._deep_merge(base[key], value)
            else:
                base[key] = value

    def save(self):
        try:
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"保存配置失败: {e}")

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
        """点号路径设值，自动保存"""
        keys = key.split(".")
        target = self._config
        for k in keys[:-1]:
            if k not in target:
                target[k] = {}
            target = target[k]
        target[keys[-1]] = value
        self.save()

    @property
    def ipp_uri(self):
        ip = self.get("printer.ip", "")
        if not ip:
            return ""
        port = self.get("printer.port", 631)
        path = self.get("printer.ipp_path", "/ipp/print")
        return f"ipp://{ip}:{port}{path}"
