"""打印日志管理模块"""

import json
import os
import threading
from datetime import datetime


class LogManager:
    """管理打印日志的 JSON 文件存储与查询。

    线程安全：add/clear 持有 RLock（调度线程与手动打印可能并发写入）；
    落盘使用"临时文件 + os.replace"原子写，避免并发/断电写坏文件。
    每条日志带单调递增的 id，供 Web 表格做唯一 row_key（时间只有秒级精度，
    同秒多次打印会撞 key）。
    """

    MAX_LOGS = 500

    def __init__(self, log_path=None):
        if log_path is None:
            # 可用环境变量 LOG_PATH 指定日志位置（如 Docker 挂载卷）
            log_path = os.environ.get("LOG_PATH") or os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "print_log.json"
            )
        self._log_path = log_path
        self._lock = threading.RLock()
        self._logs, self._seq = self._load()

    def _load(self):
        logs = []
        if os.path.exists(self._log_path):
            try:
                with open(self._log_path, "r", encoding="utf-8") as f:
                    logs = json.load(f)
                if not isinstance(logs, list):
                    raise json.JSONDecodeError("日志文件不是数组", "", 0)
            except (json.JSONDecodeError, OSError, TypeError) as e:
                logs = self._backup_corrupt(logs, e)
        else:
            logs = []

        # 为旧日志（无 id 字段）补发唯一 id，并确定下一个序号
        seq = 0
        for entry in logs:
            if isinstance(entry, dict) and isinstance(entry.get("id"), int):
                seq = max(seq, entry["id"])
        for entry in logs:
            if isinstance(entry, dict) and not isinstance(entry.get("id"), int):
                seq += 1
                entry["id"] = seq
        # 丢弃意外混入的非 dict 元素
        logs = [e for e in logs if isinstance(e, dict)]
        return logs, seq

    def _backup_corrupt(self, parsed, err):
        """日志文件损坏：备份坏文件并告警，返回可保留的条目（通常是空列表）。"""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = f"{self._log_path}.corrupt_{ts}"
        try:
            os.replace(self._log_path, backup)
            print(
                f"⚠️ 警告: 日志文件 {self._log_path} 已损坏（{err}），"
                f"已备份到 {backup}，历史日志将丢失。",
                flush=True,
            )
        except OSError:
            print(
                f"⚠️ 警告: 日志文件 {self._log_path} 已损坏（{err}），无法备份。",
                flush=True,
            )
        # 若只是 JSON 结构异常但能解析成列表，尽量保留
        if isinstance(parsed, list):
            return parsed
        return []

    def _save_locked(self):
        """原子写入。调用方需已持有 self._lock。"""
        directory = os.path.dirname(os.path.abspath(self._log_path))
        tmp = self._log_path + ".tmp"
        try:
            os.makedirs(directory, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._logs, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._log_path)
        except OSError as e:
            print(f"保存日志失败: {e}", flush=True)
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass

    def add(self, success, message, file_path=""):
        """添加一条打印日志（线程安全）"""
        with self._lock:
            self._seq += 1
            entry = {
                "id": self._seq,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "success": success,
                "message": message,
                "file_path": file_path,
            }
            self._logs.append(entry)

            # 保留最近 N 条
            if len(self._logs) > self.MAX_LOGS:
                self._logs = self._logs[-self.MAX_LOGS:]

            self._save_locked()
            return entry

    def get_logs(self, limit=100):
        """获取最近 N 条日志（倒序，最新的在前）"""
        return list(reversed(self._logs[-limit:]))

    def clear(self):
        """清空所有日志（线程安全）"""
        with self._lock:
            self._logs = []
            self._save_locked()

    def count(self):
        return len(self._logs)
