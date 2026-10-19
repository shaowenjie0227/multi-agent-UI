"""FastAPI 入口：配置管理 REST + 运行控制 REST + WebSocket 事件推送。"""
from __future__ import annotations

import asyncio
import hmac
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .clash import (
    extract_groups,
    fetch_url,
    get_all_proxies,
    group_candidates,
    parse_subscription,
    select_node,
    test_delays,
)
from .engine.bus import EventBus, Run
from .engine.orchestrator import run_flow
from .schemas import (
    Agent,
    AgentIn,
    AgentUpdate,
    ClashDelayIn,
    ClashSelectIn,
    ModelIn,
    Provider,
    ProviderIn,
    ProviderModel,
    ProviderUpdate,
    RecommendIn,
    RunEvent,
    RunInputIn,
    RunMeta,
    RunStartIn,
    SettingsUpdate,
    SubscriptionIn,
)
from .selector import load_knowledge, recommend
from .store import (
    DATA_DIR,
    Store,
    delete_run_file,
    load_run_events,
    load_run_meta,
    load_run_metas,
    new_id,
    now,
    reconcile_stale_runs,
)
from .workspace import Workspace

WORKSPACE_DIR = DATA_DIR / "workspace"

store = Store()
bus = EventBus()
RUNS: dict[str, Run] = {}
TASKS: dict[str, asyncio.Task] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 上次进程退出时仍在跑的运行不可能继续推进，启动时收敛，避免历史列表永远显示"运行中"
    reconcile_stale_runs()
    yield


app = FastAPI(title="Multi-Agent Studio", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

PUBLIC_PATHS = {"/api/settings"}  # 前端需要在拿到 token 前读取设置来判断是否已启用鉴权


def _expected_token() -> str:
    return (store.settings.auth.token or "").strip()


def _token_ok(token: str) -> bool:
    expected = _expected_token()
    return not expected or hmac.compare_digest(token or "", expected)


@app.middleware("http")
async def auth_middleware(request, call_next):
    """可选鉴权：settings.auth.token 为空时完全放行（默认本机使用）；
    设置后要求 Authorization: Bearer <token>（或 ?token= / X-Auth-Token）。"""
    if not _expected_token():
        return await call_next(request)
    path = request.url.path
    if not path.startswith("/api") or path in PUBLIC_PATHS:
        return await call_next(request)
    token = ""
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        token = header[7:].strip()
    token = token or request.headers.get("x-auth-token", "") or request.query_params.get("token", "")
    if not _token_ok(token):
        return JSONResponse({"detail": "未授权：请在界面中填写访问令牌"}, status_code=401)
    return await call_next(request)


def _mask_key(key: str) -> str:
    """API Key 只回传掩码，前端保存时若原样回传掩码则保留真实值（避免配置界面泄露明文）。"""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * (len(key) - 8)}{key[-4:]}"


def _provider_out(p: Provider) -> dict:
    return {**p.model_dump(), "apiKey": _mask_key(p.apiKey), "hasApiKey": bool(p.apiKey)}


def _is_masked(value: str) -> bool:
    return "*" in (value or "")



# ---------------- 供应商 / 模型 ----------------


@app.get("/api/providers")
def get_providers():
    return {"providers": [_provider_out(p) for p in store.providers], "models": store.models}


@app.post("/api/providers")
def create_provider(body: ProviderIn):
    p = Provider(id=new_id("p_"), **body.model_dump())
    store.add_provider(p)
    return _provider_out(p)


@app.put("/api/providers/{pid}")
def update_provider(pid: str, body: ProviderUpdate):
    patch = body.model_dump(exclude_unset=True)
    # 前端拿到的是掩码；原样回传掩码视为"不修改密钥"
    if "apiKey" in patch and _is_masked(patch["apiKey"] or ""):
        patch.pop("apiKey")
    p = store.update_provider(pid, patch)
    if not p:
        raise HTTPException(404, "供应商不存在")
    # 供应商配置变化后，旧的 OpenAI 客户端缓存（含连接池）已失效
    from .providers.openai_compat import invalidate_client
    invalidate_client(pid)
    return _provider_out(p)


@app.delete("/api/providers/{pid}")
def delete_provider(pid: str):
    if not store.delete_provider(pid):
        raise HTTPException(404, "供应商不存在")
    from .providers.openai_compat import invalidate_client
    invalidate_client(pid)
    return {"ok": True}


@app.post("/api/providers/{pid}/models")
def create_model(pid: str, body: ModelIn):
    if not store.find_provider(pid):
        raise HTTPException(404, "供应商不存在")
    if not body.name.strip():
        raise HTTPException(400, "模型名不能为空")
    m = ProviderModel(id=new_id("m_"), providerId=pid, name=body.name.strip(), note=body.note)
    return store.add_model(m)


@app.delete("/api/providers/{pid}/models/{mid}")
def delete_model(pid: str, mid: str):
    if not store.delete_model(mid):
        raise HTTPException(404, "模型不存在")
    return {"ok": True}


@app.get("/api/providers/{pid}/fetch-models")
async def fetch_models(pid: str):
    """调用供应商的 OpenAI 兼容 /models 接口拉取可用模型名列表。"""
    p = store.find_provider(pid)
    if not p:
        raise HTTPException(404, "供应商不存在")
    if not p.baseUrl:
        raise HTTPException(400, "请先填写该供应商的 Base URL")
    url = p.baseUrl.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {p.apiKey}"} if p.apiKey else {}
    proxy = store.settings.proxy
    kwargs: dict = {"timeout": 15, "follow_redirects": True}
    if proxy.mode == "custom":
        kwargs.update(proxy=f"http://{proxy.host}:{proxy.port}", trust_env=False)
    elif proxy.mode == "none":
        kwargs["trust_env"] = False
    try:
        async with httpx.AsyncClient(**kwargs) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        raise HTTPException(502, f"拉取模型列表失败：{e}")
    items = data.get("data", []) if isinstance(data, dict) else data
    ids = []
    for it in items:
        mid = it.get("id") if isinstance(it, dict) else str(it)
        if mid:
            ids.append(mid)
    return {"models": ids}


# ---------------- 模型推荐 ----------------


@app.post("/api/recommend-model")
async def recommend_model(body: RecommendIn):
    if not body.task.strip():
        raise HTTPException(400, "任务描述不能为空")
    try:
        return await recommend(
            store,
            body.task.strip(),
            {"cost": body.prefer.cost, "speed": body.prefer.speed},
        )
    except ValueError as e:
        raise HTTPException(500, str(e))


@app.get("/api/selector/models")
def selector_models():
    return {"models": load_knowledge()}


# ---------------- 全局设置（代理 / Clash 集成） ----------------


@app.get("/api/settings")
def get_settings():
    return store.settings


@app.put("/api/settings")
def put_settings(body: SettingsUpdate):
    s = store.update_settings(
        proxy=body.proxy.model_dump() if body.proxy else None,
        clash=body.clash.model_dump() if body.clash else None,
        workspace=body.workspace.model_dump() if body.workspace else None,
        sandbox=body.sandbox.model_dump() if body.sandbox else None,
        auth=body.auth.model_dump() if body.auth else None,
    )
    if body.proxy:
        # 代理设置变化后，所有缓存的 OpenAI 客户端底层 httpx 连接池都已失效
        from .providers.openai_compat import invalidate_client
        invalidate_client(None)
    return s


# ---------------- 工作区文件（Agent 产出落盘） ----------------


def _workspace_of(rid: str) -> Workspace:
    if not load_run_meta(rid) and rid not in RUNS:
        raise HTTPException(404, "运行不存在")
    return Workspace(WORKSPACE_DIR / rid)


@app.get("/api/runs/{rid}/artifacts")
def list_artifacts(rid: str):
    ws = _workspace_of(rid)
    return {"enabled": store.settings.workspace.enabled, "root": str(ws.root), "files": ws.list_files()}


@app.get("/api/runs/{rid}/artifacts/file")
def read_artifact(rid: str, path: str):
    ws = _workspace_of(rid)
    try:
        return ws.read(path)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/clash/subscription")
async def clash_subscription(body: SubscriptionIn):
    if not body.url.strip():
        raise HTTPException(400, "订阅地址不能为空")
    try:
        content = await fetch_url(body.url.strip(), store.settings.proxy)
    except Exception as e:
        raise HTTPException(502, f"拉取订阅失败：{e}")
    nodes = parse_subscription(content)
    if not nodes:
        raise HTTPException(422, "未能从订阅内容解析出节点（支持 Clash YAML 与 Base64 分享链接）")
    return {"nodes": nodes}


@app.get("/api/clash/groups")
async def clash_groups():
    try:
        proxies = await get_all_proxies(store.settings.clash)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    return {"groups": extract_groups(proxies)}


@app.post("/api/clash/delay")
async def clash_delay(body: ClashDelayIn):
    clash = store.settings.clash
    names = body.names
    if not names:
        try:
            proxies = await get_all_proxies(clash)
        except RuntimeError as e:
            raise HTTPException(502, str(e))
        groups = extract_groups(proxies)
        names = group_candidates(groups[0], proxies) if groups else []
    results = await test_delays(clash, names)
    return {"results": results}


@app.post("/api/clash/select")
async def clash_select(body: ClashSelectIn):
    try:
        await select_node(store.settings.clash, body.group, body.name)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    return {"ok": True}


@app.post("/api/clash/auto-select")
async def clash_auto_select(body: ClashSelectIn):
    """测速分组内全部节点 → 切换到延迟最低的可用节点。"""
    clash = store.settings.clash
    try:
        proxies = await get_all_proxies(clash)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    groups = {g["name"]: g for g in extract_groups(proxies)}
    g = groups.get(body.group)
    if not g:
        raise HTTPException(404, f"策略组「{body.group}」不存在")
    candidates = group_candidates(g, proxies)
    if not candidates:
        raise HTTPException(422, f"策略组「{body.group}」中没有可测速的节点")
    results = await test_delays(clash, candidates)
    ok = [r for r in results if r["delayMs"] is not None]
    if not ok:
        raise HTTPException(504, "所有节点测速均超时或失败，请检查节点可用性")
    best = min(ok, key=lambda r: r["delayMs"])
    try:
        await select_node(clash, body.group, best["name"])
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    return {"selected": best["name"], "delayMs": best["delayMs"], "results": sorted(results, key=lambda r: r["delayMs"] is None and 10**9 or r["delayMs"])}


# ---------------- Agent ----------------


@app.get("/api/agents")
def get_agents():
    return {"agents": store.agents}


@app.post("/api/agents")
def create_agent(body: AgentIn):
    a = Agent(id=new_id("a_"), **body.model_dump())
    return store.add_agent(a)


@app.put("/api/agents/{aid}")
def update_agent(aid: str, body: AgentUpdate):
    a = store.update_agent(aid, body.model_dump(exclude_unset=True))
    if not a:
        raise HTTPException(404, "Agent 不存在")
    return a


@app.delete("/api/agents/{aid}")
def delete_agent(aid: str):
    if not store.delete_agent(aid):
        raise HTTPException(404, "Agent 不存在")
    return {"ok": True}


# ---------------- 运行 ----------------


def _active_run() -> Run | None:
    return next((r for r in RUNS.values() if r.meta.status == "running"), None)


@app.post("/api/runs")
async def start_run(body: RunStartIn):
    if not body.task.strip():
        raise HTTPException(400, "任务内容不能为空")
    if _active_run():
        raise HTTPException(409, "已有进行中的运行，请先等待完成或手动停止")
    run = Run(new_id("r_"), body.task.strip(), store, bus, agent_count=body.agentCount)
    RUNS[run.id] = run
    TASKS[run.id] = asyncio.create_task(run_flow(run))
    return run.meta


@app.get("/api/runs")
def list_runs():
    metas: dict[str, RunMeta] = {m.id: m for m in load_run_metas()}
    for r in RUNS.values():
        metas[r.id] = r.meta
    return sorted(metas.values(), key=lambda m: m.createdAt, reverse=True)


@app.get("/api/runs/{rid}")
def get_run(rid: str):
    r = RUNS.get(rid)
    if r:
        return {"meta": r.meta, "events": r.events}
    events = load_run_events(rid)
    if events is None:
        raise HTTPException(404, "运行不存在")
    meta = load_run_meta(rid)
    return {"meta": meta, "events": events}


@app.delete("/api/runs/{rid}")
def delete_run(rid: str):
    t = TASKS.get(rid)
    if t and not t.done():
        raise HTTPException(400, "运行仍在进行中，请先停止再删除")
    TASKS.pop(rid, None)
    RUNS.pop(rid, None)
    if not delete_run_file(rid):
        raise HTTPException(404, "运行不存在")
    import shutil

    shutil.rmtree(WORKSPACE_DIR / rid, ignore_errors=True)
    return {"ok": True}


@app.post("/api/runs/{rid}/input")
def run_input(rid: str, body: RunInputIn):
    r = RUNS.get(rid)
    if not r or r.meta.status != "running":
        raise HTTPException(400, "运行不在进行中")
    r.provide_input(body.text, body.kind, body.assignments)
    return {"ok": True}


@app.post("/api/runs/{rid}/stop")
def stop_run(rid: str):
    t = TASKS.get(rid)
    if not t or t.done():
        raise HTTPException(400, "运行已结束")
    t.cancel()
    return {"ok": True}


@app.get("/api/runs/{rid}/usage")
def run_usage(rid: str):
    """按 Agent/模型汇总 token 用量，供交付物面板展示成本概况。"""
    events = RUNS[rid].events if rid in RUNS else load_run_events(rid)
    if events is None:
        raise HTTPException(404, "运行不存在")
    total = {"promptTokens": 0, "completionTokens": 0, "totalTokens": 0, "calls": 0, "elapsedMs": 0}
    by_model: dict[str, dict] = {}
    for ev in events:
        if ev.type != "usage.reported":
            continue
        p = ev.payload or {}
        total["calls"] += 1
        for k in ("promptTokens", "completionTokens", "totalTokens", "elapsedMs"):
            total[k] += int(p.get(k) or 0)
        key = f"{p.get('provider') or '未知'} / {p.get('model') or '未知'}"
        item = by_model.setdefault(
            key, {"provider": p.get("provider"), "model": p.get("model"), "calls": 0,
                  "promptTokens": 0, "completionTokens": 0, "totalTokens": 0, "elapsedMs": 0}
        )
        item["calls"] += 1
        for k in ("promptTokens", "completionTokens", "totalTokens", "elapsedMs"):
            item[k] += int(p.get(k) or 0)
    return {"total": total, "byModel": sorted(by_model.values(), key=lambda x: x["totalTokens"], reverse=True)}


# ---------------- WebSocket ----------------


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    # 可选鉴权：token 通过 ?token= 或 Sec-WebSocket-Protocol 传递
    if not _token_ok(ws.query_params.get("token", "")):
        await ws.close(code=1008)
        return
    await ws.accept()
    q = bus.subscribe()
    try:
        await ws.send_json({"type": "hello"})
        while True:
            data = await q.get()
            await ws.send_json({"type": "event", "event": data})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        bus.unsubscribe(q)
