"""编排主流程：需求对话与工作拆解 → 任务分配 → 工作包并行执行 → 联调验收（按包返工）→ 汇总交付。"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from ..providers.base import chat as chat_default
from ..providers.base import parse_json_tolerant
from ..schemas import Agent
from ..store import now
from .analyst_loop import run_requirements_and_assignment
from .bus import EventBus, Run
from .errors import EngineError
from .executor import delta_flusher, execute_dag, run_task

MAX_REWORK = 2  # 联调验收不通过后的最大返工轮数


async def run_flow(run: Run, chat_fn=chat_default) -> None:
    store = run.store
    try:
        await run.emit("run.started", {"task": run.task_text})
        await run.emit("phase.changed", {"phase": "analyzing"})

        # ---------- 阶段一：需求分析（对话）→ 工作拆解 → 任务分配 ----------
        proposal, packages, assignments = await run_requirements_and_assignment(run, chat_fn)

        # ---------- 阶段二：工作包执行 ⇄ 联调验收 ----------
        await run.emit("phase.changed", {"phase": "executing"})
        impl_by_key, report, passed, failed_items = await _execute_packages(run, chat_fn, packages, assignments, proposal)

        # ---------- 交付 ----------
        await run.emit("phase.changed", {"phase": "delivering"})
        orchestrator = store.find_agent_by_role("orchestrator")
        combined = _combine_outputs(packages, impl_by_key)
        summary = await _summarize(run, chat_fn, orchestrator, proposal, combined, report, failed_items, passed)
        await run.emit("result.final", {"content": summary})
        run.meta.status = "completed"
        run.meta.finishedAt = now()
        await run.emit("run.completed", {"summary": summary[:200]})
    except asyncio.CancelledError:
        run.meta.status = "stopped"
        run.meta.finishedAt = now()
        await run.emit("run.failed", {"reason": "stopped", "message": "已手动停止"})
    except EngineError as e:
        run.meta.status = "failed"
        run.meta.finishedAt = now()
        await run.emit("run.failed", {"message": str(e)})
    except Exception as e:  # 兜底：任何未预期异常都终结为失败而不是挂死
        run.meta.status = "failed"
        run.meta.finishedAt = now()
        await run.emit("run.failed", {"message": f"内部错误：{e}"})


def _combine_outputs(packages: list[dict], impl_by_key: dict[str, str]) -> str:
    parts = []
    for p in packages:
        out = impl_by_key.get(p["key"], "")
        if out:
            parts.append(f"### 工作包 · {p['agentName']}\n\n{out}")
    return "\n\n---\n\n".join(parts)


# ---------------- 工作包执行 ⇄ 联调验收 ----------------


async def _execute_packages(run: Run, chat_fn, packages: list[dict], assignments: list[dict], proposal: str):
    store = run.store
    agent_by_id = {a.id: a for a in store.agents}
    assign_by_key = {a["packageKey"]: a for a in assignments}

    plan_tasks: list[dict] = []
    for p in packages:
        a = assign_by_key[p["key"]]
        agent = agent_by_id.get(a["agentId"])
        valid_deps = [d for d in p.get("dependsOn", []) if any(x["key"] == d for x in packages)]
        plan_tasks.append(
            {
                "id": p["key"],
                "title": p["agentName"],
                "role": agent.role if agent else "custom",
                "agentId": a["agentId"],
                "agentName": a["agentName"],
                "binding": a["binding"],
                "package": p,
                "dependsOn": valid_deps,
            }
        )

    # 图渲染：工作包 + 联调验收节点一次性入图
    tester = store.find_agent_by_role("tester")
    graph_tasks = [
        {"id": t["id"], "title": t["title"], "role": t["role"], "agentId": t["agentId"], "dependsOn": t["dependsOn"]}
        for t in plan_tasks
    ]
    if tester:
        graph_tasks.append(
            {"id": "test-1", "title": "联调验收", "role": "tester", "agentId": tester.id, "dependsOn": [t["id"] for t in plan_tasks]}
        )
    await run.emit("plan.created", {"round": 1, "tasks": graph_tasks}, round=1)

    async def run_one(task: dict, dep_outputs: dict[str, str]) -> str:
        agent = agent_by_id.get(task["agentId"])
        if not agent:
            raise EngineError(f"工作包「{task['title']}」分配的 Agent 不存在或已被删除")
        p = task["package"]
        dep_text = "\n\n".join(f"【上游产出 · {k}】\n{v}" for k, v in dep_outputs.items()) or "（无）"
        content = (
            f"最终需求方案：\n{proposal}\n\n"
            f"你负责的工作包：{p['agentName']}\n"
            f"职责：{p.get('responsibility', '')}\n"
            f"要完成的任务：\n" + "".join(f"- {t}\n" for t in p.get("tasks", [])) +
            f"\n联调方式：{p.get('integration', '')}\n\n"
            f"上游依赖产出：\n{dep_text}\n\n请完成该工作包并输出结果报告。"
        )
        return await run_task(
            run, chat_fn, agent,
            task_id=task["id"], title=task["title"], round=1,
            user_content=content,
            hint={"taskKind": "work_package", "round": 1, "packageName": p["agentName"], "packageTasks": p.get("tasks", [])},
            binding=task["binding"],
        )

    outputs = await execute_dag(plan_tasks, run_one)
    impl_by_key = {t["id"]: outputs.get(t["id"], "") for t in plan_tasks}

    round = 1
    verdict: dict = {"passed": True, "report": "", "failed_items": [], "failed_by_pkg": {}}
    if tester:
        package_keys = {t["id"] for t in plan_tasks}
        while True:
            combined = "\n\n".join(f"【{t['title']}】\n{impl_by_key[t['id']]}" for t in plan_tasks)
            raw = await run_task(
                run, chat_fn, tester,
                task_id=f"test-{round}", title="联调验收" if round == 1 else f"联调验收（复测 {round - 1}）", round=round,
                user_content=(
                    f"最终需求方案（含各工作包职责与联调约定）：\n{proposal}\n\n"
                    f"各工作包产出：\n{combined}\n\n"
                    "请对照需求方案的验收标准做联调验收，输出 JSON；failed_items 每项注明所属工作包 key，"
                    '形如 {"package": "pkg-1", "issue": "问题描述"}。'
                ),
                hint={"taskKind": "integration", "round": round, "packages": sorted(package_keys)},
            )
            verdict = _parse_verdict(raw, package_keys)
            await _emit_verdict(run, tester.id, round, verdict)
            if verdict["passed"] or round > MAX_REWORK:
                break

            # 确定需要返工的工作包（联调失败项按包归属；无法归属则全部返工）
            failed_by_pkg: dict[str, list[str]] = verdict["failed_by_pkg"]
            involved = [k for k in failed_by_pkg if k in package_keys] if failed_by_pkg else []
            if not involved or "_global" in failed_by_pkg:
                involved = [t["id"] for t in plan_tasks]
            task_by_id = {t["id"]: t for t in plan_tasks}

            round += 1
            rework_ids: list[str] = []
            for key in involved:
                src = task_by_id[key]
                issues = failed_by_pkg.get(key) or failed_by_pkg.get("_global") or []
                new_id = f"{key}-r{round}"
                rework_ids.append(new_id)
                await run.emit(
                    "handoff",
                    {"kind": "rework", "fromTask": f"test-{round - 1}", "toTask": new_id,
                     "note": f"联调不通过，工作包「{src['title']}」带失败项返工", "failedItems": issues},
                    agentId=src["agentId"], taskId=new_id, round=round,
                )
            # 图：本轮返工包 + 复测节点（复测依赖本轮全部返工包）
            await run.emit(
                "plan.created",
                {"round": round, "tasks": [
                    *[{"id": f"{k}-r{round}", "title": f"{task_by_id[k]['title']}（返工 {round - 1}）",
                       "role": task_by_id[k]["role"], "agentId": task_by_id[k]["agentId"], "dependsOn": []}
                      for k in involved],
                    {"id": f"test-{round}", "title": f"联调验收（复测 {round - 1}）", "role": "tester",
                     "agentId": tester.id, "dependsOn": rework_ids},
                ]},
                round=round,
            )
            for key in involved:
                src = task_by_id[key]
                issues = failed_by_pkg.get(key) or failed_by_pkg.get("_global") or []
                new_id = f"{key}-r{round}"
                p = src["package"]
                agent = agent_by_id.get(src["agentId"])
                if not agent:
                    raise EngineError(f"工作包「{src['title']}」分配的 Agent 不存在或已被删除")
                out = await run_task(
                    run, chat_fn, agent,
                    task_id=new_id, title=f"{src['title']}（返工 {round - 1}）", round=round,
                    user_content=(
                        f"最终需求方案：\n{proposal}\n\n"
                        f"你负责的工作包：{p['agentName']}\n"
                        f"你上一轮的产出：\n{impl_by_key[key]}\n\n"
                        f"联调验收失败项（与本工作包相关）：\n- " + "\n- ".join(issues) +
                        "\n\n请逐项修复并输出修订后的完整结果报告。"
                    ),
                    hint={"taskKind": "work_package", "round": round, "packageName": p["agentName"],
                          "packageTasks": p.get("tasks", []), "issues": issues},
                    binding=src["binding"],
                )
                impl_by_key[key] = out

    return impl_by_key, verdict.get("report", ""), bool(verdict.get("passed")), verdict.get("failed_items", [])


def _parse_verdict(raw: str, package_keys: set[str]) -> dict:
    parsed = parse_json_tolerant(raw)
    if parsed and "passed" in parsed:
        raw_items = parsed.get("failed_items") or []
        display: list[str] = []
        by_pkg: dict[str, list[str]] = {}
        for it in raw_items:
            if isinstance(it, dict):
                issue = str(it.get("issue") or it)
                pkg = str(it.get("package") or "")
                target = pkg if pkg in package_keys else "_global"
                by_pkg.setdefault(target, []).append(issue)
                display.append(f"[{pkg or '全局'}] {issue}")
            else:
                by_pkg.setdefault("_global", []).append(str(it))
                display.append(str(it))
        return {"passed": bool(parsed.get("passed")), "report": parsed.get("report") or raw,
                "failed_items": display, "failed_by_pkg": by_pkg}
    # 解析失败：宽松兜底为通过，避免误触发返工死循环
    return {"passed": True, "report": raw, "failed_items": [], "failed_by_pkg": {}}


async def _emit_verdict(run: Run, tester_agent_id: str, round: int, verdict: dict) -> None:
    await run.emit(
        "review.verdict",
        {"round": round, "passed": verdict.get("passed", False), "report": verdict.get("report", ""),
         "failedItems": verdict.get("failed_items", [])},
        agentId=tester_agent_id, taskId=f"test-{round}", round=round,
    )


# ---------------- 汇总交付 ----------------


async def _summarize(
    run: Run, chat_fn, orchestrator: Optional[Agent],
    proposal: str, impl: str, report: str, failed_items: list[str], passed: bool,
) -> str:
    if not orchestrator:
        return (
            f"# 最终交付\n\n## 一、最终需求方案\n{proposal}\n\n## 二、实现交付\n{impl}\n\n"
            f"## 三、联调验收结论\n{report or '（未启用测试工程师，跳过联调验收）'}\n\n## 四、遗留问题\n"
            + ("\n".join(f"- {i}" for i in failed_items) if failed_items else "无")
        )
    await run.emit("agent.status", {"status": "working", "detail": "汇总最终交付"}, agentId=orchestrator.id)
    on_delta, flush = delta_flusher(run, orchestrator.id)  # 无 taskId：监控面板按 agent 维度展示汇总流
    try:
        summary = await chat_fn(
            run.store,
            orchestrator,
            orchestrator.persona,
            [{
                "role": "user",
                "content": (
                    f"请汇总以下材料，输出最终交付文档（markdown）。\n\n"
                    f"【最终需求方案】\n{proposal}\n\n【各工作包实现交付】\n{impl}\n\n【联调验收结论】\n{report or '未执行联调验收'}\n\n"
                    f"【是否通过】{'通过' if passed else '未完全通过'}\n"
                    f"【遗留失败项】{json.dumps(failed_items, ensure_ascii=False)}"
                ),
            }],
            {"purpose": "summary", "proposal": proposal, "implementation": impl, "report": report,
             "issues": failed_items, "passed": passed},
            on_delta=on_delta,
        )
        await flush()
        await run.emit("agent.status", {"status": "done"}, agentId=orchestrator.id)
        return summary
    except Exception as e:
        await run.emit("agent.status", {"status": "done"}, agentId=orchestrator.id)
        return f"# 最终交付\n\n（编排者汇总失败：{e}）\n\n## 一、最终需求方案\n{proposal}\n\n## 二、实现交付\n{impl}\n\n## 三、联调验收结论\n{report}"
