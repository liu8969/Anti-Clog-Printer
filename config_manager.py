"""配置持久化管理模块"""

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
    },
}


class ConfigManager:
    """管理 JSON 配置文件读写，支持点号路径访问"""

    def __init__(self, config_path=None):
        if config_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(base_dir, "config.json")
        self._config_path = config_path
        self._config = self._load()

    def _load(self):
        if os.path.exists(self._config_path):
            try:
                with open(self._config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                merged = DEFAULT_CONFIG.copy()
                self._deep_merge(merged, saved)
                return merged
            except (json.JSONDecodeError, OSError):
                pass
        return DEFAULT_CONFIG.copy()

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
