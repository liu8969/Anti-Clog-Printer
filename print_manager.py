"""IPP 直连打印管理模块 — 每次打印用完即断，只用 JPEG"""

import subprocess
import os

IPPTEST_DIR = "/usr/share/cups/ipptool"
TEMP_PRINTER_NAME = "_auto_anti_clog_temp"


class PrintManager:
    """通过 IPP 直连打印机，CUPS 作为兜底，只用 JPEG"""

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

    def _run_ipptool(self, uri, test_file, input_file=None, timeout=5):
        cmd = ["ipptool", "-t"]
        if input_file:
            cmd += ["-f", input_file]
        cmd += [uri, os.path.join(IPPTEST_DIR, test_file)]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
            )
            output = (result.stdout.strip() + "\n" + result.stderr.strip()).strip()
            return result.returncode == 0, output
        except FileNotFoundError:
            return False, "ipptool 不可用"
        except subprocess.TimeoutExpired:
            return False, f"连接超时 ({timeout}s)"
        except Exception as e:
            return False, str(e)

    # ------------------------------------------------------------------ #
    #  公开方法
    # ------------------------------------------------------------------ #

    def test_connection(self):
        uri = self._uri()
        if not uri:
            return False, "请先填写打印机 IP 地址"

        for alt_uri in self._uri_alt_paths():
            ok, _ = self._run_ipptool(alt_uri, "get-printer-attributes.test")
            if ok:
                return True, f"打印机连接成功 (IPP)"

        return False, "无法连接打印机"

    def print_file(self, jpg_path):
        """
        向打印机发送 JPEG 文件。
        优先 IPP 直连，失败后 CUPS 兜底。
        返回 (success, message) — message 中明确标注 [IPP] 或 [CUPS]。
        """
        lines = []

        if not self._uri():
            return False, "请先填写打印机 IP 地址"

        if not os.path.exists(jpg_path):
            return False, f"文件不存在: {jpg_path}"

        # —— 首选: IPP 直连 JPEG ——
        ok, out = self._try_ipp_print(jpg_path, lines)
        if ok:
            return True, "\n".join(lines)

        # —— 兜底: CUPS 临时打印机 ——
        lines.append("--- 回退到 CUPS ---")
        ok, msg = self._cups_print(jpg_path)
        if ok:
            lines.append(f"[CUPS] {msg}")
            return True, "\n".join(lines)

        lines.append(f"[CUPS] 失败: {msg}")
        return False, "\n".join(lines)

    def _try_ipp_print(self, jpg_path, lines):
        """尝试 IPP 直连所有路径（打印任务给更长超时，避免慢网络误判）"""
        uris = self._uri_alt_paths()
        lines.append(f"[IPP] 直连 JPEG ({len(uris)} 个路径)")
        for i, u in enumerate(uris):
            ok, out = self._run_ipptool(u, "print-job.test", input_file=jpg_path, timeout=30)
            if ok:
                lines.append(f"[IPP] 路径 {i+1} OK → 打印成功")
                return True, out
            else:
                short = out.replace("\n", " ")[:80]
                lines.append(f"[IPP] 路径 {i+1} 失败: {short}")
        return False, out

    # ------------------------------------------------------------------ #
    #  CUPS 兜底
    # ------------------------------------------------------------------ #

    def _cups_print(self, jpg_path):
        uri = self._uri()

        # 添加临时打印机
        added = False
        for args, timeout in (
            (["lpadmin", "-p", TEMP_PRINTER_NAME, "-v", uri, "-E", "-m", "raw"], 10),
            (["lpadmin", "-p", TEMP_PRINTER_NAME, "-v", uri, "-E", "-m", "everywhere"], 25),
            (["lpadmin", "-p", TEMP_PRINTER_NAME, "-v", uri, "-E"], 10),
        ):
            try:
                r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
                if r.returncode == 0:
                    added = True
                    break
            except Exception:
                continue

        if not added:
            return False, "lpadmin 添加临时打印机失败"

        # 发送打印；无论成败都清理临时打印机（finally）
        lp = None
        lp_fail = "lp 打印超时 (60s)"
        try:
            lp = subprocess.run(
                ["lp", "-d", TEMP_PRINTER_NAME, jpg_path],
                capture_output=True, text=True, timeout=60,
            )
        except subprocess.TimeoutExpired:
            lp = None
        finally:
            subprocess.run(
                ["lpadmin", "-x", TEMP_PRINTER_NAME],
                capture_output=True, text=True, timeout=10,
            )

        if lp is not None and lp.returncode == 0:
            return True, "打印成功"
        elif lp is not None:
            return False, lp.stderr.strip() or lp.stdout.strip()
        else:
            return False, lp_fail
