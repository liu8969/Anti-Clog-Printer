#!/usr/bin/env python3
"""Docker Web 管理端 — NiceGUI 4 页签界面"""

import asyncio
import base64
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from nicegui import app as nicegui_app
from nicegui import ui
from config_manager import ConfigManager
from log_manager import LogManager
from content_generator import ContentGenerator
from scheduler_manager import SchedulerManager
from ipp_client import send_print_job, test_printer_connection


# ====================================================================== #
#  Basic Auth 中间件（设置 WEB_PASSWORD 后启用）
# ====================================================================== #

WEB_USER = os.environ.get("WEB_USER", "admin")
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "")


def _safe_int(value, default):
    """安全转 int：UI 数字输入被清空/非法时回退默认值，避免回调抛异常无反馈"""
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


class BasicAuthMiddleware:
    """
    纯 ASGI 中间件：保护管理界面。
    设置环境变量 WEB_PASSWORD 后启用 Basic Auth（用户名默认 admin）。
    仅拦截 HTTP 请求；WebSocket 与后端调度不受影响。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if not WEB_PASSWORD or scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 健康探针不经过 Basic Auth：探针只读、无副作用，dpl/HEALTHCHECK 需要稳定 200。
        if scope.get("path") == "/healthz":
            await self.app(scope, receive, send)
            return

        auth = b""
        for k, v in scope.get("headers") or []:
            if k == b"authorization":
                auth = v
                break

        ok = False
        if auth.startswith(b"Basic "):
            try:
                decoded = base64.b64decode(auth[6:]).decode("utf-8")
                user, _, pwd = decoded.partition(":")
                ok = user == WEB_USER and secrets.compare_digest(pwd, WEB_PASSWORD)
            except Exception:
                ok = False

        if ok:
            await self.app(scope, receive, send)
            return

        body = b'{"detail": "Unauthorized"}'
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"www-authenticate", b'Basic realm="printer-admin"'),
            ],
        })
        await send({"type": "http.response.body", "body": body})


# ====================================================================== #
#  后端
# ====================================================================== #

class App:
    def __init__(self):
        self.config = ConfigManager()
        self.log_mgr = LogManager()
        self.content_gen = ContentGenerator(self.config)
        self.scheduler = SchedulerManager(self.config, self._scheduled_print)

    VALID_FREQUENCIES = ("daily", "every_2", "every_3", "every_5", "every_7")

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
        try:
            self.do_print()
        except Exception as e:
            # 定时打印路径的异常也要落日志，否则用户无从得知失败
            self.log_mgr.add(False, f"异常: {e}", "")

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
            if not v:
                continue
            if key.endswith(("port", "hour", "minute")):
                try:
                    self.config.set(key, int(v))
                except ValueError:
                    print(f"警告: 环境变量 {ev}={v} 不是有效整数，已忽略", flush=True)
            else:
                self.config.set(key, v)

        # 频率合法性校验，非法值回退 daily
        if (os.environ.get("SCHEDULE_FREQUENCY")
                and self.config.get("schedule.frequency") not in self.VALID_FREQUENCIES):
            print("警告: SCHEDULE_FREQUENCY 无效，回退为 daily", flush=True)
            self.config.set("schedule.frequency", "daily")

        # 显式调度开关：SCHEDULE_ENABLED=1/0 覆盖本地状态
        if os.environ.get("SCHEDULE_ENABLED") is not None:
            self.config.set("schedule.enabled",
                            os.environ["SCHEDULE_ENABLED"].strip().lower()
                            in ("1", "true", "yes", "on"))

        # 省墨测试模式：TEST_MODE=1 时只打印一条细色带（验证打印链路用，不防堵）
        # 注意：显式设置 PATTERN 时以 PATTERN 为准（见 resolve_pattern）
        if os.environ.get("TEST_MODE") is not None:
            self.config.set("content.test_mode",
                            os.environ["TEST_MODE"].strip().lower()
                            in ("1", "true", "yes", "on"))

        # 打印图案 / 覆盖强度 / 分辨率（新版防堵图案）
        if os.environ.get("PATTERN"):
            self.config.set("content.pattern", os.environ["PATTERN"].strip().lower())
        if os.environ.get("DUTY"):
            self.config.set("content.duty", os.environ["DUTY"].strip().lower())
        if os.environ.get("PRINT_DPI"):
            try:
                self.config.set("content.dpi", int(os.environ["PRINT_DPI"]))
            except ValueError:
                print(f"警告: PRINT_DPI={os.environ['PRINT_DPI']} 不是有效整数，已忽略",
                      flush=True)
        for key, ev in (("content.k_boost", "K_BOOST"),
                        ("content.bars", "BARS"),
                        ("content.ruler", "RULER")):
            v = os.environ.get(ev)
            if v is not None:
                self.config.set(key, v.strip().lower() in ("1", "true", "yes", "on"))

        # 测试页旋转补偿：TEST_ROTATE=1 时测试页预先旋转 90°
        #（部分打印机的图像打印会把横向小图竖排，需预先反向旋转）
        if os.environ.get("TEST_ROTATE") is not None:
            self.config.set("content.test_rotate",
                            os.environ["TEST_ROTATE"].strip().lower()
                            in ("1", "true", "yes", "on"))


# 快照"是否已有本地配置"：load_env 的 set() 会创建 config.json，须在之前判断
_CONFIG_PATH = os.environ.get("CONFIG_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config.json"
)
fresh_deploy = not os.path.exists(_CONFIG_PATH)

app = App()
app.load_env()

# ---- 调度自动恢复 ----
# 1) SCHEDULE_ENABLED 显式设置时完全以它为准；
# 2) 否则沿用本地 config.json 的 schedule.enabled（用户在 UI 停用后重启容器仍保持停用）；
# 3) 首次部署（无本地配置，只配了 PRINTER_IP）默认启用，
#    保证 24x7 防堵的核心目标开箱即用。
if os.environ.get("SCHEDULE_ENABLED") is not None:
    auto_start = app.config.get("schedule.enabled", False)
elif app.config.get("schedule.enabled", False):
    auto_start = True
elif fresh_deploy and app.config.get("printer.ip", "").strip():
    auto_start = True
else:
    auto_start = False

if auto_start:
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
            app.config.set("printer.ip", (ip_inp.value or "").strip())
            app.config.set("printer.port", _safe_int(port_inp.value, 631))
            app.config.set("printer.ipp_path", (path_inp.value or "").strip() or "/ipp/print")
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
            app.config.set("schedule.frequency", freq_map.get(freq_sel.value, "daily"))
            app.config.set("schedule.hour", _safe_int(hour_inp.value, 9))
            app.config.set("schedule.minute", _safe_int(minute_inp.value, 0))
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

    # ====== Tab 3: 打印内容 ======
    with ui.tab_panel(t3).classes("p-4"):
        custom_text = ui.textarea("自定义备注文字",
                                  value=app.config.get("content.custom_text", ""))

        pattern_map = {
            "全喷嘴斜线覆盖页（推荐：防堵主力，覆盖全部喷孔）": "coverage",
            "经典彩色页（渐变色条 + 喷嘴网格，兼容旧版）": "classic",
            "细色带自检页（只验证打印链路，不防堵）": "link_test",
        }
        duty_map = {
            "省墨（每孔每趟≈4点）": "eco",
            "标准（每孔每趟≈8点，推荐）": "standard",
            "加强（每孔每趟≈16点，已轻微堵塞时用）": "strong",
        }
        pattern_rev = {v: k for k, v in pattern_map.items()}
        duty_rev = {v: k for k, v in duty_map.items()}
        pattern_sel = ui.select(list(pattern_map), label="打印图案",
                                value=pattern_rev[app.content_gen.resolve_pattern()])
        duty_sel = ui.select(list(duty_map), label="覆盖强度（墨量档位）",
                             value=duty_rev[app.content_gen.resolve_duty()])
        with ui.row().classes("gap-6"):
            k_boost_sw = ui.switch("黑墨加强",
                                   value=bool(app.config.get("content.k_boost", True)))
            bars_sw = ui.switch("满高竖条",
                                value=bool(app.config.get("content.bars", True)))
            ruler_sw = ui.switch("左侧毫米标尺",
                                 value=bool(app.config.get("content.ruler", True)))
        ui.label("黑墨加强：K 列的斜线幕与竖条都加倍（颜料黑最容易干堵）。"
                 "左侧标尺用于读出缺口在纸上的位置（mm）。").classes("text-grey text-sm")
        content_summary = ui.label("").classes("text-blue")

        def _cur_pattern():
            return pattern_map.get(pattern_sel.value, "coverage")

        def _cur_duty():
            return duty_map.get(duty_sel.value, "standard")

        def refresh_content_summary():
            content_summary.set_text(app.content_gen.summary_line(
                pattern=_cur_pattern(), duty=_cur_duty()))

        def save_content():
            app.config.set("content.custom_text", custom_text.value or "")
            app.config.set("content.pattern", _cur_pattern())
            app.config.set("content.duty", _cur_duty())
            app.config.set("content.k_boost", bool(k_boost_sw.value))
            app.config.set("content.bars", bool(bars_sw.value))
            app.config.set("content.ruler", bool(ruler_sw.value))
            # 同步旧开关：只有"细色带自检页"才算 test_mode
            app.config.set("content.test_mode", _cur_pattern() == "link_test")
            refresh_content_summary()
            ui.notify("已保存，下次打印生效", type="positive")

        async def preview_content():
            """生成预览并下载到浏览器（不打印、不费纸）"""
            try:
                path = await asyncio.to_thread(
                    app.content_gen.generate, None, _cur_pattern(), _cur_duty())
            except Exception as e:
                ui.notify(f"生成预览失败: {e}", type="negative")
                return
            ui.download(path, filename=f"防堵测试页_{_cur_pattern()}_{_cur_duty()}.jpg")
            ui.notify("预览已生成（未打印）", type="positive")

        pattern_sel.on_value_change(lambda _: refresh_content_summary())
        duty_sel.on_value_change(lambda _: refresh_content_summary())

        with ui.row():
            ui.button("保存内容设置", icon="save", on_click=save_content)
            ui.button("生成预览并下载（不打印）", icon="image", on_click=preview_content)

        refresh_content_summary()

    # ====== Tab 4: 打印日志 ======
    with ui.tab_panel(t4).classes("p-4"):
        cols = [
            {"name": "time", "label": "时间", "field": "time", "align": "left"},
            {"name": "status", "label": "状态", "field": "status", "align": "left"},
            {"name": "message", "label": "详情", "field": "message", "align": "left"},
        ]
        # row_key 用唯一的 id（时间只有秒级精度，同秒多次打印会撞 key 导致行不更新）
        log_table = ui.table(columns=cols, rows=[], row_key="id").classes("w-full")

        def refresh_log():
            rows = [{"id": e["id"], "time": e["time"],
                     "status": "成功" if e["success"] else "失败",
                     "message": e["message"]} for e in app.log_mgr.get_logs(100)]
            # 内容无变化时不重设 rows，避免每 10 秒 timer 重置表格滚动位置
            if rows != log_table.rows:
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
        try:
            ok, msg = await asyncio.to_thread(app.do_print)
        except Exception as e:
            # 手动打印路径的异常也要落日志，否则失败无迹可寻
            app.log_mgr.add(False, f"异常: {e}", "")
            ok, msg = False, f"异常: {e}"
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

# 轻量健康探针：不要走 "/" —— NiceGUI 首页会为每个 HTTP 客户端创建页面/timer，
# Docker HEALTHCHECK 每 30s 探一次会在几天内累积数千线程（2026-10 的 8037 线程事故）。
@nicegui_app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# 设置 WEB_PASSWORD 后启用 Basic Auth 保护管理界面
if WEB_PASSWORD:
    nicegui_app.add_middleware(BasicAuthMiddleware)

ui.run(host="0.0.0.0", port=18080, title="打印机自动防堵程序",
       show=False, reload=False)
