"""Clash Verge 集成：订阅解析 + External Controller API（获取分组/测延迟/切换节点）。

订阅格式兼容：
- Clash YAML（含 proxies: 列表）
- Base64 编码的节点分享链接列表（ss:// vmess:// trojan:// vless:// hysteria2:// 等）

节点测速与自动切换通过 Clash 的 External Controller（Verge 设置中需开启「外部控制」）。
"""
from __future__ import annotations

import asyncio
import base64
import json
import urllib.parse

import httpx
import yaml

from .schemas import ClashSettings, ProxySettings

TEST_URL = "http://www.gstatic.com/generate_204"


# ---------------- 订阅解析 ----------------


def parse_subscription(content: bytes) -> list[dict]:
    text = content.decode("utf-8", "replace")

    # 1) Clash YAML
    if "proxies:" in text:
        try:
            data = yaml.safe_load(text)
            out = []
            for p in (data or {}).get("proxies") or []:
                if isinstance(p, dict) and p.get("name"):
                    out.append(
                        {"name": str(p["name"]), "type": str(p.get("type") or ""), "server": str(p.get("server") or "")}
                    )
            if out:
                return out
        except Exception:
            pass

    # 2) Base64 编码的分享链接列表
    try:
        stripped = "".join(text.split())
        decoded = base64.b64decode(stripped + "=" * (-len(stripped) % 4)).decode("utf-8", "replace")
    except Exception:
        decoded = ""
    nodes: list[dict] = []
    for line in decoded.splitlines():
        line = line.strip()
        if "://" not in line:
            continue
        proto, _, rest = line.partition("://")
        proto = proto.lower()
        name = ""
        if proto == "vmess":
            try:
                b64 = rest.split("#")[0]
                obj = json.loads(base64.b64decode(b64 + "=" * (-len(b64) % 4)).decode("utf-8", "replace"))
                name = str(obj.get("ps") or "")
            except Exception:
                pass
        if not name and "#" in rest:
            name = urllib.parse.unquote(rest.split("#", 1)[1].split("?")[0])
        if not name:
            name = f"{proto} 节点"
        nodes.append({"name": name, "type": proto, "server": ""})
    return nodes


async def fetch_url(url: str, proxy: ProxySettings) -> bytes:
    """拉取订阅：localhost 直连；其余按代理设置出网。"""
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    kwargs: dict = {"timeout": 20, "follow_redirects": True}
    if host in ("localhost", "127.0.0.1", "::1"):
        kwargs["trust_env"] = False
    elif proxy.mode == "custom":
        kwargs.update(proxy=f"http://{proxy.host}:{proxy.port}", trust_env=False)
    elif proxy.mode == "none":
        kwargs["trust_env"] = False
    async with httpx.AsyncClient(**kwargs) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.content


# ---------------- External Controller ----------------


def _client(clash: ClashSettings) -> httpx.AsyncClient:
    headers = {"Authorization": f"Bearer {clash.secret}"} if clash.secret else {}
    return httpx.AsyncClient(
        base_url=clash.controllerUrl.rstrip("/"), headers=headers, trust_env=False, timeout=10
    )


async def get_all_proxies(clash: ClashSettings) -> dict[str, dict]:
    """返回 Clash 当前的全部代理/策略组：{name: {type, now?, all?}}。"""
    try:
        async with _client(clash) as c:
            r = await c.get("/proxies")
            r.raise_for_status()
            return (r.json().get("proxies")) or {}
    except Exception as e:
        raise RuntimeError(
            f"无法连接 Clash 外部控制器（{clash.controllerUrl}）：{e}。"
            "请在 Clash Verge 设置中开启「外部控制」，并核对外部控制地址与密钥。"
        ) from e


def extract_groups(proxies: dict[str, dict]) -> list[dict]:
    """提取全部策略组（Selector 类型），含当前选中与成员列表。"""
    groups = []
    for name, info in proxies.items():
        if info.get("type") == "Selector":
            groups.append({"name": name, "now": info.get("now"), "all": info.get("all") or []})
    return groups


def group_candidates(group: dict, proxies: dict[str, dict]) -> list[str]:
    """组内可参与自动选择的节点：排除 DIRECT/REJECT 与嵌套策略组。"""
    out = []
    for n in group.get("all") or []:
        info = proxies.get(n)
        if n in ("DIRECT", "REJECT", "REJECT-DROP", "PASS"):
            continue
        if info and info.get("type") in ("Selector", "URLTest", "Fallback", "LoadBalance", "Relay"):
            continue
        out.append(n)
    return out


async def test_delay(clash: ClashSettings, name: str, timeout_ms: int = 5000) -> int | None:
    path = "/proxies/" + urllib.parse.quote(name, safe="") + "/delay"
    try:
        async with _client(clash) as c:
            r = await c.get(path, params={"timeout": timeout_ms, "url": TEST_URL})
            if r.status_code == 200:
                return int(r.json().get("delay"))
    except Exception:
        return None
    return None


async def test_delays(clash: ClashSettings, names: list[str], timeout_ms: int = 5000, concurrency: int = 6) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)

    async def one(n: str) -> dict:
        async with sem:
            delay = await test_delay(clash, n, timeout_ms)
            return {"name": n, "delayMs": delay}

    return list(await asyncio.gather(*[one(n) for n in names]))


async def select_node(clash: ClashSettings, group: str, name: str) -> None:
    path = "/proxies/" + urllib.parse.quote(group, safe="")
    async with _client(clash) as c:
        r = await c.put(path, json={"name": name})
        if r.status_code not in (200, 204):
            raise RuntimeError(f"切换节点失败（HTTP {r.status_code}）：{r.text[:200]}")
