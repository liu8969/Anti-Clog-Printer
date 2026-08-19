#!/usr/bin/env python3
"""Docker 版入口 — 无 GUI，后台定时打印防堵头测试页"""

import os
import sys
import time
import signal
import threading
import schedule
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_manager import ConfigManager
from log_manager import LogManager
from content_generator import ContentGenerator
from ipp_client import send_print_job, test_printer_connection


class DockerApp:
    def __init__(self):
        self.config = ConfigManager()
        self.log_mgr = LogManager()
        self.content_gen = ContentGenerator(self.config)
        self._stop_event = threading.Event()
        self._running = False

    # ------------------------------------------------------------------ #
    #  配置加载（环境变量覆盖 config.json）
    # ------------------------------------------------------------------ #

    def load_config(self):
        """环境变量优先级高于 config.json"""
        env = os.environ
        if env.get("PRINTER_IP"):
            self.config.set("printer.ip", env["PRINTER_IP"])
        if env.get("PRINTER_PORT"):
            self.config.set("printer.port", int(env["PRINTER_PORT"]))
        if env.get("PRINTER_IPP_PATH"):
            self.config.set("printer.ipp_path", env["PRINTER_IPP_PATH"])
        if env.get("SCHEDULE_FREQUENCY"):
            self.config.set("schedule.frequency", env["SCHEDULE_FREQUENCY"])
        if env.get("SCHEDULE_HOUR"):
            self.config.set("schedule.hour", int(env["SCHEDULE_HOUR"]))
        if env.get("SCHEDULE_MINUTE"):
            self.config.set("schedule.minute", int(env["SCHEDULE_MINUTE"]))
        if env.get("CUSTOM_TEXT"):
            self.config.set("content.custom_text", env["CUSTOM_TEXT"])
        if env.get("TEST_MODE") is not None:
            self.config.set("content.test_mode",
                            env["TEST_MODE"].strip().lower() in ("1", "true", "yes", "on"))
        if env.get("TEST_ROTATE") is not None:
            self.config.set("content.test_rotate",
                            env["TEST_ROTATE"].strip().lower() in ("1", "true", "yes", "on"))

    # ------------------------------------------------------------------ #
    #  打印
    # ------------------------------------------------------------------ #

    def do_print(self):
        """执行一次打印"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ip = self.config.get("printer.ip", "")
        port = self.config.get("printer.port", 631)
        path = self.config.get("printer.ipp_path", "/ipp/print")

        print(f"[{now}] 开始打印...", flush=True)

        try:
            jpg = self.content_gen.generate()
            with open(jpg, "rb") as f:
                data = f.read()
            success, msg = send_print_job(ip, port, path, data)
            self.log_mgr.add(success, msg, jpg)
            status = "成功" if success else "失败"
            print(f"[{now}] {status}: {msg}", flush=True)
        except Exception as e:
            self.log_mgr.add(False, str(e), "")
            print(f"[{now}] 异常: {e}", flush=True)

    # ------------------------------------------------------------------ #
    #  调度
    # ------------------------------------------------------------------ #

    def start(self):
        freq = self.config.get("schedule.frequency", "daily")
        hour = self.config.get("schedule.hour", 9)
        minute = self.config.get("schedule.minute", 0)

        freq_days = {"daily": 1, "every_2": 2, "every_3": 3,
                     "every_5": 5, "every_7": 7}
        days = freq_days.get(freq, 1)
        time_str = f"{int(hour):02d}:{int(minute):02d}"

        if days == 1:
            schedule.every().day.at(time_str).do(self.do_print)
        else:
            schedule.every(days).days.at(time_str).do(self.do_print)

        print(f"定时打印已启动: 每{days}天 {time_str}", flush=True)
        print(f"打印机: {self.config.ipp_uri}", flush=True)

        self._running = True
        while not self._stop_event.is_set():
            schedule.run_pending()
            time.sleep(30)

    def stop(self):
        self._running = False
        self._stop_event.set()

    # ------------------------------------------------------------------ #
    #  诊断
    # ------------------------------------------------------------------ #

    def test(self):
        """连接测试"""
        ip = self.config.get("printer.ip", "")
        port = self.config.get("printer.port", 631)
        path = self.config.get("printer.ipp_path", "/ipp/print")
        print(f"测试连接: {ip}:{port}{path} ...", flush=True)
        ok, msg = test_printer_connection(ip, port, path)
        print(f"{'OK' if ok else 'FAIL'}: {msg}", flush=True)
        return ok


# ====================================================================== #
#  main
# ====================================================================== #

def main():
    app = DockerApp()
    app.load_config()

    # 命令行子命令
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"

    if cmd == "test":
        app.test()
    elif cmd == "print":
        app.do_print()
    elif cmd == "run":
        # 信号处理
        signal.signal(signal.SIGTERM, lambda *_: app.stop())
        signal.signal(signal.SIGINT, lambda *_: app.stop())

        # 启动前先测试连接
        if not app.test():
            print("警告: 打印机连接测试失败，继续尝试定时打印...", flush=True)

        app.do_print()  # 启动时立即打印一次
        app.start()
    else:
        print(f"用法: python docker_main.py [run|test|print]")


if __name__ == "__main__":
    main()
