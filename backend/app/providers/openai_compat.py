"""OpenAI 兼容 API 调用（智谱 / xAI / DeepSeek / OpenAI 等），一个实现通吃。

支持按全局代理设置出网：none=强制直连、system=跟随系统代理、custom=显式本机代理。
支持流式输出：传入 on_delta 时走 stream=True 逐块回调，供应商不支持流式则自动回退非流式。
支持瞬时故障重试（429/5xx/连接错误）；已经流出内容后不再重试，避免重复输出。
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

import httpx
import openai
from openai import AsyncOpenAI

from ..schemas import Provider, ProviderModel, ProxySettings

DeltaCallback = Callable[[str], Awaitable[None]]
UsageCallback = Callable[[dict], Awaitable[None]]

_clients: dict[str, AsyncOpenAI] = {}

MAX_ATTEMPTS = 3
BACKOFF_BASE = 1.5

# 可重试的瞬时错误：限流、服务端错误、连接问题
_RETRYABLE = (
    openai.RateLimitError,
    openai.APIConnectionError,
    openai.InternalServerError,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.RemoteProtocolError,
)


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
        kwargs: dict = {
            "base_url": provider.baseUrl,
            "api_key": provider.apiKey or "sk-empty",
            "timeout": 120,
            "max_retries": 0,  # 重试由本模块统一控制，避免叠加放大
        }
        http_client = _http_client_for(proxy)
        if http_client is not None:
            kwargs["http_client"] = http_client
        _clients[key] = AsyncOpenAI(**kwargs)
    return _clients[key]


def invalidate_client(provider_id: str | None = None) -> None:
    """清掉缓存的 OpenAI 客户端（含其 httpx 连接池）。
    provider_id 为 None 时清空全部（代理设置变化）；否则只清该供应商相关的条目。
    注意：若有正在进行的流式调用，其底层连接会被池化复用直到该调用自然结束。"""
    loop = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        pass  # 非异步上下文：直接丢弃引用，由 GC 回收
    for key in [k for k in _clients if provider_id is None or k.startswith(f"{provider_id}:")]:
        client = _clients.pop(key, None)
        if client is not None and loop is not None:
            try:
                loop.create_task(client.close())
            except Exception:
                pass


def _retry_delay(attempt: int) -> float:
    return BACKOFF_BASE * (2 ** (attempt - 1))


async def _emit_usage(usage_cb: Optional[UsageCallback], usage, model_name: str, provider_name: str) -> None:
    if usage_cb is None:
        return
    await usage_cb(
        {
            "model": model_name,
            "provider": provider_name,
            "promptTokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completionTokens": getattr(usage, "completion_tokens", 0) or 0,
            "totalTokens": getattr(usage, "total_tokens", 0) or 0,
        }
    )


async def _complete_once(
    provider: Provider,
    model: ProviderModel,
    payload: list[dict],
    kwargs: dict,
    proxy: ProxySettings,
    on_delta: Optional[DeltaCallback],
    on_usage: Optional[UsageCallback],
    streamed: list[str],
) -> str:
    """执行一次调用；streamed 用于在流式中记录已产出的内容（决定能否重试）。"""
    client = _client_for(provider, proxy)

    if on_delta is None:
        resp = await client.chat.completions.create(model=model.name, messages=payload, **kwargs)
        content = resp.choices[0].message.content or ""
        await _emit_usage(on_usage, getattr(resp, "usage", None), model.name, provider.name)
        return content

    content = ""
    try:
        stream = await client.chat.completions.create(model=model.name, messages=payload, stream=True, **kwargs)
        usage = None
        async for chunk in stream:
            if getattr(chunk, "usage", None):
                usage = chunk.usage
            if not getattr(chunk, "choices", None):
                continue
            delta = chunk.choices[0].delta.content
            if delta:
                content += delta
                streamed.append(delta)
                await on_delta(delta)
        await _emit_usage(on_usage, usage, model.name, provider.name)
    except _RETRYABLE:
        raise
    except Exception:
        if content:
            raise  # 已流出一部分，回退重试会造成输出重复
        # 供应商不支持流式 → 回退非流式
        resp = await client.chat.completions.create(model=model.name, messages=payload, **kwargs)
        content = resp.choices[0].message.content or ""
        await _emit_usage(on_usage, getattr(resp, "usage", None), model.name, provider.name)
        if content:
            streamed.append(content)
            await on_delta(content)
    return content


async def real_chat(
    provider: Provider,
    model: ProviderModel,
    system: str,
    messages: list[dict],
    effort: str = "default",
    proxy: ProxySettings | None = None,
    on_delta: Optional[DeltaCallback] = None,
    on_usage: Optional[UsageCallback] = None,
) -> str:
    proxy = proxy or ProxySettings()
    payload = [{"role": "system", "content": system}] + messages
    kwargs: dict = {"temperature": 0.4}
    if effort and effort != "default":
        # 不支持该参数的供应商可能忽略或报错；Agent 档位保持 default 即可规避
        kwargs["reasoning_effort"] = effort

    last_exc: Exception | None = None
    streamed: list[str] = []
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            content = await _complete_once(provider, model, payload, kwargs, proxy, on_delta, on_usage, streamed)
            if not content.strip():
                raise RuntimeError(f"模型 {model.name} 返回了空内容")
            return content
        except _RETRYABLE as e:
            last_exc = e
            # 已产出部分内容时重试会重复输出；剩次数用尽也不再重试
            if streamed or attempt >= MAX_ATTEMPTS:
                break
            await asyncio.sleep(_retry_delay(attempt))

    raise RuntimeError(f"模型 {model.name} 调用失败（已尝试 {MAX_ATTEMPTS} 次）：{last_exc}")
