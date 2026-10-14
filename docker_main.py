#!/usr/bin/env python3
"""Docker 版入口 — 无 GUI，后台定时打印防堵头测试页

与 web_main 共用 SchedulerManager（1 秒级轮询、回调异常落日志、stop 可快速退出），
避免两套调度实现行为不一致。
"""

import os
import sys
import time
import signal
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_manager import ConfigManager
from log_manager import LogManager
from content_generator import ContentGenerator
from scheduler_manager import SchedulerManager
from ipp_client import send_print_job, test_printer_connection

VALID_FREQUENCIES = ("daily", "every_2", "every_3", "every_5", "every_7")


def _safe_int(value, default):
    """安全转 int：非法值回退默认并告警，避免启动崩溃"""
    try:
        return int(value)
    except (TypeError, ValueError):
        print(f"警告: 值 {value!r} 不是有效整数，使用默认值 {default}", flush=True)
        return default


def _to_bool(v):
    return v.strip().lower() in ("1", "true", "yes", "on")


class DockerApp:
    def __init__(self):
        self.config = ConfigManager()
        self.log_mgr = LogManager()
        self.content_gen = ContentGenerator(self.config)
        self.scheduler = SchedulerManager(self.config, self._scheduled_print)
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------ #
    #  配置加载（环境变量覆盖 config.json）
    # ------------------------------------------------------------------ #

    def load_config(self):
        """环境变量优先级高于 config.json（仅当环境变量已设置时覆盖）"""
        env = os.environ
        if env.get("PRINTER_IP"):
            self.config.set("printer.ip", env["PRINTER_IP"].strip())
        if env.get("PRINTER_PORT"):
            self.config.set("printer.port", _safe_int(env["PRINTER_PORT"], 631))
        if env.get("PRINTER_IPP_PATH"):
            self.config.set("printer.ipp_path", env["PRINTER_IPP_PATH"].strip())
        if env.get("SCHEDULE_FREQUENCY"):
            freq = env["SCHEDULE_FREQUENCY"].strip()
            if freq not in VALID_FREQUENCIES:
                print(f"警告: SCHEDULE_FREQUENCY={freq} 无效，回退为 daily", flush=True)
                freq = "daily"
            self.config.set("schedule.frequency", freq)
        if env.get("SCHEDULE_HOUR"):
            self.config.set("schedule.hour", _safe_int(env["SCHEDULE_HOUR"], 9))
        if env.get("SCHEDULE_MINUTE"):
            self.config.set("schedule.minute", _safe_int(env["SCHEDULE_MINUTE"], 0))
        if env.get("CUSTOM_TEXT"):
            self.config.set("content.custom_text", env["CUSTOM_TEXT"])
        if env.get("TEST_MODE") is not None:
            self.config.set("content.test_mode", _to_bool(env["TEST_MODE"]))
        if env.get("TEST_ROTATE") is not None:
            self.config.set("content.test_rotate", _to_bool(env["TEST_ROTATE"]))
        # 打印图案 / 覆盖强度 / 分辨率：显式 PATTERN 优先于旧的 TEST_MODE
        if env.get("PATTERN"):
            self.config.set("content.pattern", env["PATTERN"].strip().lower())
        if env.get("DUTY"):
            self.config.set("content.duty", env["DUTY"].strip().lower())
        if env.get("PRINT_DPI"):
            try:
                self.config.set("content.dpi", int(env["PRINT_DPI"]))
            except ValueError:
                print(f"警告: PRINT_DPI={env['PRINT_DPI']} 不是有效整数，已忽略",
                      flush=True)
        for key, ev in (("content.k_boost", "K_BOOST"),
                        ("content.bars", "BARS"),
                        ("content.ruler", "RULER")):
            if env.get(ev) is not None:
                self.config.set(key, _to_bool(env[ev]))

    # ------------------------------------------------------------------ #
    #  打印
    # ------------------------------------------------------------------ #

    def do_print(self):
        """执行一次打印"""
        from datetime import datetime
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
            self.log_mgr.add(False, f"异常: {e}", "")
            print(f"[{now}] 异常: {e}", flush=True)

    def _scheduled_print(self):
        """SchedulerManager 触发（已在后台线程）；异常也要落日志"""
        try:
            self.do_print()
        except Exception as e:
            self.log_mgr.add(False, f"异常: {e}", "")

    # ------------------------------------------------------------------ #
    #  调度
    # ------------------------------------------------------------------ #

    def run_forever(self):
        """启动调度并阻塞主线程，直到收到停止信号"""
        self.scheduler.start()
        freq = self.config.get("schedule.frequency", "daily")
        hour = int(self.config.get("schedule.hour", 9))
        minute = int(self.config.get("schedule.minute", 0))
        print(f"定时打印已启动: 频率={freq} 时间={hour:02d}:{minute:02d}", flush=True)
        print(f"打印机: {self.config.ipp_uri}", flush=True)
        print("等待停止信号 (SIGTERM/SIGINT) ...", flush=True)

        # 阻塞主线程；调度跑在 SchedulerManager 的后台守护线程
        while not self._stop_event.is_set():
            time.sleep(0.5)

    def stop(self):
        """仅解除主线程阻塞。

        不调用 scheduler.stop()：它会把 schedule.enabled=False 持久化进
        config.json（Docker 挂载卷），可能改变重启后的自动启动行为。
        守护线程随进程退出而结束即可。
        """
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

    def preview(self, pattern=None, duty=None, out=None):
        """生成预览图（不打印、不费纸）并打印墨量统计"""
        info = self.content_gen.describe(pattern=pattern, duty=duty)
        path = self.content_gen.generate(pattern=pattern, duty=duty, out_path=out)
        print(f"图案={info['pattern']} 档位={info.get('duty')} "
              f"分辨率={info.get('dpi')}dpi 尺寸={info['width']}x{info['height']}",
              flush=True)
        per = info.get("coverage_percent")
        if per:
            print("每色覆盖: " + " / ".join(f"{k} {v:.2f}%" for k, v in per.items()),
                  flush=True)
            print(f"整页覆盖≈{info['coverage_total_percent']:.2f}% "
                  f"（约 {info['ink_ml_per_page']:.3f} ml/页）", flush=True)
        else:
            print(f"整页覆盖≈{info['coverage_total_percent']:.2f}%", flush=True)
        print(f"预览图: {path}", flush=True)
        return path


# ====================================================================== #
#  main
# ====================================================================== #

def main():
    import argparse

    app = DockerApp()
    app.load_config()

    parser = argparse.ArgumentParser(
        description="喷墨打印机自动防堵程序（Docker 无界面版）")
    parser.add_argument("command", nargs="?", default="run",
                        choices=["run", "test", "print", "preview"],
                        help="run=定时运行（默认）/ test=连接测试 / print=立即打印 / "
                             "preview=生成预览图（不打印）")
    parser.add_argument("--pattern", choices=["coverage", "classic", "link_test"],
                        help="预览用的打印图案（默认取配置）")
    parser.add_argument("--duty", choices=["eco", "standard", "strong"],
                        help="预览用的覆盖强度（默认取配置）")
    parser.add_argument("--out", help="预览图输出路径（默认临时目录）")
    parser.add_argument("--all", action="store_true", help="预览全部三种图案")
    args = parser.parse_args()

    if args.command == "test":
        app.test()
    elif args.command == "print":
        app.do_print()
    elif args.command == "preview":
        patterns = ["coverage", "classic", "link_test"] if args.all else [args.pattern]
        for p in patterns:
            out = args.out
            if out and len(patterns) > 1:
                root, ext = os.path.splitext(out)
                out = f"{root}_{p}{ext or '.jpg'}"
            app.preview(pattern=p, duty=args.duty, out=out)
    elif args.command == "run":
        # 信号处理（仅在主线程注册）
        signal.signal(signal.SIGTERM, lambda *_: app.stop())
        signal.signal(signal.SIGINT, lambda *_: app.stop())

        # 启动前先测试连接
        if not app.test():
            print("警告: 打印机连接测试失败，继续尝试定时打印...", flush=True)

        app.do_print()  # 启动时立即打印一次
        app.run_forever()


if __name__ == "__main__":
    main()
