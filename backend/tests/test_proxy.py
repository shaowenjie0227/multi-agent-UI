"""代理设置贯通：LLM 调用与模型列表拉取都必须遵循全局代理设置。"""
from __future__ import annotations

import pytest

from app.schemas import Agent, Provider, ProviderModel, ProxySettings


def test_fetch_models_uses_custom_proxy(monkeypatch):
    """fetch-models 必须按 settings.proxy 构造 httpx 客户端，而不是走系统代理。"""
    from fastapi.testclient import TestClient

    import app.main as main_mod

    captured: dict = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            class R:
                status_code = 200

                def raise_for_status(self):
                    pass

                def json(self):
                    return {"data": [{"id": "grok-4.7"}]}

            return R()

    monkeypatch.setattr(main_mod.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(main_mod, "store", main_mod.Store())
    main_mod.store.update_settings(proxy={"mode": "custom", "host": "127.0.0.1", "port": 7897})
    main_mod.store.update_provider("xai", {"apiKey": "sk-test"})

    client = TestClient(main_mod.app)
    resp = client.get("/api/providers/xai/fetch-models")
    assert resp.status_code == 200
    assert resp.json()["models"] == ["grok-4.7"]
    assert captured.get("proxy") == "http://127.0.0.1:7897"
    assert captured.get("trust_env") is False


def test_fetch_models_none_mode_disables_env_proxy(monkeypatch):
    from fastapi.testclient import TestClient

    import app.main as main_mod

    captured: dict = {}

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            class R:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"data": []}

            return R()

    monkeypatch.setattr(main_mod.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(main_mod, "store", main_mod.Store())
    main_mod.store.update_settings(proxy={"mode": "none", "host": "127.0.0.1", "port": 7897})
    TestClient(main_mod.app).get("/api/providers/xai/fetch-models")
    assert captured.get("trust_env") is False
    assert "proxy" not in captured


@pytest.mark.asyncio
async def test_recommend_llm_passes_configured_proxy(monkeypatch):
    """模型推荐的 LLM 路径必须传 settings.proxy，否则会回落到硬编码默认代理。"""
    import app.selector as selector

    seen: dict = {}

    async def fake_real_chat(provider, model, system, messages, **kwargs):
        seen.update(kwargs)
        return '{"tags":["coding"],"primary":{"modelId":"grok-4.7","reasoningEffort":"off","confidence":0.9,"rationale":"x"}}'

    monkeypatch.setattr(selector, "real_chat", fake_real_chat)

    class FakeStore:
        providers = [Provider(id="xai", name="xAI", baseUrl="https://api.x.ai/v1", apiKey="sk-x")]
        models = [ProviderModel(id="m1", providerId="xai", name="grok-4.7")]
        settings = type("S", (), {"proxy": ProxySettings(mode="none", host="h", port=1)})()

        @staticmethod
        def models_of(pid):
            return [ProviderModel(id="m1", providerId="xai", name="grok-4.7")]

    out = await selector.recommend_llm(FakeStore(), "写个脚本", {"cost": "balanced", "speed": False}, [{"id": "grok-4.7"}])
    assert out["primary"]["modelId"] == "grok-4.7"
    assert seen["proxy"].mode == "none"


@pytest.mark.asyncio
async def test_chat_passes_usage_callback(monkeypatch):
    """run_task 依赖 on_usage 收集 token 用量，base.chat 必须把它接到 real_chat。"""
    from app.providers import base as base_mod

    seen: dict = {}

    async def fake_real_chat(provider, model, system, messages, **kwargs):
        seen["on_usage"] = kwargs.get("on_usage")
        seen["proxy"] = kwargs.get("proxy")
        return "ok"

    monkeypatch.setattr(base_mod, "real_chat", fake_real_chat)

    class FakeStore:
        settings = type("S", (), {"proxy": ProxySettings(mode="system")})()

        @staticmethod
        def resolve_binding(binding):
            return Provider(id="xai", name="xAI", baseUrl="u", apiKey="k"), ProviderModel(id="m", providerId="xai", name="n")

    agent = Agent(id="a", name="dev", role="developer", binding="xai:m")
    chunks: list[str] = []

    async def on_usage(p):
        chunks.append("usage")

    out = await base_mod.chat(FakeStore(), agent, "sys", [{"role": "user", "content": "hi"}], on_usage=on_usage)
    assert out == "ok"
    assert seen["on_usage"] is not None
    assert seen["proxy"].mode == "system"
    # 供应商没回 usage 时也要落一条耗时记录，保证用量面板不为空
    assert chunks == ["usage"]
