"""LLM 调用入口：根据 Agent 的 binding 分发到 mock 或 OpenAI 兼容实现。"""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable, Optional

from ..schemas import Agent
from .mock import mock_chat
from .openai_compat import real_chat

DeltaCallback = Callable[[str], Awaitable[None]]
UsageCallback = Callable[[dict], Awaitable[None]]


async def chat(
    store,
    agent: Agent,
    system: str,
    messages: list[dict],
    hint: dict[str, Any] | None = None,
    binding: str | None = None,
    on_delta: Optional[DeltaCallback] = None,
    on_usage: Optional[UsageCallback] = None,
) -> str:
    """store: app.store.Store；messages: [{"role","content"}]；hint 仅供 mock 脚本使用；
    binding 可覆盖 Agent 自身绑定（任务分配时用户可为单个工作包指定模型）；
    on_delta 提供时流式回调增量文本（监控实时输出用）；on_usage 回调 token 用量。"""
    hint = hint or {}
    use_binding = binding or agent.binding
    if use_binding == "mock":
        started = time.monotonic()
        content = await mock_chat(agent.role, messages, hint, on_delta=on_delta)
        if on_usage is not None:
            # Mock 没有真实 token，但保留调用次数与耗时，便于演示用量面板
            await on_usage(
                {
                    "model": "Mock",
                    "provider": "Mock",
                    "promptTokens": 0,
                    "completionTokens": 0,
                    "totalTokens": 0,
                    "elapsedMs": int((time.monotonic() - started) * 1000),
                }
            )
        return content

    provider, model = store.resolve_binding(use_binding)
    started = time.monotonic()
    saw_tokens = False

    async def _usage(payload: dict) -> None:
        nonlocal saw_tokens
        if payload.get("totalTokens"):
            saw_tokens = True
            if on_usage is not None:
                await on_usage(payload)

    content = await real_chat(
        provider,
        model,
        system,
        messages,
        effort=getattr(agent, "effort", "default") or "default",
        proxy=store.settings.proxy,
        on_delta=on_delta,
        on_usage=_usage,
    )
    if on_usage is not None and not saw_tokens:
        # 供应商未返回 usage 时至少记录耗时，便于性能复盘
        await on_usage(
            {
                "model": model.name,
                "provider": provider.name,
                "promptTokens": 0,
                "completionTokens": 0,
                "totalTokens": 0,
                "elapsedMs": int((time.monotonic() - started) * 1000),
            }
        )
    return content


def parse_json_tolerant(raw: str) -> dict | None:
    """宽容解析 LLM 输出的 JSON：去代码围栏、截取首尾大括号。失败返回 None。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    import json

    try:
        obj = json.loads(text[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None
