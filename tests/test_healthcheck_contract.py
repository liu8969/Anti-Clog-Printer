"""健康探针回归测试。

历史 bug：Docker HEALTHCHECK 探测 NiceGUI 首页 `/`，每 30~35 秒给应用创建一个
页面客户端/定时器，2.8 天累积了 8000+ 线程，把 ubuntu-dev 的 load 拖到 1600+。

这里把修复钉死：
- healthcheck.py 必须探测轻量 `/healthz`，且允许用 HEALTHCHECK_URL 指向测试服务器；
- web_main.py 必须暴露 `/healthz`；
- deploy.json 的 dpl 健康检查也必须用 `/healthz`；
- compose 加 pids_limit 作为第二道护栏。
"""

import http.server
import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class TestHealthcheckContract(unittest.TestCase):
    def test_healthcheck_script_probes_healthz(self):
        seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(self.path)
                self.send_response(200 if self.path == "/healthz" else 404)
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *_args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            env = os.environ.copy()
            env["HEALTHCHECK_URL"] = f"http://127.0.0.1:{server.server_port}/healthz"
            result = subprocess.run(
                [sys.executable, str(ROOT / "healthcheck.py")],
                env=env, capture_output=True, text=True, timeout=10,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(seen, ["/healthz"])

    def test_web_main_exposes_healthz_without_page(self):
        src = (ROOT / "web_main.py").read_text(encoding="utf-8")
        self.assertIn('@nicegui_app.get("/healthz")', src)

    def test_deploy_health_uses_healthz(self):
        spec = json.loads((ROOT / "deploy.json").read_text(encoding="utf-8"))
        self.assertEqual(spec["health"]["path"], "/healthz")

    def test_compose_bounds_threads(self):
        src = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("pids_limit: 512", src)


if __name__ == "__main__":
    unittest.main()
