"""常驻 mock：本机订阅服务 + Clash External Controller（GUI 实测用）。端口 19097。"""
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SUB_YAML = """
proxies:
  - {name: "🇭🇰 香港 01", type: ss, server: hk1.example.com, port: 8388}
  - {name: "🇯🇵 日本 02", type: vmess, server: jp1.example.com, port: 443}
  - {name: "🇺🇸 美国 03", type: trojan, server: us1.example.com, port: 443}
  - {name: "🇸🇬 新加坡 04", type: ss, server: sg1.example.com, port: 8388}
"""
PROXIES = {
    "🚀 节点选择": {"type": "Selector", "now": "🇭🇰 香港 01", "all": ["🇭🇰 香港 01", "🇯🇵 日本 02", "🇺🇸 美国 03", "🇸🇬 新加坡 04", "DIRECT"]},
    "🇭🇰 香港 01": {"type": "Shadowsocks"},
    "🇯🇵 日本 02": {"type": "VMess"},
    "🇺🇸 美国 03": {"type": "Trojan"},
    "🇸🇬 新加坡 04": {"type": "Shadowsocks"},
    "DIRECT": {"type": "Direct"},
}
current = {"now": "🇭🇰 香港 01"}
DELAYS = {"🇯🇵 日本 02": 88, "🇭🇰 香港 01": 150, "🇸🇬 新加坡 04": 320}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Type", "application/json" if raw is None else "text/yaml")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/sub":
            self._send(200, raw=SUB_YAML.encode())
        elif self.path == "/proxies":
            merged = {k: dict(v) for k, v in PROXIES.items()}
            merged["🚀 节点选择"]["now"] = current["now"]
            self._send(200, {"proxies": merged})
        elif "/delay" in self.path:
            name = urllib.parse.unquote(self.path.split("/proxies/")[1].split("/delay")[0])
            if name in DELAYS:
                self._send(200, {"delay": DELAYS[name]})
            else:
                self._send(504, {"message": "timeout"})
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


if __name__ == "__main__":
    print("mock clash services on http://127.0.0.1:19097  (订阅: /sub)")
    ThreadingHTTPServer(("127.0.0.1", 19097), Handler).serve_forever()
