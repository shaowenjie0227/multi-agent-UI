"""DAG 调度：并行性、失败取消兄弟任务、环检测。"""
from __future__ import annotations

import asyncio

import pytest

from app.engine.errors import EngineError
from app.engine.executor import execute_dag


def task(tid: str, deps: list[str] | None = None) -> dict:
    return {"id": tid, "title": tid, "dependsOn": deps or []}


@pytest.mark.asyncio
async def test_sibling_tasks_run_in_parallel():
    started: list[str] = []
    barrier = asyncio.Event()

    async def run_one(t, _deps):
        started.append(t["id"])
        if len(started) == 2:
            barrier.set()
        # 两个任务必须同时开始，否则超时
        await asyncio.wait_for(barrier.wait(), timeout=1)
        return t["id"]

    out = await execute_dag([task("a"), task("b")], run_one)
    assert out == {"a": "a", "b": "b"}


@pytest.mark.asyncio
async def test_dependencies_respected():
    order: list[str] = []

    async def run_one(t, deps):
        order.append(t["id"])
        return f"{t['id']}:{sorted(deps)}"

    out = await execute_dag([task("a"), task("b", ["a"]), task("c", ["b"])], run_one)
    assert order == ["a", "b", "c"]
    assert out["c"] == "c:['b']"


@pytest.mark.asyncio
async def test_failure_cancels_siblings():
    """一个任务失败时，仍在跑的兄弟任务必须被取消，不能让运行在失败后继续写事件。"""
    cancelled: list[str] = []
    started = asyncio.Event()

    async def run_one(t, _deps):
        if t["id"] == "fail":
            await started.wait()
            raise RuntimeError("boom")
        started.set()
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            cancelled.append(t["id"])
            raise
        return t["id"]

    with pytest.raises(EngineError) as exc:
        await asyncio.wait_for(execute_dag([task("fail"), task("slow")], run_one), timeout=3)
    assert "boom" in str(exc.value)
    assert cancelled == ["slow"]


@pytest.mark.asyncio
async def test_cycle_raises_engine_error():
    async def run_one(t, _deps):
        return t["id"]

    with pytest.raises(EngineError) as exc:
        await execute_dag([task("a", ["b"]), task("b", ["a"])], run_one)
    assert "环路" in str(exc.value)


@pytest.mark.asyncio
async def test_empty_task_list():
    async def run_one(t, _deps):  # pragma: no cover - 不应被调用
        raise AssertionError("no tasks")

    assert await execute_dag([], run_one) == {}
