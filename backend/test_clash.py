"""订阅解析 + Clash 集成单测（mock controller）：不依赖真实订阅与真实 Clash。"""
import base64
import json
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import yaml

from app.clash import extract_groups, group_candidates, parse_subscription
from app.schemas import ClashSettings

# ---------------- 1) 订阅解析：Clash YAML ----------------

CLASH_YAML = """
proxies:
  - name: "🇭🇰 香港 01"
    type: ss
    server: hk1.example.com
    port: 8388
  - name: "🇯🇵 日本 02"
    type: vmess
    server: jp1.example.com
    port: 443
  - name: "🇺🇸 美国 03"
    type: trojan
    server: us1.example.com
    port: 443
proxy-groups:
  - name: "🚀 节点选择"
    type: select
    proxies: ["🇭🇰 香港 01", "🇯🇵 日本 02"]
"""

nodes = parse_subscription(CLASH_YAML.encode())
assert len(nodes) == 3, nodes
assert nodes[0]["name"] == "🇭🇰 香港 01" and nodes[0]["type"] == "ss" and nodes[0]["server"] == "hk1.example.com"
print("✅ Clash YAML 解析:", [n["name"] for n in nodes])

# ---------------- 2) 订阅解析：Base64 分享链接 ----------------

lines = [
    "ss://YWVzLTI1Ni1nY206cGFzcw@hk2.example.com:8388#" + urllib.parse.quote("🇸🇬 新加坡 01"),
    "trojan://pwd@us2.example.com:443?sni=a.com#" + urllib.parse.quote("🇺🇸 美国 04"),
]
b64 = base64.b64encode("\n".join(lines).encode()).decode()
nodes2 = parse_subscription(b64.encode())
assert len(nodes2) == 2, nodes2
assert nodes2[0]["name"] == "🇸🇬 新加坡 01", nodes2[0]
print("✅ Base64 分享链接解析:", [n["name"] for n in nodes2])

# ---------------- 3) mock External Controller ----------------

MOCK_PROXIES = {
    "🚀 节点选择": {"type": "Selector", "now": "🇭🇰 香港 01", "all": ["🇭🇰 香港 01", "🇯🇵 日本 02", "🇺🇸 美国 03", "DIRECT"]},
    "🇭🇰 香港 01": {"type": "Shadowsocks", "history": []},
    "🇯🇵 日本 02": {"type": "VMess"},
    "🇺🇸 美国 03": {"type": "Trojan"},
    "DIRECT": {"type": "Direct"},
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
        if self.path == "/proxies":
            merged = {**{k: dict(v) for k, v in MOCK_PROXIES.items()}}
            merged["🚀 节点选择"]["now"] = current["now"]
            self._send(200, {"proxies": merged})
        elif "/delay" in self.path:
            name = urllib.parse.unquote(self.path.split("/proxies/")[1].split("/delay")[0])
            # 模拟：日本最快 88ms，香港 150ms，美国超时
            delays = {"🇯🇵 日本 02": 88, "🇭🇰 香港 01": 150}
            if name in delays:
                self._send(200, {"delay": delays[name]})
            else:
                self._send(504, {"message": "timeout"})
        else:
            self._send(404, {})

    def do_PUT(self):
        if self.path.startswith("/proxies/"):
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            current["now"] = body.get("name")
            self._send(204)
        else:
            self._send(404, {})

    def log_message(self, *a):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 19097), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
time.sleep(0.3)

clash = ClashSettings(controllerUrl="http://127.0.0.1:19097", secret="")
import asyncio

from app.clash import get_all_proxies, select_node, test_delays


async def main():
    proxies = await get_all_proxies(clash)
    groups = extract_groups(proxies)
    assert groups[0]["name"] == "🚀 节点选择" and groups[0]["now"] == "🇭🇰 香港 01", groups
    cands = group_candidates(groups[0], proxies)
    assert cands == ["🇭🇰 香港 01", "🇯🇵 日本 02", "🇺🇸 美国 03"], cands
    print("✅ 分组提取:", groups[0]["name"], "候选:", cands)

    results = await test_delays(clash, cands)
    ok = {r["name"]: r["delayMs"] for r in results}
    assert ok == {"🇭🇰 香港 01": 150, "🇯🇵 日本 02": 88, "🇺🇸 美国 03": None}, ok
    print("✅ 并发测速:", ok)

    await select_node(clash, "🚀 节点选择", "🇯🇵 日本 02")
    assert current["now"] == "🇯🇵 日本 02", current
    print("✅ 切换节点: 当前 =", current["now"])


asyncio.run(main())
server.shutdown()
print("\n全部单测 ✅ PASS")
