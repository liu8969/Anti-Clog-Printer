#!/usr/bin/env python3
"""Docker Web 管理端 — NiceGUI 4 页签界面"""

import asyncio
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nicegui import ui
from config_manager import ConfigManager
from log_manager import LogManager
from content_generator import ContentGenerator
from scheduler_manager import SchedulerManager
from ipp_client import send_print_job, test_printer_connection


# ====================================================================== #
#  后端
# ====================================================================== #

class App:
    def __init__(self):
        self.config = ConfigManager()
        self.log_mgr = LogManager()
        self.content_gen = ContentGenerator(self.config)
        self.scheduler = SchedulerManager(self.config, self._scheduled_print)

    def do_print(self):
        ip = self.config.get("printer.ip", "")
        port = self.config.get("printer.port", 631)
        path = self.config.get("printer.ipp_path", "/ipp/print")
        jpg = self.content_gen.generate()
        with open(jpg, "rb") as f:
            data = f.read()
        ok, msg = send_print_job(ip, port, path, data)
        self.log_mgr.add(ok, msg, jpg)
        return ok, msg

    def _scheduled_print(self):
        self.do_print()

    def test_conn(self):
        return test_printer_connection(
            self.config.get("printer.ip", ""),
            self.config.get("printer.port", 631),
            self.config.get("printer.ipp_path", "/ipp/print"),
        )

    def load_env(self):
        for key, ev in [
            ("printer.ip", "PRINTER_IP"), ("printer.port", "PRINTER_PORT"),
            ("printer.ipp_path", "PRINTER_IPP_PATH"),
            ("schedule.frequency", "SCHEDULE_FREQUENCY"),
            ("schedule.hour", "SCHEDULE_HOUR"), ("schedule.minute", "SCHEDULE_MINUTE"),
            ("content.custom_text", "CUSTOM_TEXT"),
        ]:
            v = os.environ.get(ev)
            if v:
                self.config.set(key, int(v) if key.endswith(("port", "hour", "minute")) else v)


app = App()
app.load_env()

# 无论有没有人打开网页，计划恢复运行
if app.config.get("schedule.enabled", False):
    app.scheduler.start()


# ====================================================================== #
#  NiceGUI 界面（auto-index 模式，单用户共享）
# ====================================================================== #

ui.label("喷墨打印机自动防堵程序").classes("text-h5")

with ui.tabs().classes("w-full") as tabs:
    t1 = ui.tab("打印机设置")
    t2 = ui.tab("打印计划")
    t3 = ui.tab("打印内容")
    t4 = ui.tab("打印日志")

with ui.tab_panels(tabs, value=t1).classes("w-full"):

    # ====== Tab 1: 打印机设置 ======
    with ui.tab_panel(t1).classes("p-4"):
        ip_inp = ui.input("打印机 IP 地址", value=app.config.get("printer.ip", ""))
        with ui.row():
            port_inp = ui.number("端口", value=app.config.get("printer.port", 631),
                                 min=1, max=65535, precision=0)
            path_inp = ui.input("IPP 路径", value=app.config.get("printer.ipp_path", "/ipp/print"))
        conn_label = ui.label("").classes("text-grey")

        def test_conn():
            app.config.set("printer.ip", ip_inp.value.strip())
            app.config.set("printer.port", int(port_inp.value))
            app.config.set("printer.ipp_path", path_inp.value.strip())
            conn_label.set_text("正在连接...").classes("text-grey")
            ok, msg = app.test_conn()
            conn_label.set_text(msg).classes("text-positive" if ok else "text-negative")

        ui.button("测试连接", icon="wifi", on_click=test_conn)

    # ====== Tab 2: 打印计划 ======
    with ui.tab_panel(t2).classes("p-4"):
        freq_map = {"每天": "daily", "每 2 天": "every_2", "每 3 天": "every_3",
                    "每 5 天": "every_5", "每 7 天": "every_7"}
        rev = {v: k for k, v in freq_map.items()}
        cur = app.config.get("schedule.frequency", "daily")

        freq_sel = ui.select(list(freq_map.keys()), value=rev.get(cur, "每天"), label="打印频率")
        with ui.row():
            hour_inp = ui.number("时", value=app.config.get("schedule.hour", 9),
                                 min=0, max=23, precision=0)
            minute_inp = ui.number("分", value=app.config.get("schedule.minute", 0),
                                   min=0, max=59, precision=0)

        next_label = ui.label("（计划未启动）").classes("text-blue")

        def do_start():
            app.config.set("schedule.frequency", freq_map[freq_sel.value])
            app.config.set("schedule.hour", int(hour_inp.value))
            app.config.set("schedule.minute", int(minute_inp.value))
            app.scheduler.start()
            refresh_buttons()
            refresh_status()
            ui.notify("计划已启动", type="positive")

        def do_stop():
            app.scheduler.stop()
            refresh_buttons()
            refresh_status()
            ui.notify("计划已停止", type="warning")

        with ui.row():
            start_btn = ui.button("启动定时打印", icon="play_arrow", on_click=do_start)
            stop_btn = ui.button("停止", icon="stop", on_click=do_stop)

        def refresh_buttons():
            start_btn.set_enabled(not app.scheduler.is_running)
            stop_btn.set_enabled(app.scheduler.is_running)

    # ====== Tab 3: 打印内容 ======
    with ui.tab_panel(t3).classes("p-4"):
        custom_text = ui.textarea("自定义备注文字",
                                  value=app.config.get("content.custom_text", ""))
        ui.label("测试页包含: CMYK 四色条 / 混合色 / 渐变色 / 喷嘴网格").classes("text-grey")
        ui.button("保存内容设置", icon="save",
                  on_click=lambda: (
                      app.config.set("content.custom_text", custom_text.value),
                      ui.notify("已保存", type="positive"),
                  ))

    # ====== Tab 4: 打印日志 ======
    with ui.tab_panel(t4).classes("p-4"):
        cols = [
            {"name": "time", "label": "时间", "field": "time", "align": "left"},
            {"name": "status", "label": "状态", "field": "status", "align": "left"},
            {"name": "message", "label": "详情", "field": "message", "align": "left"},
        ]
        log_table = ui.table(columns=cols, rows=[], row_key="time").classes("w-full")

        def refresh_log():
            rows = [{"time": e["time"], "status": "成功" if e["success"] else "失败",
                     "message": e["message"]} for e in app.log_mgr.get_logs(100)]
            log_table.rows = rows

        with ui.row():
            ui.button("刷新", icon="refresh", on_click=refresh_log)
            ui.button("清空", icon="delete",
                      on_click=lambda: (app.log_mgr.clear(), refresh_log()))


# ====== 底部状态栏 ======
with ui.row().classes("w-full items-center gap-4 mt-4"):
    status_label = ui.label("就绪").classes("text-grey")
    ui.space()

    async def manual_print():
        ok, msg = await asyncio.to_thread(app.do_print)
        refresh_log()
        if ok:
            ui.notify("打印成功", type="positive")
        else:
            ui.notify(f"打印失败: {msg}", type="negative")

    ui.button("立即打印", icon="print", on_click=manual_print)


# ====== 定时刷新 ======
def refresh_status():
    if app.scheduler.is_running:
        nt = app.scheduler.get_next_run_time()
        next_label.set_text(nt.strftime("%Y-%m-%d %H:%M:%S") if nt else "—")
        status_label.set_text("计划运行中")
    else:
        next_label.set_text("（计划未启动）")
        status_label.set_text("就绪")
    refresh_buttons()

def refresh_buttons():
    start_btn.set_enabled(not app.scheduler.is_running)
    stop_btn.set_enabled(app.scheduler.is_running)

# 初始化按钮状态
refresh_buttons()

ui.timer(10, callback=lambda: (refresh_status(), refresh_log()))

# ====== 初始加载日志 ======
refresh_log()


# ====================================================================== #
#  启动
# ====================================================================== #

ui.run(host="0.0.0.0", port=18080, title="打印机自动防堵程序", show=False, reload=False)
