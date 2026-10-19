"""编排主流程：需求对话与工作拆解 → 任务分配 → 工作包并行执行 → 联调验收（按包返工）→ 汇总交付。"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from ..providers.base import chat as chat_default
from ..providers.base import parse_json_tolerant
from ..sandbox import (
    clean_caches,
    detect_checks,
    failed_checks,
    format_report,
    run_command,
    visible_files,
)
from ..schemas import Agent
from ..store import DATA_DIR, now
from ..workspace import Workspace, extract_artifacts
from .analyst_loop import run_requirements_and_assignment
from .bus import EventBus, Run
from .context import DEP_LIMIT, PACKAGE_LIMIT, PROPOSAL_LIMIT, REPORT_LIMIT, clip
from .errors import EngineError
from .executor import delta_flusher, execute_dag, run_task

MAX_REWORK = 2  # 联调验收不通过后的最大返工轮数
WORKSPACE_DIR = DATA_DIR / "workspace"


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
        raise
    except EngineError as e:
        run.meta.status = "failed"
        run.meta.finishedAt = now()
        await run.emit("run.failed", {"message": str(e)})
    except Exception as e:  # 兜底：任何未预期异常都终结为失败而不是挂死
        run.meta.status = "failed"
        run.meta.finishedAt = now()
        await run.emit("run.failed", {"message": f"内部错误：{e}"})
    finally:
        # 终态 meta 落盘（事件流已是追加写，无需整份重写）
        from ..store import save_run_meta

        save_run_meta(run.meta)


def _combine_outputs(packages: list[dict], impl_by_key: dict[str, str]) -> str:
    parts = []
    for p in packages:
        out = impl_by_key.get(p["key"], "")
        if out:
            parts.append(f"### 工作包 · {p['agentName']}\n\n{out}")
    return "\n\n---\n\n".join(parts)


def _package_brief(p: dict) -> str:
    return (
        f"工作包 {p['key']}：{p['agentName']}\n"
        f"职责：{p.get('responsibility', '')}\n"
        f"任务：\n" + "".join(f"- {t}\n" for t in p.get("tasks", []))
        + f"联调方式：{p.get('integration', '')}"
    )


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

    task_by_id = {t["id"]: t for t in plan_tasks}
    clipped_proposal = clip(proposal, PROPOSAL_LIMIT, "需求方案")
    workspace = Workspace(WORKSPACE_DIR / run.id) if getattr(store.settings, "workspace", None) and store.settings.workspace.enabled else None

    async def persist_artifacts(task: dict, output: str) -> None:
        """把产出里的 ```path=...``` 文件块写到工作区，并发出 artifact.written 事件。"""
        if workspace is None:
            return
        for f in extract_artifacts(output):
            try:
                info = workspace.write(f["path"], f["content"])
            except ValueError as e:
                await run.emit(
                    "artifact.rejected",
                    {"path": f["path"], "reason": str(e)},
                    agentId=task.get("agentId"), taskId=task["id"], round=task.get("round"),
                )
                continue
            await run.emit(
                "artifact.written",
                {**info, "package": task.get("title")},
                agentId=task.get("agentId"), taskId=task["id"], round=task.get("round"),
            )

    async def run_checks(task_id: str, round_no: int, agent_id: str | None) -> tuple[str, list[dict]]:
        """在工作区跑白名单校验命令，把结果作为事件与文本交给测试工程师。

        返回 (给 tester 的报告文本, 结构化结果)。
        """
        if workspace is None:
            return "", []
        sb = store.settings.sandbox
        if not sb.enabled:
            return "（命令执行已在设置中关闭，本次仅做文档级验收）", []

        commands = detect_checks(workspace.root)
        results: list[dict] = []
        for cmd in commands:
            r = run_command(
                workspace.root,
                cmd,
                timeout=sb.timeoutSeconds,
                max_output=sb.maxOutputChars,
            )
            results.append(r)
            await run.emit(
                "check.finished",
                {
                    "command": r["command"],
                    "allowed": r["allowed"],
                    "exitCode": r["exitCode"],
                    "timedOut": r["timedOut"],
                    "durationMs": r["durationMs"],
                    "truncated": r["truncated"],
                    "stdout": clip(r.get("stdout") or "", 4000, "输出"),
                    "stderr": clip(r.get("stderr") or "", 4000, "错误输出"),
                },
                agentId=agent_id, taskId=task_id, round=round_no,
            )
        # 校验过程会留下 __pycache__/.pytest_cache，清掉以免污染交付文件列表
        clean_caches(workspace.root)
        return format_report(results, visible_files(workspace.root)), results

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

    def build_package_prompt(src: dict, dep_outputs: dict[str, str], prev: str | None = None, issues: list[str] | None = None) -> str:
        p = src["package"]
        dep_text = "\n\n".join(f"【上游产出 · {k}】\n{v}" for k, v in dep_outputs.items()) or "（无）"
        parts = [f"最终需求方案：\n{clipped_proposal}", f"你负责的工作包：{p['agentName']}", _package_brief(p)]
        if prev is not None:
            parts.append(f"你上一轮的产出：\n{clip(prev, PACKAGE_LIMIT, '上轮产出')}")
        if issues:
            parts.append("联调验收失败项（与本工作包相关）：\n- " + "\n- ".join(issues))
        parts.append(f"上游依赖产出：\n{clip(dep_text, DEP_LIMIT, '上游产出')}")
        if workspace is not None:
            parts.append(
                "交付文件约定：需要落盘的文件请用带 path 的代码块输出，系统会自动写入工作区，例如\n"
                "```python path=src/main.py\n...\n```\n"
                "没有 path 的代码块只作为说明示例，不会落盘。"
            )
        parts.append("请逐项修复并输出修订后的完整结果报告。" if prev is not None else "请完成该工作包并输出结果报告。")
        return "\n\n".join(parts)

    async def run_one(task: dict, dep_outputs: dict[str, str]) -> str:
        agent = agent_by_id.get(task["agentId"])
        if not agent:
            raise EngineError(f"工作包「{task['title']}」分配的 Agent 不存在或已被删除")
        p = task["package"]
        output = await run_task(
            run, chat_fn, agent,
            task_id=task["id"], title=task["title"], round=1,
            user_content=build_package_prompt(task, dep_outputs),
            hint={"taskKind": "work_package", "round": 1, "packageName": p["agentName"], "packageTasks": p.get("tasks", [])},
            binding=task["binding"],
        )
        await persist_artifacts(task, output)
        return output

    outputs = await execute_dag(plan_tasks, run_one)
    impl_by_key = {t["id"]: outputs.get(t["id"], "") for t in plan_tasks}

    round = 1
    verdict: dict = {"passed": True, "report": "", "failed_items": [], "failed_by_pkg": {}, "parsed": True}
    if tester:
        package_keys = {t["id"] for t in plan_tasks}
        while True:
            combined = "\n\n".join(
                f"【{t['title']}】\n{clip(impl_by_key[t['id']], PACKAGE_LIMIT, '工作包产出')}" for t in plan_tasks
            )
            # 真实校验：在工作区跑白名单命令（pytest / 语法检查），结果喂给测试工程师
            check_report, check_results = await run_checks(f"test-{round}", round, tester.id)
            check_failures = failed_checks(check_results)
            raw = await run_task(
                run, chat_fn, tester,
                task_id=f"test-{round}", title="联调验收" if round == 1 else f"联调验收（复测 {round - 1}）", round=round,
                user_content=(
                    f"最终需求方案（含各工作包职责与联调约定）：\n{clipped_proposal}\n\n"
                    f"各工作包产出：\n{combined}\n\n"
                    + (f"【机器执行结果（工作区真实命令，可作为客观依据）】\n{check_report}\n\n" if check_report else "")
                    + "请对照需求方案的验收标准做联调验收，输出 JSON；failed_items 每项注明所属工作包 key，"
                    '形如 {"package": "pkg-1", "issue": "问题描述"}。'
                    + ("\n注意：机器校验存在失败项，若问题无法归属到具体工作包请用 package=\"_global\"。" if check_failures else "")
                ),
                hint={"taskKind": "integration", "round": round, "packages": sorted(package_keys),
                      "checkFailures": check_failures},
            )
            verdict = _parse_verdict(raw, package_keys)
            # 机器校验失败是客观事实：模型若判通过，也必须降级为不通过（防止只看文档放水）
            if check_failures and verdict["parsed"] and verdict["passed"]:
                verdict["passed"] = False
                verdict["failed_items"] = [*verdict["failed_items"], *check_failures]
                verdict["failed_by_pkg"].setdefault("_global", []).extend(check_failures)
                verdict["report"] = (
                    f"{verdict['report']}\n\n> ⚠️ 工作区命令校验未通过，已自动判定验收不通过：\n"
                    + "\n".join(f"- {f}" for f in check_failures)
                )
            await _emit_verdict(run, tester.id, round, verdict)
            if not verdict["parsed"]:
                # 解析失败时既不放行也不返工：标记为待人工确认，直接进入交付
                break
            if verdict["passed"] or round > MAX_REWORK:
                break

            # 确定需要返工的工作包（联调失败项按包归属；无法归属则全部返工）
            failed_by_pkg: dict[str, list[str]] = verdict["failed_by_pkg"]
            involved = [k for k in failed_by_pkg if k in package_keys] if failed_by_pkg else []
            if not involved or "_global" in failed_by_pkg:
                involved = [t["id"] for t in plan_tasks]

            round += 1
            rework_ids = [f"{k}-r{round}" for k in involved]
            for key in involved:
                src = task_by_id[key]
                issues = failed_by_pkg.get(key) or failed_by_pkg.get("_global") or []
                await run.emit(
                    "handoff",
                    {"kind": "rework", "fromTask": f"test-{round - 1}", "toTask": f"{key}-r{round}",
                     "note": f"联调不通过，工作包「{src['title']}」带失败项返工", "failedItems": issues},
                    agentId=src["agentId"], taskId=f"{key}-r{round}", round=round,
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

            # 返工包之间相互独立 → 并行；上游产出用最新版本，保证多包联动返工语义正确
            async def run_rework(key: str) -> str:
                src = task_by_id[key]
                issues = failed_by_pkg.get(key) or failed_by_pkg.get("_global") or []
                agent = agent_by_id.get(src["agentId"])
                if not agent:
                    raise EngineError(f"工作包「{src['title']}」分配的 Agent 不存在或已被删除")
                dep_outputs = {
                    d: impl_by_key.get(d, "") for d in src.get("dependsOn", []) if d in impl_by_key
                }
                out = await run_task(
                    run, chat_fn, agent,
                    task_id=f"{key}-r{round}", title=f"{src['title']}（返工 {round - 1}）", round=round,
                    user_content=build_package_prompt(src, dep_outputs, prev=impl_by_key[key], issues=issues),
                    hint={"taskKind": "work_package", "round": round, "packageName": src["package"]["agentName"],
                          "packageTasks": src["package"].get("tasks", []), "issues": issues},
                    binding=src["binding"],
                )
                await persist_artifacts({**src, "id": f"{key}-r{round}", "round": round}, out)
                return out

            rework_results = await asyncio.gather(*[run_rework(k) for k in involved])
            for key, out in zip(involved, rework_results):
                impl_by_key[key] = out

    return impl_by_key, verdict.get("report", ""), bool(verdict.get("passed")), verdict.get("failed_items", [])


def _parse_verdict(raw: str, package_keys: set[str]) -> dict:
    """解析联调结论。解析失败时 passed=False 且 parsed=False：既不误放行，也不触发无意义的返工。"""
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
                "failed_items": display, "failed_by_pkg": by_pkg, "parsed": True}
    # 解析失败：不能默认通过（那等于验收门失效），也不返工（失败项无从归属）
    return {
        "passed": False,
        "parsed": False,
        "report": f"{raw}\n\n> ⚠️ 未能解析出结构化验收结论，本次验收结果需人工复核。",
        "failed_items": ["验收结论解析失败，结果未经结构化校验，请人工复核"],
        "failed_by_pkg": {},
    }


async def _emit_verdict(run: Run, tester_agent_id: str, round: int, verdict: dict) -> None:
    await run.emit(
        "review.verdict",
        {"round": round, "passed": verdict.get("passed", False), "parsed": verdict.get("parsed", True),
         "report": verdict.get("report", ""), "failedItems": verdict.get("failed_items", [])},
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

    async def on_usage(payload: dict) -> None:
        await run.emit("usage.reported", {**payload, "taskTitle": "汇总交付"}, agentId=orchestrator.id)

    try:
        summary = await chat_fn(
            run.store,
            orchestrator,
            orchestrator.persona,
            [{
                "role": "user",
                "content": (
                    f"请汇总以下材料，输出最终交付文档（markdown）。\n\n"
                    f"【最终需求方案】\n{clip(proposal, PROPOSAL_LIMIT, '需求方案')}\n\n"
                    f"【各工作包实现交付】\n{clip(impl, PROPOSAL_LIMIT, '实现交付')}\n\n"
                    f"【联调验收结论】\n{clip(report or '未执行联调验收', REPORT_LIMIT, '验收报告')}\n\n"
                    f"【是否通过】{'通过' if passed else '未完全通过'}\n"
                    f"【遗留失败项】{json.dumps(failed_items, ensure_ascii=False)}"
                ),
            }],
            {"purpose": "summary", "proposal": proposal, "implementation": impl, "report": report,
             "issues": failed_items, "passed": passed},
            on_delta=on_delta,
            on_usage=on_usage,
        )
        await flush()
        await run.emit("agent.status", {"status": "done"}, agentId=orchestrator.id)
        return summary
    except Exception as e:
        await flush()
        await run.emit("agent.status", {"status": "done"}, agentId=orchestrator.id)
        return f"# 最终交付\n\n（编排者汇总失败：{e}）\n\n## 一、最终需求方案\n{proposal}\n\n## 二、实现交付\n{impl}\n\n## 三、联调验收结论\n{report}"
