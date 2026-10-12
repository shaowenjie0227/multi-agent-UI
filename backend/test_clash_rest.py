"""REST 层冒烟：订阅解析端点 + Clash auto-select 端点，全链路走 HTTP。"""
import asyncio
import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx

B = "http://localhost:3001"
c = httpx.Client(base_url=B, timeout=15, trust_env=False)

SUB_YAML = """
proxies:
  - {name: "🇭🇰 香港 01", type: ss, server: hk1.example.com, port: 8388}
  - {name: "🇯🇵 日本 02", type: vmess, server: jp1.example.com, port: 443}
  - {name: "🇺🇸 美国 03", type: trojan, server: us1.example.com, port: 443}
"""
MOCK_PROXIES = {
    "🚀 节点选择": {"type": "Selector", "now": "🇭🇰 香港 01", "all": ["🇭🇰 香港 01", "🇯🇵 日本 02", "🇺🇸 美国 03"]},
    "🇭🇰 香港 01": {"type": "Shadowsocks"},
    "🇯🇵 日本 02": {"type": "VMess"},
    "🇺🇸 美国 03": {"type": "Trojan"},
}
current = {"now": "🇭🇰 香港 01"}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body=None):
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/sub":
            body = SUB_YAML.encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/proxies":
            merged = {k: dict(v) for k, v in MOCK_PROXIES.items()}
            merged["🚀 节点选择"]["now"] = current["now"]
            self._send(200, {"proxies": merged})
        elif "/delay" in self.path:
            name = urllib.parse.unquote(self.path.split("/proxies/")[1].split("/delay")[0])
            delays = {"🇯🇵 日本 02": 88, "🇭🇰 香港 01": 150}
            self._send(200, {"delay": delays[name]}) if name in delays else self._send(504, {})
        else:
            self._send(404, {})

    def do_PUT(self):
        if self.path.startswith("/proxies/"):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            current["now"] = body.get("name")
            self._send(204)
        else:
            self._send(404, {})

    def log_message(self, *a):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 19097), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
time.sleep(0.3)

try:
    # 保存原 controller 设置，指向 mock
    old = c.get("/api/settings").json()
    c.put("/api/settings", json={"clash": {"controllerUrl": "http://127.0.0.1:19097", "secret": ""}})

    # 1) 订阅解析
    r = c.post("/api/clash/subscription", json={"url": "http://127.0.0.1:19097/sub"})
    assert r.status_code == 200, r.text
    nodes = r.json()["nodes"]
    assert [n["name"] for n in nodes] == ["🇭🇰 香港 01", "🇯🇵 日本 02", "🇺🇸 美国 03"], nodes
    print("✅ POST /api/clash/subscription →", len(nodes), "节点")

    # 2) 分组
    r = c.get("/api/clash/groups")
    assert r.status_code == 200 and r.json()["groups"][0]["name"] == "🚀 节点选择", r.text
    print("✅ GET /api/clash/groups →", r.json()["groups"][0]["name"])

    # 3) 自动选最快（期望 🇯🇵 日本 02 @88ms）
    r = c.post("/api/clash/auto-select", json={"group": "🚀 节点选择", "name": ""})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["selected"] == "🇯🇵 日本 02" and data["delayMs"] == 88, data
    assert current["now"] == "🇯🇵 日本 02"
    print("✅ POST /api/clash/auto-select →", data["selected"], f"({data['delayMs']}ms)，Clash 组已切换")

    print("\nREST 冒烟 ✅ PASS")
finally:
    server.shutdown()
    c.put("/api/settings", json={"clash": old["clash"]})
    print("已恢复 controller 设置:", c.get("/api/settings").json()["clash"])
