"""OpenAI 兼容 API 调用（智谱 / xAI / DeepSeek / OpenAI 等），一个实现通吃。

支持按全局代理设置出网：none=强制直连、system=跟随系统代理、custom=显式本机代理。
支持流式输出：传入 on_delta 时走 stream=True 逐块回调，供应商不支持流式则自动回退非流式。
"""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

import httpx
from openai import AsyncOpenAI

from ..schemas import Provider, ProviderModel, ProxySettings

DeltaCallback = Callable[[str], Awaitable[None]]

_clients: dict[str, AsyncOpenAI] = {}


def _proxy_signature(proxy: ProxySettings) -> str:
    return f"{proxy.mode}:{proxy.host}:{proxy.port}"


def _http_client_for(proxy: ProxySettings) -> httpx.AsyncClient | None:
    """按代理模式构造 httpx 客户端；None 表示使用 openai SDK 默认（跟随系统代理）。"""
    if proxy.mode == "custom":
        return httpx.AsyncClient(proxy=f"http://{proxy.host}:{proxy.port}", trust_env=False, timeout=120)
    if proxy.mode == "none":
        return httpx.AsyncClient(trust_env=False, timeout=120)
    return None


def _client_for(provider: Provider, proxy: ProxySettings) -> AsyncOpenAI:
    key = f"{provider.id}:{provider.baseUrl}:{provider.apiKey}:{_proxy_signature(proxy)}"
    if key not in _clients:
        kwargs: dict = {"base_url": provider.baseUrl, "api_key": provider.apiKey or "sk-empty", "timeout": 120}
        http_client = _http_client_for(proxy)
        if http_client is not None:
            kwargs["http_client"] = http_client
        _clients[key] = AsyncOpenAI(**kwargs)
    return _clients[key]


async def real_chat(
    provider: Provider,
    model: ProviderModel,
    system: str,
    messages: list[dict],
    effort: str = "default",
    proxy: ProxySettings | None = None,
    on_delta: Optional[DeltaCallback] = None,
) -> str:
    proxy = proxy or ProxySettings()
    client = _client_for(provider, proxy)
    payload = [{"role": "system", "content": system}] + messages
    kwargs: dict = {"temperature": 0.4}
    if effort and effort != "default":
        # 不支持该参数的供应商可能忽略或报错；Agent 档位保持 default 即可规避
        kwargs["reasoning_effort"] = effort

    if on_delta is None:
        resp = await client.chat.completions.create(model=model.name, messages=payload, **kwargs)
        content = resp.choices[0].message.content or ""
    else:
        content = ""
        try:
            stream = await client.chat.completions.create(model=model.name, messages=payload, stream=True, **kwargs)
            async for chunk in stream:
                if not getattr(chunk, "choices", None):
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    content += delta
                    await on_delta(delta)
        except Exception:
            if content:
                raise  # 已流出一部分，回退重试会造成输出重复
            content = ""  # 供应商不支持流式 → 回退非流式
        if not content.strip():
            resp = await client.chat.completions.create(model=model.name, messages=payload, **kwargs)
            content = resp.choices[0].message.content or ""
            if content:
                await on_delta(content)

    if not content.strip():
        raise RuntimeError(f"模型 {model.name} 返回了空内容")
    return content
