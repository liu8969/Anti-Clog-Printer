"""纯 Python IPP 客户端 — 无 CUPS/ipptool 依赖，跨平台可用"""

import struct
import ssl
import urllib.request
import urllib.error


# 跳过打印机自签名证书验证
_SSL_CONTEXT = ssl._create_unverified_context()


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


def _ipp_request(ip, port, ipp_path, body, timeout):
    """
    发送 IPP 请求，先尝试 IPPS (HTTPS)，再尝试 IPP (HTTP)。
    打印机通常使用 IPPS，自签名证书需要跳过验证。
    """
    path = ipp_path.rstrip("/")

    # 优先 IPPS（HTTPS），因为很多打印机强制 HTTPS
    for scheme in ("https", "http"):
        url = f"{scheme}://{ip}:{port}{path}"
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/ipp"}, method="POST"
        )
        try:
            ctx = _SSL_CONTEXT if scheme == "https" else None
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read()
                return True, _parse_ipp_status(raw), scheme
        except urllib.error.HTTPError as e:
            if e.code == 426:  # Upgrade Required → 说明要 HTTPS
                continue
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


def _parse_ipp_status(raw):
    """解析 IPP 响应状态码"""
    if len(raw) >= 4:
        status = struct.unpack(">H", raw[2:4])[0]
        if status == 0x0000:
            return "OK"
        return f"IPP 状态码 0x{status:04X}"
    return "响应异常"


# ------------------------------------------------------------------ #
#  公开接口
# ------------------------------------------------------------------ #

def send_print_job(ip, port, ipp_path, jpeg_bytes, timeout=30):
    """发送 IPP Print-Job，返回 (success, message)"""
    printer_uri = f"ipp://{ip}:{port}{ipp_path}"
    body = build_print_job_body(printer_uri, jpeg_bytes)

    ok, status, scheme = _ipp_request(ip, port, ipp_path, body, timeout)
    if ok:
        return True, f"打印成功 (IPPS)" if scheme == "https" else "打印成功 (IPP)"
    else:
        return False, f"[{scheme.upper()}] {status}"


def test_printer_connection(ip, port=631, ipp_path="/ipp/print", timeout=5):
    """获取打印机属性测试连接，返回 (success, message)"""
    printer_uri = f"ipp://{ip}:{port}{ipp_path}"
    body = build_get_attrs_body(printer_uri)

    ok, status, scheme = _ipp_request(ip, port, ipp_path, body, timeout)
    if ok:
        label = "IPPS" if scheme == "https" else "IPP"
        return True, f"打印机连接成功 ({label})"
    else:
        return False, f"[{scheme.upper()}] {status}"
