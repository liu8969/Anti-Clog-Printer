#!/usr/bin/env python3
"""喷墨打印机自动防堵程序 - GUI 主入口"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import os
import sys

# 确保能找到同目录模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_manager import ConfigManager
from log_manager import LogManager
from content_generator import ContentGenerator
from print_manager import PrintManager
from scheduler_manager import SchedulerManager


class App:
    def __init__(self):
        self.config = ConfigManager()
        self.log_mgr = LogManager()
        self.content_gen = ContentGenerator(self.config)
        self.print_mgr = PrintManager(self.config)
        self.scheduler = SchedulerManager(self.config, self._scheduled_print)

        self.root = tk.Tk()
        self.root.title("喷墨打印机自动防堵程序")
        self.root.geometry("700x580")
        self.root.minsize(640, 480)

        # 窗口关闭 → 隐藏而非退出（如计划在跑）
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._load_ui_from_config()

        # 如果上次运行时计划是启用的，自动启动
        if self.config.get("schedule.enabled", False):
            self._safe_start_scheduler()

        # 定时刷新状态
        self._update_status()

    # ================================================================== #
    #  UI 构建
    # ================================================================== #

    def _build_ui(self):
        # 主容器
        main_frame = ttk.Frame(self.root, padding=8)
        main_frame.pack(fill="both", expand=True)

        # ---- 标题 ----
        title = ttk.Label(
            main_frame,
            text="喷墨打印机自动防堵程序",
            font=("", 18, "bold"),
        )
        title.pack(pady=(0, 8))

        # ---- Tab 页签 ----
        self._notebook = ttk.Notebook(main_frame)
        self._notebook.pack(fill="both", expand=True)

        self._build_printer_tab()
        self._build_schedule_tab()
        self._build_content_tab()
        self._build_log_tab()

        # ---- 底部按钮栏 ----
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill="x", pady=(8, 0))

        self._btn_save = ttk.Button(btn_frame, text="保存设置", command=self._save_settings)
        self._btn_save.pack(side="left", padx=2)

        self._btn_print_now = ttk.Button(
            btn_frame, text="立即打印", command=self._print_now
        )
        self._btn_print_now.pack(side="left", padx=2)

        self._btn_start = ttk.Button(
            btn_frame, text="启动定时打印", command=self._safe_start_scheduler
        )
        self._btn_start.pack(side="left", padx=2)

        self._btn_stop = ttk.Button(
            btn_frame, text="停止", command=self._stop_scheduler
        )
        self._btn_stop.pack(side="left", padx=2)

        # ---- 状态栏 ----
        self._status_var = tk.StringVar(value="就绪")
        status_bar = ttk.Label(
            main_frame,
            textvariable=self._status_var,
            relief="sunken",
            anchor="w",
            padding=4,
        )
        status_bar.pack(fill="x", pady=(6, 0))

    # ---------- Tab 1: 打印机设置 ----------

    def _build_printer_tab(self):
        tab = ttk.Frame(self._notebook, padding=16)
        self._notebook.add(tab, text="打印机设置")

        row = 0
        pad_y = 8

        # IP
        ttk.Label(tab, text="打印机 IP 地址:").grid(
            row=row, column=0, sticky="w", pady=pad_y
        )
        self._var_ip = tk.StringVar()
        self._entry_ip = ttk.Entry(tab, textvariable=self._var_ip, width=22)
        self._entry_ip.grid(row=row, column=1, sticky="w", padx=(8, 0), pady=pad_y)

        # 端口
        ttk.Label(tab, text="端口:").grid(row=row, column=2, sticky="w", padx=(16, 0), pady=pad_y)
        self._var_port = tk.StringVar(value="631")
        ttk.Entry(tab, textvariable=self._var_port, width=6).grid(
            row=row, column=3, sticky="w", padx=(4, 0), pady=pad_y
        )
        row += 1

        # IPP 路径
        ttk.Label(tab, text="IPP 路径:").grid(row=row, column=0, sticky="w", pady=pad_y)
        self._var_ipp_path = tk.StringVar(value="/ipp/print")
        ttk.Entry(tab, textvariable=self._var_ipp_path, width=28).grid(
            row=row, column=1, columnspan=3, sticky="w", padx=(8, 0), pady=pad_y
        )
        row += 1

        # 完整 URI 预览
        ttk.Label(tab, text="IPP URI:").grid(row=row, column=0, sticky="w", pady=pad_y)
        self._var_uri_preview = tk.StringVar()
        uri_label = ttk.Label(
            tab, textvariable=self._var_uri_preview, foreground="gray"
        )
        uri_label.grid(row=row, column=1, columnspan=3, sticky="w", padx=(8, 0), pady=pad_y)
        row += 1

        # 测试按钮
        btn_frame = ttk.Frame(tab)
        btn_frame.grid(row=row, column=0, columnspan=4, sticky="w", pady=(12, 0))
        ttk.Button(btn_frame, text="测试连接", command=self._test_connection).pack(
            side="left"
        )

        self._var_conn_status = tk.StringVar(value="等待测试...")
        ttk.Label(
            btn_frame, textvariable=self._var_conn_status, foreground="gray"
        ).pack(side="left", padx=(12, 0))

        # 路径变更时更新 URI 预览
        for v in (self._var_ip, self._var_port, self._var_ipp_path):
            v.trace_add("write", lambda *_: self._update_uri_preview())

    # ---------- Tab 2: 打印计划 ----------

    def _build_schedule_tab(self):
        tab = ttk.Frame(self._notebook, padding=16)
        self._notebook.add(tab, text="打印计划")

        row = 0
        pad_y = 10

        ttk.Label(tab, text="打印频率:").grid(row=row, column=0, sticky="w", pady=pad_y)
        self._var_freq = tk.StringVar(value="daily")
        freq_combo = ttk.Combobox(
            tab,
            textvariable=self._var_freq,
            values=["daily", "every_2", "every_3", "every_5", "every_7"],
            state="readonly",
            width=10,
        )
        freq_combo["values"] = ("每天", "每 2 天", "每 3 天", "每 5 天", "每 7 天")
        freq_combo.current(0)
        freq_combo.grid(row=row, column=1, sticky="w", padx=(8, 0), pady=pad_y)
        row += 1

        ttk.Label(tab, text="打印时间:").grid(row=row, column=0, sticky="w", pady=pad_y)
        time_frame = ttk.Frame(tab)
        time_frame.grid(row=row, column=1, sticky="w", padx=(8, 0), pady=pad_y)

        self._var_hour = tk.StringVar(value="9")
        ttk.Spinbox(time_frame, textvariable=self._var_hour, from_=0, to=23, width=3).pack(side="left")
        ttk.Label(time_frame, text=" 时 ").pack(side="left")
        self._var_minute = tk.StringVar(value="0")
        ttk.Spinbox(time_frame, textvariable=self._var_minute, from_=0, to=59, width=3).pack(side="left")
        ttk.Label(time_frame, text=" 分").pack(side="left")
        row += 1

        ttk.Label(tab, text="下次打印:").grid(row=row, column=0, sticky="w", pady=(20, 0))
        self._var_next_run = tk.StringVar(value="（计划未启动）")
        ttk.Label(
            tab, textvariable=self._var_next_run, foreground="blue"
        ).grid(row=row, column=1, sticky="w", padx=(8, 0), pady=(20, 0))

    # ---------- Tab 3: 打印内容 ----------

    def _build_content_tab(self):
        tab = ttk.Frame(self._notebook, padding=16)
        self._notebook.add(tab, text="打印内容")

        ttk.Label(tab, text="自定义备注文字（会出现在测试页上）:").pack(anchor="w")

        self._text_custom = tk.Text(tab, height=4, width=60)
        self._text_custom.pack(fill="x", pady=(6, 12))

        ttk.Label(
            tab,
            text="测试页包含: CMYK 四色条 / 混合色条 / 渐变色条 / 喷嘴网格",
            foreground="gray",
        ).pack(anchor="w")

    # ---------- Tab 4: 打印日志 ----------

    def _build_log_tab(self):
        tab = ttk.Frame(self._notebook, padding=12)
        self._notebook.add(tab, text="打印日志")

        # 表格
        columns = ("time", "status", "message")
        self._log_tree = ttk.Treeview(
            tab, columns=columns, show="headings", height=12
        )
        self._log_tree.heading("time", text="时间")
        self._log_tree.heading("status", text="状态")
        self._log_tree.heading("message", text="详情")

        self._log_tree.column("time", width=160, anchor="center")
        self._log_tree.column("status", width=80, anchor="center")
        self._log_tree.column("message", width=340, anchor="w")

        scrollbar = ttk.Scrollbar(tab, orient="vertical", command=self._log_tree.yview)
        self._log_tree.configure(yscrollcommand=scrollbar.set)

        self._log_tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # 操作按钮
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill="x", pady=(6, 0))
        ttk.Button(btn_frame, text="刷新", command=self._refresh_log_view).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="清空日志", command=self._clear_logs).pack(side="left", padx=2)

        self._refresh_log_view()

    # ================================================================== #
    #  事件处理
    # ================================================================== #

    def _update_uri_preview(self):
        ip = self._var_ip.get().strip()
        port = self._var_port.get().strip()
        path = self._var_ipp_path.get().strip()
        if ip:
            self._var_uri_preview.set(f"ipp://{ip}:{port}{path}")
        else:
            self._var_uri_preview.set("（请先输入 IP 地址）")

    def _test_connection(self):
        self._sync_ui_to_config()
        self._var_conn_status.set("正在连接...")
        self.root.update_idletasks()

        def _task():
            success, msg = self.print_mgr.test_connection()
            self.root.after(0, lambda: self._on_test_connection_done(success, msg))

        threading.Thread(target=_task, daemon=True).start()

    def _on_test_connection_done(self, success, msg):
        if success:
            self._var_conn_status.set("已连接 - 打印机可达")
        else:
            short = msg.split("\n")[0][:80]
            self._var_conn_status.set(f"连接失败: {short}")

    def _print_now(self):
        """立即打印一次（在后台线程中执行，避免阻塞 GUI）"""
        self._sync_ui_to_config()

        self._btn_print_now.config(state="disabled", text="打印中...")
        self._set_status("正在打印...")

        def _task():
            try:
                jpg = self.content_gen.generate()
                success, msg = self.print_mgr.print_file(jpg)
                self.log_mgr.add(success, msg, jpg)
            except Exception as e:
                success = False
                msg = f"异常: {e}"
                self.log_mgr.add(False, msg, "")

            self.root.after(0, lambda: self._on_print_done(success, msg))

        threading.Thread(target=_task, daemon=True).start()

    def _on_print_done(self, success, msg):
        self._btn_print_now.config(state="normal", text="立即打印")
        self._refresh_log_view()
        if success:
            self._set_status(f"打印完成: {msg}")
        else:
            self._set_status(f"打印失败: {msg}")
            messagebox.showwarning("打印结果", f"打印失败\n\n{msg}")

    def _scheduled_print(self):
        """计划触发时的打印回调（已在后台线程中）"""
        try:
            jpg, pdf = self.content_gen.generate("both")
            success, msg = self.print_mgr.print_file(jpg, pdf)
            self.log_mgr.add(success, msg, jpg)
        except Exception as e:
            self.log_mgr.add(False, f"异常: {e}", "")

        # 更新 GUI（主线程）
        self.root.after(0, self._refresh_log_view)

    def _safe_start_scheduler(self):
        self._sync_ui_to_config()

        if not self._config.get("printer.ip", "").strip():
            messagebox.showwarning("提示", "请先填写打印机 IP 地址")
            return

        self.scheduler.start()
        self._set_status("计划已启动")
        self._refresh_status()

    def _stop_scheduler(self):
        self.scheduler.stop()
        self._set_status("计划已停止")
        self._var_next_run.set("（计划未启动）")

    def _save_settings(self):
        self._sync_ui_to_config()
        self._set_status("设置已保存")
        if self.scheduler.is_running:
            # 重启调度以应用新设置
            self.scheduler.stop()
            self.scheduler.start()

    def _clear_logs(self):
        if messagebox.askyesno("确认", "确定要清空所有打印日志吗？"):
            self.log_mgr.clear()
            self._refresh_log_view()

    def _on_close(self):
        if self.scheduler.is_running:
            # 隐藏窗口，调度器继续在后台运行
            self.root.withdraw()
            messagebox.showinfo(
                "提示", "程序将在后台继续运行。\n\n可在 Dock 中点击图标重新打开窗口。"
            )
        else:
            self.root.destroy()

    # ================================================================== #
    #  UI ↔ Config 同步
    # ================================================================== #

    def _sync_ui_to_config(self):
        """将 GUI 控件的值写入配置"""
        self.config.set("printer.ip", self._var_ip.get().strip())
        try:
            self.config.set("printer.port", int(self._var_port.get().strip()))
        except ValueError:
            self.config.set("printer.port", 631)
        self.config.set("printer.ipp_path", self._var_ipp_path.get().strip())

        freq_map = {"每天": "daily", "每 2 天": "every_2", "每 3 天": "every_3",
                     "每 5 天": "every_5", "每 7 天": "every_7"}
        self.config.set("schedule.frequency", freq_map.get(self._var_freq.get(), "daily"))
        try:
            self.config.set("schedule.hour", int(self._var_hour.get()))
        except ValueError:
            pass
        try:
            self.config.set("schedule.minute", int(self._var_minute.get()))
        except ValueError:
            pass

        custom_text = self._text_custom.get("1.0", "end-1c")
        self.config.set("content.custom_text", custom_text)

    def _load_ui_from_config(self):
        """将配置值填入 GUI 控件"""
        self._var_ip.set(self.config.get("printer.ip", ""))
        self._var_port.set(str(self.config.get("printer.port", 631)))
        self._var_ipp_path.set(self.config.get("printer.ipp_path", "/ipp/print"))

        freq_to_label = {"daily": "每天", "every_2": "每 2 天", "every_3": "每 3 天",
                         "every_5": "每 5 天", "every_7": "每 7 天"}
        freq = self.config.get("schedule.frequency", "daily")
        self._var_freq.set(freq_to_label.get(freq, "每天"))

        self._var_hour.set(str(self.config.get("schedule.hour", 9)))
        self._var_minute.set(str(self.config.get("schedule.minute", 0)))

        custom_text = self.config.get("content.custom_text", "")
        self._text_custom.delete("1.0", "end")
        if custom_text:
            self._text_custom.insert("1.0", custom_text)

        self._update_uri_preview()

    def _refresh_log_view(self):
        """刷新日志表格"""
        for item in self._log_tree.get_children():
            self._log_tree.delete(item)

        for entry in self.log_mgr.get_logs(limit=200):
            status = "成功" if entry["success"] else "失败"
            tag = "ok" if entry["success"] else "fail"
            self._log_tree.insert(
                "",
                "end",
                values=(entry["time"], status, entry["message"]),
                tags=(tag,),
            )

        self._log_tree.tag_configure("ok", foreground="green")
        self._log_tree.tag_configure("fail", foreground="red")

    # ================================================================== #
    #  状态刷新
    # ================================================================== #

    def _update_status(self):
        self._refresh_status()
        self.root.after(10_000, self._update_status)  # 每 10 秒

    def _refresh_status(self):
        if self.scheduler.is_running:
            next_run = self.scheduler.get_next_run_time()
            if next_run:
                self._var_next_run.set(next_run.strftime("%Y-%m-%d %H:%M:%S"))
            self._set_status("计划运行中")
            self._btn_start.config(state="disabled")
            self._btn_stop.config(state="normal")
        else:
            self._var_next_run.set("（计划未启动）")
            self._btn_start.config(state="normal")
            self._btn_stop.config(state="disabled")

    def _set_status(self, text):
        self._status_var.set(text)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = App()
    app.run()
