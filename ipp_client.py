"""纯 Python IPP 客户端 — 无 CUPS/ipptool 依赖，跨平台可用"""

import os
import struct
import ssl
import urllib.request
import urllib.error


# 默认跳过打印机自签名证书验证（局域网打印机普遍如此）
# 设置环境变量 IPP_VERIFY_SSL=1 可开启标准证书校验
_SSL_CONTEXT = ssl._create_unverified_context()
_VERIFY_SSL = os.environ.get("IPP_VERIFY_SSL", "").strip().lower() in ("1", "true", "yes", "on")


def _get_ssl_context():
    if _VERIFY_SSL:
        return ssl.create_default_context()
    return _SSL_CONTEXT


def _attr_str(value_tag, name, value):
    nb = name.encode("utf-8")
    vb = value.encode("utf-8")
    return (
        struct.pack(">B", value_tag)
        + struct.pack(">H", len(nb)) + nb
        + struct.pack(">H", len(vb)) + vb
    )


def _attr_int(value_tag, name, value):
    nb = name.encode("utf-8")
    return (
        struct.pack(">B", value_tag)
        + struct.pack(">H", len(nb)) + nb
        + struct.pack(">H", 4) + struct.pack(">I", value)
    )


def build_print_job_body(printer_uri, jpeg_bytes):
    """构造 IPP Print-Job 请求的二进制 body"""
    parts = [
        b"\x02\x00", b"\x00\x02", b"\x00\x00\x00\x01",
        b"\x01"
        + _attr_str(0x47, "attributes-charset", "utf-8")
        + _attr_str(0x48, "attributes-natural-language", "en")
        + _attr_str(0x45, "printer-uri", printer_uri)
        + _attr_str(0x42, "requesting-user-name", "docker")
        + _attr_str(0x49, "document-format", "image/jpeg"),
        b"\x02" + _attr_int(0x21, "copies", 1),
        b"\x03",
        jpeg_bytes,
    ]
    return b"".join(parts)


def build_get_attrs_body(printer_uri):
    """构造 Get-Printer-Attributes 请求"""
    parts = [
        b"\x02\x00", b"\x00\x0b", b"\x00\x00\x00\x01",
        b"\x01"
        + _attr_str(0x47, "attributes-charset", "utf-8")
        + _attr_str(0x48, "attributes-natural-language", "en")
        + _attr_str(0x45, "printer-uri", printer_uri)
        + _attr_str(0x42, "requesting-user-name", "docker"),
        b"\x03",
    ]
    return b"".join(parts)


# IPP 状态码 0x0000（successful-ok）/ 0x0001（successful-ok-but-warnings）视为成功
def _ipp_success(status):
    return status in ("OK", "OK (有警告)")


def _parse_ipp_status(raw):
    """解析 IPP 响应状态码"""
    if len(raw) >= 4:
        status = struct.unpack(">H", raw[2:4])[0]
        if status == 0x0000:
            return "OK"
        if status == 0x0001:
            return "OK (有警告)"
        return f"IPP 状态码 0x{status:04X}"
    return "响应异常"


def _ipp_request(ip, port, ipp_path, body_factory, timeout):
    """
    发送 IPP 请求，先尝试 IPPS (HTTPS)，再尝试 IPP (HTTP)。
    body_factory(printer_uri) 用于按实际传输 scheme 构造请求体，
    保证 printer-uri 属性与传输层一致（严格实现的打印机要求如此）。
    """
    path = ipp_path.rstrip("/")

    # 优先 IPPS（HTTPS），因为很多打印机强制 HTTPS
    for scheme in ("https", "http"):
        printer_uri = (
            f"ipps://{ip}:{port}{path}" if scheme == "https"
            else f"ipp://{ip}:{port}{path}"
        )
        body = body_factory(printer_uri)
        url = f"{scheme}://{ip}:{port}{path}"
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/ipp"}, method="POST"
        )
        try:
            ctx = _get_ssl_context() if scheme == "https" else None
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read()
                return True, _parse_ipp_status(raw), scheme
        except urllib.error.HTTPError as e:
            if scheme == "https":
                # HTTPS 端口返回普通 HTTP 错误（多半不是 IPPS 服务），降级试 HTTP
                continue
            if e.code == 426:  # Upgrade Required → 打印机要求 HTTPS，但 HTTPS 已失败
                return False, "打印机要求 HTTPS 升级，但 HTTPS 连接失败，请检查端口/路径配置", scheme
            return False, f"HTTP {e.code}", scheme
        except urllib.error.URLError as e:
            if scheme == "https":
                continue  # HTTPS 连不上，试试 HTTP
            return False, str(e.reason), scheme
        except Exception as e:
            if scheme == "https":
                continue
            return False, str(e), scheme

    return False, "IPP/IPPS 均无法连接", "?"


# ------------------------------------------------------------------ #
#  公开接口
# ------------------------------------------------------------------ #

def send_print_job(ip, port, ipp_path, jpeg_bytes, timeout=30):
    """发送 IPP Print-Job，返回 (success, message)

    仅当 HTTP 层正常 且 IPP 状态码为 0x0000/0x0001 时才判定成功：
    打印机常用 HTTP 200 + IPP 错误状态码表示拒绝作业（如离线/配置错误），
    只检查 HTTP 层会把这类失败误报为"打印成功"。
    """
    def _build(printer_uri):
        return build_print_job_body(printer_uri, jpeg_bytes)

    ok, status, scheme = _ipp_request(ip, port, ipp_path, _build, timeout)
    label = "IPPS" if scheme == "https" else "IPP"
    if not ok:
        return False, f"[{label}] {status}"
    if not _ipp_success(status):
        return False, f"[{label}] 打印机拒绝作业: {status}"
    return True, f"打印成功 ({label})"


def test_printer_connection(ip, port=631, ipp_path="/ipp/print", timeout=5):
    """获取打印机属性测试连接，返回 (success, message)"""
    def _build(printer_uri):
        return build_get_attrs_body(printer_uri)

    ok, status, scheme = _ipp_request(ip, port, ipp_path, _build, timeout)
    label = "IPPS" if scheme == "https" else "IPP"
    if not ok:
        return False, f"[{label}] {status}"
    if not _ipp_success(status):
        # 网络可达但 IPP 层报错：通常是 IPP 路径不对或打印机未就绪
        return False, f"[{label}] 网络可达但打印机返回 {status}（请检查 IPP 路径/打印机状态）"
    return True, f"打印机连接成功 ({label})"
