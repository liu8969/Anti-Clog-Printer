"""IPP 直连打印管理模块 — 每次打印用完即断，不注册永久打印机"""

import subprocess
import os

IPPTEST_DIR = "/usr/share/cups/ipptool"
TEMP_PRINTER_NAME = "_auto_anti_clog_temp"


class PrintManager:
    """通过 ipptool 直连打印机，单次 HTTP 请求，无长连接"""

    def __init__(self, config):
        self._config = config

    # ------------------------------------------------------------------ #
    #  IPP URI
    # ------------------------------------------------------------------ #

    def _uri(self):
        return self._config.ipp_uri

    def _uri_alt_paths(self):
        ip = self._config.get("printer.ip", "").strip()
        port = self._config.get("printer.port", 631)
        if not ip:
            return []
        base = f"ipp://{ip}:{port}"
        custom = self._config.get("printer.ipp_path", "/ipp/print").strip()
        paths = [custom]
        for p in ["/ipp/print", "/ipp/printsl", "/ipp", "/printers/printer", "/ipp/printer"]:
            if p not in paths:
                paths.append(p)
        return [f"{base}{p}" for p in paths]

    def _run_ipptool(self, uri, test_file, input_file=None):
        cmd = ["ipptool", "-t"]
        if input_file:
            cmd += ["-f", input_file]
        cmd += [uri, os.path.join(IPPTEST_DIR, test_file)]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=5,
            )
            output = (result.stdout.strip() + "\n" + result.stderr.strip()).strip()
            return result.returncode == 0, output
        except FileNotFoundError:
            return False, "错误: ipptool 命令不可用"
        except subprocess.TimeoutExpired:
            return False, "错误: 连接打印机超时 (5s)"
        except Exception as e:
            return False, f"错误: {e}"

    # ------------------------------------------------------------------ #
    #  公开方法
    # ------------------------------------------------------------------ #

    def test_connection(self):
        uri = self._uri()
        if not uri:
            return False, "请先填写打印机 IP 地址"

        success, output = self._run_ipptool(uri, "get-printer-attributes.test")
        if success:
            return True, "打印机连接成功"

        for alt_uri in self._uri_alt_paths():
            if alt_uri == uri:
                continue
            success, _ = self._run_ipptool(alt_uri, "get-printer-attributes.test")
            if success:
                return True, f"打印机连接成功 (路径: {alt_uri})"

        return False, output

    def print_file(self, jpg_path, pdf_path):
        """
        向打印机发送文件。
        优先 JPEG（几乎所有 IPP 打印机支持），其次 PDF，最后 CUPS 临时打印机。
        返回 (success, message)
        """
        if not self._uri():
            return False, "请先填写打印机 IP 地址"

        # 方案 A: ipptool + JPEG（兼容性最好）
        if os.path.exists(jpg_path):
            ok, out = self._try_ipptool_print(jpg_path)
            if ok:
                return True, "打印任务已发送 (IPP/JPEG)"

        # 方案 B: ipptool + PDF
        if os.path.exists(pdf_path):
            ok, out = self._try_ipptool_print(pdf_path)
            if ok:
                return True, "打印任务已发送 (IPP/PDF)"

        # 方案 C: CUPS 临时打印机
        target = jpg_path if os.path.exists(jpg_path) else pdf_path
        ok, msg = self._cups_temp_print(target)
        if ok:
            return True, msg

        return False, f"打印失败。\nIPP: {out[:300]}\nCUPS: {msg}"

    def _try_ipptool_print(self, file_path):
        """在所有已知 IPP 路径上尝试 ipptool print-job"""
        for uri in self._uri_alt_paths():
            ok, out = self._run_ipptool(uri, "print-job.test", input_file=file_path)
            if ok:
                return True, out
        return False, out

    # ------------------------------------------------------------------ #
    #  CUPS 临时打印机方案
    # ------------------------------------------------------------------ #

    def _cups_temp_print(self, file_path):
        uri = self._uri()
        if not self._try_add_temp_printer(uri):
            return False, "无法添加临时打印机 (lpadmin 失败)"

        lp_result = subprocess.run(
            ["lp", "-d", TEMP_PRINTER_NAME, "-o", "ColorModel=CMYK", file_path],
            capture_output=True, text=True, timeout=60,
        )
        self._cleanup_temp_printer()

        if lp_result.returncode == 0:
            return True, "打印任务已发送 (CUPS/IPP)"
        else:
            msg = lp_result.stderr.strip() or lp_result.stdout.strip()
            return False, f"lp 发送失败: {msg}"

    def _try_add_temp_printer(self, uri):
        strategies = [
            (["lpadmin", "-p", TEMP_PRINTER_NAME, "-v", uri, "-E", "-m", "raw"], 10),
            (["lpadmin", "-p", TEMP_PRINTER_NAME, "-v", uri, "-E", "-m", "everywhere"], 25),
            (["lpadmin", "-p", TEMP_PRINTER_NAME, "-v", uri, "-E"], 10),
        ]
        for cmd, timeout in strategies:
            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout,
                )
                if result.returncode == 0:
                    return True
            except (subprocess.TimeoutExpired, Exception):
                continue
        return False

    def _cleanup_temp_printer(self):
        subprocess.run(
            ["lpadmin", "-x", TEMP_PRINTER_NAME],
            capture_output=True, text=True, timeout=10,
        )
