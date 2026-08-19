"""后台定时调度管理模块"""

import threading
import schedule
from datetime import datetime


class SchedulerManager:
    """后台线程定时调度，支持每天 / 每 N 天"""

    FREQUENCY_MAP = {
        "daily": 1,
        "every_2": 2,
        "every_3": 3,
        "every_5": 5,
        "every_7": 7,
    }

    def __init__(self, config, job_callback):
        """
        config: ConfigManager 实例
        job_callback: 到时回调，签名为 job_callback()
        """
        self._config = config
        self._callback = job_callback
        self._thread = None
        self._stop_event = threading.Event()
        self._next_run = None

    # ------------------------------------------------------------------ #
    #  控制
    # ------------------------------------------------------------------ #

    def start(self):
        if self._thread and self._thread.is_alive():
            return  # 已在运行

        self._stop_event.clear()
        self._setup_job()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._config.set("schedule.enabled", True)

    def stop(self):
        self._stop_event.set()
        schedule.clear()
        self._next_run = None
        # 等待线程退出，避免 is_running 误报（_run_loop 用 wait() 轮询，1 秒内退出）
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        self._config.set("schedule.enabled", False)

    @property
    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    def get_next_run_time(self):
        """获取下次计划打印时间 (datetime)，仅在运行中有效"""
        if not self.is_running:
            return None
        jobs = schedule.get_jobs()
        if jobs:
            nt = jobs[0].next_run
            if nt:
                return nt.replace(tzinfo=None)
        return None

    # ------------------------------------------------------------------ #
    #  内部
    # ------------------------------------------------------------------ #

    def _setup_job(self):
        schedule.clear()
        freq = self._config.get("schedule.frequency", "daily")
        hour = self._config.get("schedule.hour", 9)
        minute = self._config.get("schedule.minute", 0)
        days = self.FREQUENCY_MAP.get(freq, 1)

        time_str = f"{int(hour):02d}:{int(minute):02d}"

        if days == 1:
            schedule.every().day.at(time_str).do(self._fire)
        else:
            schedule.every(days).days.at(time_str).do(self._fire)

    def _fire(self):
        """定时器触发，通过标志位跳过已被 stop 清理的残余任务"""
        if self._stop_event.is_set():
            return schedule.CancelJob
        try:
            self._callback()
        except Exception:
            # 不静默吞掉：回调未捕获的异常打印到 stderr，便于排查
            import traceback
            traceback.print_exc()

    def _run_loop(self):
        # 用 wait() 而非 sleep()：stop() 后能立刻响应退出
        while not self._stop_event.is_set():
            schedule.run_pending()
            self._stop_event.wait(1)

    # ------------------------------------------------------------------ #
    #  工具
    # ------------------------------------------------------------------ #

    @staticmethod
    def interval_to_label(freq_key):
        return SchedulerManager.FREQUENCY_MAP.get(freq_key, 1)
