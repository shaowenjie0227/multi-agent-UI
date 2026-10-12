"""任务执行器：单任务运行（状态事件发射）+ 通用 DAG 拓扑调度（无依赖并行）。"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable

from ..schemas import Agent
from .errors import EngineError

ChatFn = Callable[..., Awaitable[str]]
EmitFn = Callable[..., Awaitable[Any]]
DeltaCallback = Callable[[str], Awaitable[None]]


def delta_flusher(
    run,
    agent_id: str,
    *,
    task_id: str | None = None,
    round_no: int | None = None,
    interval: float = 0.8,
    max_chars: int = 500,
) -> tuple[DeltaCallback, Callable[[], Awaitable[None]]]:
    """把流式增量聚合成 agent.output 事件：interval 秒或攒够 max_chars 才广播一次，
    避免逐 token 事件刷爆事件总线与落盘。返回 (on_delta, flush)，结束后须调用 flush 补发残余。"""
    buf: list[str] = []
    last = time.monotonic()

    async def on_delta(s: str) -> None:
        nonlocal last
        if not s:
            return
        buf.append(s)
        if time.monotonic() - last >= interval or sum(map(len, buf)) >= max_chars:
            await run.emit("agent.output", {"delta": "".join(buf)}, agentId=agent_id, taskId=task_id, round=round_no)
            buf.clear()
            last = time.monotonic()

    async def flush() -> None:
        if buf:
            await run.emit("agent.output", {"delta": "".join(buf)}, agentId=agent_id, taskId=task_id, round=round_no)
            buf.clear()

    return on_delta, flush


async def run_task(
    run,
    chat_fn: ChatFn,
    agent: Agent,
    *,
    task_id: str,
    title: str,
    round: int,
    user_content: str,
    hint: dict | None = None,
    binding: str | None = None,
) -> str:
    """运行单个任务：task.started → working → 流式调 LLM（agent.output 增量）→ task.completed。
    binding 可覆盖 Agent 绑定。"""
    await run.emit("task.started", {"title": title, "role": agent.role, "agentId": agent.id}, agentId=agent.id, taskId=task_id, round=round)
    await run.emit("agent.status", {"status": "working", "detail": title}, agentId=agent.id, taskId=task_id, round=round)
    on_delta, flush = delta_flusher(run, agent.id, task_id=task_id, round_no=round)
    try:
        output = await chat_fn(run.store, agent, agent.persona, [{"role": "user", "content": user_content}], hint, binding, on_delta=on_delta)
    except EngineError:
        await flush()
        await run.emit("agent.status", {"status": "error", "detail": "执行失败"}, agentId=agent.id, taskId=task_id, round=round)
        raise
    except Exception as e:
        await flush()  # 失败前已产出的部分内容也留给监控面板
        await run.emit("agent.status", {"status": "error", "detail": str(e)[:200]}, agentId=agent.id, taskId=task_id, round=round)
        raise EngineError(f"Agent「{agent.name}」调用失败：{e}") from e
    await flush()
    await run.emit("agent.status", {"status": "done"}, agentId=agent.id, taskId=task_id, round=round)
    await run.emit("task.completed", {"title": title, "output": output}, agentId=agent.id, taskId=task_id, round=round)
    return output


async def execute_dag(tasks: list[dict], run_one: Callable[[dict, dict], Awaitable[Any]]) -> dict[str, Any]:
    """按依赖拓扑调度；同一批无依赖任务并行。返回 {taskId: result}。"""
    done: dict[str, Any] = {}
    pending: dict[str, dict] = {t["id"]: t for t in tasks}
    while pending:
        ready = [t for t in pending.values() if all(d in done for d in t.get("dependsOn", []))]
        if not ready:
            raise EngineError("任务依赖形成环路，无法调度")
        results = await asyncio.gather(*[run_one(t, {d: done[d] for d in t.get("dependsOn", [])}) for t in ready])
        for t, r in zip(ready, results):
            done[t["id"]] = r
            del pending[t["id"]]
    return done
