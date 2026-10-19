"""阶段一：交互式需求分析 + 工作拆解 + 任务分配门。

分析师产出方案+边界问题 → 用户对话修订 → 完整方案（含 work_packages 工作包拆解）
确认满意 → 进入任务分配门：用户为每个工作包选择执行 Agent（可覆盖 LLM）→
用户也可在分配门选择返回，继续对话修改方案，循环到满意为止。
"""
from __future__ import annotations

from typing import Awaitable, Callable

from ..providers.base import chat as chat_default
from ..providers.base import parse_json_tolerant
from .context import clip_history
from .errors import EngineError
from .executor import delta_flusher
from .graph import sanitize_dependencies

ChatFn = Callable[..., Awaitable[str]]

# 附加给分析师的输出约定（叠加在用户可编辑的人设之上，保证新字段可用）
ANALYST_SUPPLEMENT = (
    "\n\n【补充约定】当 ready_for_approval=true 时，JSON 必须包含 work_packages 字段："
    "把工作拆解为若干工作包（数量尊重用户期望，若用户未指定则自行合理判断），"
    '每项形如 {"key": "pkg-1", "agentName": "建议角色名(如 前端工程师)", "responsibility": "该包职责", '
    '"tasks": ["要干的活1", "要干的活2"], "integration": "如何与其他工作包联调对接", "dependsOn": ["pkg-1"]}。'
    "dependsOn 表示该包依赖哪些其他工作包的产出，无依赖则为空数组。"
)


def _compose_task_text(run) -> str:
    text = run.task_text
    if getattr(run, "agent_count", None):
        text += f"\n\n（用户希望由大约 {run.agent_count} 个 Agent 协作完成这份工作，请按该数量拆解工作包）"
    return text


def _normalize_packages(raw) -> list[dict]:
    out: list[dict] = []
    for i, p in enumerate(raw or [], start=1):
        if not isinstance(p, dict):
            continue
        out.append(
            {
                "key": str(p.get("key") or f"pkg-{i}"),
                "agentName": str(p.get("agentName") or p.get("name") or f"工作包 {i}"),
                "responsibility": str(p.get("responsibility") or ""),
                "tasks": [str(t) for t in (p.get("tasks") or [])],
                "integration": str(p.get("integration") or ""),
                "dependsOn": [str(d) for d in (p.get("dependsOn") or [])],
            }
        )
    # 键去重：分析师偶尔会给出重复 key，会导致分配与返工按包归属错乱
    seen: set[str] = set()
    for i, p in enumerate(out, start=1):
        key = p["key"]
        if key in seen:
            key = f"pkg-{i}"
            while key in seen:
                key += f"-{i}"
            p["key"] = key
        seen.add(key)
    return out


def _fallback_packages() -> list[dict]:
    return [
        {
            "key": "pkg-1",
            "agentName": "开发工程师",
            "responsibility": "依据需求方案完成主要实现工作",
            "tasks": ["按需求方案完成实现", "自检并整理交付说明"],
            "integration": "产出统一交付物，交由联调验收",
            "dependsOn": [],
        }
    ]


def _validate_assignments(items: list, packages: list[dict], options: list[dict]) -> list[dict]:
    option_by_id = {o["id"]: o for o in options}
    by_key = {a.get("packageKey"): a for a in items if isinstance(a, dict)}
    result = []
    for p in packages:
        a = by_key.get(p["key"])
        if not a or not a.get("agentId"):
            raise EngineError(f"工作包「{p['agentName']}」未分配执行 Agent")
        opt = option_by_id.get(a["agentId"])
        if not opt:
            raise EngineError(f"工作包「{p['agentName']}」分配的 Agent 不存在或未启用")
        model = a.get("model")
        binding = model if model not in (None, "", "follow") else opt["binding"]
        result.append({"packageKey": p["key"], "agentId": opt["id"], "agentName": opt["name"], "binding": binding})
    return result


async def run_requirements_and_assignment(run, chat_fn: ChatFn = chat_default):
    """返回 (最终需求方案, 工作包列表, 分配列表)。"""
    store = run.store
    analyst = store.find_agent_by_role("analyst")
    if not analyst:
        raise EngineError("没有启用的「需求分析师」Agent，请在 Agent 管理中检查角色与启用状态")

    await run.emit(
        "task.started", {"title": "需求分析与工作拆解", "role": "analyst"}, agentId=analyst.id, taskId="req", round=1
    )
    system = analyst.persona + ANALYST_SUPPLEMENT
    history: list[dict] = [{"role": "user", "content": _compose_task_text(run)}]
    turns = 0
    version = 0

    while True:  # 外层：方案确认 → 分配门（可返回继续修改方案）
        last_raw = ""
        # ---- 对话直到方案被确认
        while True:
            await run.emit(
                "agent.status", {"status": "thinking", "detail": "分析需求并整理方案与工作拆解"},
                agentId=analyst.id, taskId="req",
            )
            on_delta, flush = delta_flusher(run, analyst.id, task_id="req")
            raw = await chat_fn(
                store, analyst, system, clip_history(history),
                {"analyst_turns": turns, "agent_count": getattr(run, "agent_count", None), "task": run.task_text},
                on_delta=on_delta,
            )
            await flush()
            last_raw = raw
            parsed = parse_json_tolerant(raw) or {}
            proposal = parsed.get("proposal") or raw
            questions = parsed.get("questions") or []
            packages = _normalize_packages(parsed.get("work_packages"))
            ready = bool(parsed.get("ready_for_approval"))
            version += 1

            # 依赖合法性在确认前就校验并修正，避免用户确认分配后才在执行期报"依赖成环"
            if packages:
                packages, warnings = sanitize_dependencies(packages)
                if warnings:
                    await run.emit("plan.warning", {"warnings": warnings, "version": version}, agentId=analyst.id, taskId="req")

            await run.emit(
                "agent.status", {"status": "working", "detail": f"产出方案 v{version}"},
                agentId=analyst.id, taskId="req",
            )
            await run.emit(
                "proposal.updated",
                {"version": version, "content": proposal, "questions": questions, "packages": packages},
                agentId=analyst.id, taskId="req",
            )
            if questions:
                await run.emit("questions.ready", {"questions": questions}, agentId=analyst.id, taskId="req")
            if ready:
                await run.emit("approval.requested", {"version": version}, agentId=analyst.id, taskId="req")

            await run.emit(
                "agent.status",
                {"status": "waiting_user", "detail": "等待你确认方案" if ready else "等待你的回答与反馈"},
                agentId=analyst.id, taskId="req",
            )
            user = await run.wait_input()
            await run.emit("user.input", {"text": user.get("text", ""), "kind": user.get("kind", "message")})

            if ready and user.get("kind") == "approve":
                await run.emit("approval.granted", {"version": version}, agentId=analyst.id, taskId="req")
                await run.emit(
                    "proposal.final", {"version": version, "content": proposal, "packages": packages},
                    agentId=analyst.id, taskId="req",
                )
                await run.emit("agent.status", {"status": "done"}, agentId=analyst.id, taskId="req")
                await run.emit(
                    "task.completed", {"title": "需求分析与工作拆解", "output": proposal},
                    agentId=analyst.id, taskId="req", round=1,
                )
                break

            if ready and user.get("kind") == "reject":
                await run.emit("approval.rejected", {"note": "用户选择继续修改"}, agentId=analyst.id, taskId="req")

            text = user.get("text", "")
            if not ready and user.get("kind") == "approve":
                text = "（用户希望尽快定稿：如无未澄清问题，请直接给出含 work_packages 工作包拆解的完整方案并置 ready_for_approval=true）"
            elif not text:
                text = "（请继续完善方案）"
            history.append({"role": "assistant", "content": raw})
            history.append({"role": "user", "content": text})
            turns += 1

        # ---- 任务分配门
        if not packages:
            packages = _fallback_packages()
        await run.emit("phase.changed", {"phase": "assigning"})
        options = [{"id": a.id, "name": a.name, "role": a.role, "binding": a.binding} for a in store.agents if a.enabled]
        await run.emit("assignment.requested", {"packages": packages, "agents": options})

        user = await run.wait_input()
        if user.get("kind") == "assignment":
            assignments = _validate_assignments(user.get("assignments") or [], packages, options)
            await run.emit("user.input", {"text": "已确认任务分配，开始执行", "kind": "assignment"})
            await run.emit("assignment.confirmed", {"assignments": assignments})
            return proposal, packages, assignments

        # 用户选择返回修改方案 → 回到需求对话
        await run.emit("user.input", {"text": user.get("text") or "（返回修改方案）", "kind": user.get("kind", "message")})
        await run.emit("phase.changed", {"phase": "analyzing"})
        history.append({"role": "assistant", "content": last_raw or "（已给出方案与工作拆解）"})
        history.append({"role": "user", "content": user.get("text") or "（请根据我的反馈继续调整方案与工作拆解）"})
        turns += 1
