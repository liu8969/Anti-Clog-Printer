#!/usr/bin/env python3
"""Docker HEALTHCHECK：探测 Web 管理端是否存活。

退出码 0 = 健康：
  - HTTP 200（未启用 Basic Auth），或
  - HTTP 401（已启用 Basic Auth，服务在正常响应）
退出码 1 = 不健康：连接被拒 / 超时 / 其他状态码
"""
import urllib.error
import urllib.request

try:
    resp = urllib.request.urlopen("http://127.0.0.1:18080/", timeout=4)
    raise SystemExit(0 if resp.status == 200 else 1)
except urllib.error.HTTPError as e:
    raise SystemExit(0 if e.code == 401 else 1)
except Exception:
    raise SystemExit(1)
