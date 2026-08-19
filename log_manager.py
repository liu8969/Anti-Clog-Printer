"""打印日志管理模块"""

import json
import os
from datetime import datetime


class LogManager:
    """管理打印日志的 JSON 文件存储与查询"""

    MAX_LOGS = 500

    def __init__(self, log_path=None):
        if log_path is None:
            # 可用环境变量 LOG_PATH 指定日志位置（如 Docker 挂载卷）
            log_path = os.environ.get("LOG_PATH") or os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "print_log.json"
            )
        self._log_path = log_path
        self._logs = self._load()

    def _load(self):
        if os.path.exists(self._log_path):
            try:
                with open(self._log_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return []

    def _save(self):
        try:
            with open(self._log_path, "w", encoding="utf-8") as f:
                json.dump(self._logs, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"保存日志失败: {e}")

    def add(self, success, message, file_path=""):
        """添加一条打印日志"""
        entry = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "success": success,
            "message": message,
            "file_path": file_path,
        }
        self._logs.append(entry)

        # 保留最近 N 条
        if len(self._logs) > self.MAX_LOGS:
            self._logs = self._logs[-self.MAX_LOGS:]

        self._save()
        return entry

    def get_logs(self, limit=100):
        """获取最近 N 条日志（倒序，最新的在前）"""
        return list(reversed(self._logs[-limit:]))

    def clear(self):
        """清空所有日志"""
        self._logs = []
        self._save()

    def count(self):
        return len(self._logs)
