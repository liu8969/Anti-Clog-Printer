"""IPP 直连打印管理模块 — 每次打印用完即断，只用 JPEG

探测策略：先用 5 秒短超时对所有候选 URI 做 Get-Printer-Attributes 探测
（IPPS 优先、其次 IPP，自定义路径在前），找到可达 URI 后再用 30 秒长超时
发送 Print-Job。避免"打印机只支持 IPPS"时每个路径都空等 30 秒超时。
"""

import subprocess
import os

IPPTEST_DIR = "/usr/share/cups/ipptool"
TEMP_PRINTER_NAME = "_auto_anti_clog_temp"

# 常见 IPP 服务路径（自定义路径永远排最前）
_KNOWN_PATHS = ["/ipp/print", "/ipp/printsl", "/ipp", "/printers/printer", "/ipp/printer"]


class PrintManager:
    """通过 IPP 直连打印机，CUPS 作为兜底，只用 JPEG"""

    def __init__(self, config):
        self._config = config

    # ------------------------------------------------------------------ #
    #  IPP URI
    # ------------------------------------------------------------------ #

    def _uri(self):
        return self._config.ipp_uri

    def _uri_candidates(self):
        """候选 IPP URI 列表：每个路径先 IPPS 后 IPP，去重。

        IPPS 优先是因为很多打印机强制 HTTPS；旧实现只试 ipp://，
        对仅支持 IPPS 的打印机"测试连接"必然失败。
        """
        ip = self._config.get("printer.ip", "").strip()
        port = self._config.get("printer.port", 631)
        if not ip:
            return []
        custom = self._config.get("printer.ipp_path", "/ipp/print").strip()
        paths = []
        for p in [custom] + _KNOWN_PATHS:
            if p and p not in paths:
                paths.append(p)
        uris = []
        for p in paths:
            uris.append(f"ipps://{ip}:{port}{p}")
            uris.append(f"ipp://{ip}:{port}{p}")
        return uris

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
        if not self._uri():
            return False, "请先填写打印机 IP 地址"

        for uri in self._uri_candidates():
            ok, _ = self._run_ipptool(uri, "get-printer-attributes.test", timeout=5)
            if ok:
                return True, f"打印机连接成功 ({uri.split('://')[0].upper()})"

        return False, "无法连接打印机（已尝试 IPPS/IPP 多个路径）"

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
        ok = self._try_ipp_print(jpg_path, lines)
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
        """探测可达 URI 后发送打印（打印任务给更长超时，避免慢网络误判）"""
        candidates = self._uri_candidates()
        if not candidates:
            lines.append("[IPP] 未配置打印机 IP，跳过直连")
            return False

        # 第一阶段：短超时探测（5s/个），找到打印机真正响应的 URI
        probed = []
        for i, uri in enumerate(candidates):
            ok, out = self._run_ipptool(uri, "get-printer-attributes.test", timeout=5)
            if ok:
                probed.append(uri)
                lines.append(f"[IPP] 探测 {i+1} {uri} → 可达")
                break  # 找到即可，打印只需一个工作 URI
            elif len(probed) == 0 and i < 2:
                # 只记录前两个失败细节，避免日志过长
                short = out.replace("\n", " ")[:60]
                lines.append(f"[IPP] 探测 {i+1} {uri} 失败: {short}")
        if not probed:
            lines.append(f"[IPP] 探测 {len(candidates)} 个候选 URI 均不可达")

        # 第二阶段：在工作 URI 上发送打印（30s 长超时）
        targets = probed or candidates[:3]
        last_out = ""
        for uri in targets:
            ok, out = self._run_ipptool(uri, "print-job.test", input_file=jpg_path, timeout=30)
            last_out = out
            if ok:
                lines.append(f"[IPP] {uri} → 打印成功")
                return True
            short = out.replace("\n", " ")[:80]
            lines.append(f"[IPP] {uri} 打印失败: {short}")
        return False

    # ------------------------------------------------------------------ #
    #  CUPS 兜底
    # ------------------------------------------------------------------ #

    def _cups_print(self, jpg_path):
        # CUPS 兜底同样先试 IPPS（仅支持 IPPS 的打印机 ipp:// 会失败）
        base = self._uri()
        if base.startswith("ipp://"):
            uris = [base.replace("ipp://", "ipps://", 1), base]
        else:
            uris = [base]

        # 添加临时打印机
        added = False
        for uri in uris:
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
            if added:
                break

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
            try:
                subprocess.run(
                    ["lpadmin", "-x", TEMP_PRINTER_NAME],
                    capture_output=True, text=True, timeout=10,
                )
            except Exception:
                pass

        if lp is not None and lp.returncode == 0:
            return True, "打印成功"
        elif lp is not None:
            return False, lp.stderr.strip() or lp.stdout.strip()
        else:
            return False, lp_fail
