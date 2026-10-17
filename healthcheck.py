#!/usr/bin/env python3
"""Docker HEALTHCHECK：探测 Web 管理端是否存活。

历史教训（2026-10，ubuntu-dev）：探针原来打的是 "/"（NiceGUI 首页）。NiceGUI 会为
每个 HTTP 客户端创建页面/timer，Docker 每 30~35 秒探一次，2.8 天累积了 8037 个线程，
guest 的 load average 被拖到 1630。现在探 "/healthz"：纯 FastAPI 路由，不创建 UI 客户端。

退出码 0 = 健康：
  - HTTP 200（未启用 Basic Auth），或
  - HTTP 401（已启用 Basic Auth，服务在正常响应）
退出码 1 = 不健康：连接被拒 / 超时 / 其他状态码
"""
import os
import urllib.error
import urllib.request

DEFAULT_URL = "http://127.0.0.1:18080/healthz"
HEALTHCHECK_URL = os.environ.get("HEALTHCHECK_URL", DEFAULT_URL)


def check(url=HEALTHCHECK_URL, timeout=4):
    """返回进程退出码：0 健康，1 不健康。"""
    try:
        resp = urllib.request.urlopen(url, timeout=timeout)
        return 0 if resp.status == 200 else 1
    except urllib.error.HTTPError as e:
        return 0 if e.code == 401 else 1
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(check())
