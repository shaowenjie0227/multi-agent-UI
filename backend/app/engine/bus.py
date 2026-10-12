"""事件总线 + Run 运行时对象：事件落盘并广播给所有 WebSocket 订阅者。"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from ..schemas import RunEvent, RunMeta
from ..store import Store, now, save_run


class EventBus:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    async def broadcast(self, event: RunEvent) -> None:
        data = event.model_dump()
        for q in list(self._subs):
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass


class Run:
    def __init__(self, run_id: str, task_text: str, store: Store, bus: EventBus, agent_count: Optional[int] = None) -> None:
        self.id = run_id
        self.task_text = task_text
        self.store = store
        self.bus = bus
        self.agent_count = agent_count  # 用户期望的工作包/Agent 数量，可为 None
        self.meta = RunMeta(id=run_id, task=task_text, status="running", createdAt=now())
        self.events: list[RunEvent] = []
        self.input_queue: asyncio.Queue = asyncio.Queue()

    async def emit(
        self,
        type: str,
        payload: Optional[dict[str, Any]] = None,
        *,
        agentId: Optional[str] = None,
        taskId: Optional[str] = None,
        round: Optional[int] = None,
    ) -> RunEvent:
        ev = RunEvent(
            seq=len(self.events) + 1,
            runId=self.id,
            type=type,
            ts=time.time(),
            agentId=agentId,
            taskId=taskId,
            round=round,
            payload=payload or {},
        )
        self.events.append(ev)
        save_run(self.meta, self.events)
        await self.bus.broadcast(ev)
        return ev

    async def wait_input(self) -> dict:
        return await self.input_queue.get()

    def provide_input(self, text: str, kind: str, assignments: Optional[list[dict]] = None) -> None:
        self.input_queue.put_nowait({"text": text, "kind": kind, "assignments": assignments or []})
