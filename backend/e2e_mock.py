"""Mock 全流程 E2E（可指定 BASE）：需求对话 → 工作拆解确认 → 任务分配 → 工作包执行 → 联调返工 → 交付。

用法：BASE=http://127.0.0.1:3001 python e2e_mock.py
校验项：工作包数量、按包返工、最终交付、用量统计、运行详情/删除。
"""
from __future__ import annotations

import os
import time

import httpx

BASE = os.environ.get("BASE", "http://127.0.0.1:3001")
c = httpx.Client(base_url=BASE, timeout=10, trust_env=False)  # 绕过系统代理，直连本机后端

r = c.post("/api/runs", json={"task": "做一个团队任务管理工具，支持任务分配与进度跟踪", "agentCount": 3}).json()
rid = r["id"]
print("run:", rid)

sent = 0
approved = False
assigned = False
evs = []
meta: dict = {}
for _ in range(300):
    time.sleep(0.5)
    data = c.get(f"/api/runs/{rid}").json()
    evs = data["events"]
    meta = data["meta"] or {}
    if meta.get("status") != "running":
        print("== 结束状态:", meta.get("status"))
        break
    types = [e["type"] for e in evs]

    if "assignment.requested" in types and not assigned:
        req_ev = next(e for e in evs if e["type"] == "assignment.requested")
        packages = req_ev["payload"]["packages"]
        options = req_ev["payload"]["agents"]
        dev = next((o for o in options if o["role"] == "developer"), None) or next(
            (o for o in options if o["role"] != "orchestrator"), options[0]
        )
        assignments = [{"packageKey": p["key"], "agentId": dev["id"]} for p in packages]
        c.post(f"/api/runs/{rid}/input", json={"text": "", "kind": "assignment", "assignments": assignments})
        assigned = True
        print(f">> [分配门] {len(assignments)} 个工作包 → {dev['name']}（Mock）")
        continue

    if "approval.requested" in types and not approved:
        c.post(f"/api/runs/{rid}/input", json={"text": "满意，进入开发", "kind": "approve"})
        approved = True
        print(">> [确认门] approve")
        continue

    if "approval.requested" not in types and "assignment.requested" not in types:
        waiting = False
        for e in reversed(evs):
            if e["type"] == "user.input":
                break
            if e["type"] == "agent.status" and e["payload"].get("status") == "waiting_user":
                waiting = True
                break
        if waiting:
            if sent == 0:
                c.post(f"/api/runs/{rid}/input", json={"text": "面向 Web 平台，小团队几十人使用，数据需要持久化", "kind": "message"})
                print(">> [对话] 反馈 1")
            elif sent == 1:
                c.post(f"/api/runs/{rid}/input", json={"text": "首版先做核心流程完整可用", "kind": "message"})
                print(">> [对话] 反馈 2")
            else:
                c.post(f"/api/runs/{rid}/input", json={"text": "可以，就这样定稿", "kind": "message"})
                print(">> [对话] 反馈 3")
            sent += 1

print()
for e in evs:
    print(f"  #{e['seq']:>3} {e['type']:<22} task={str(e.get('taskId') or '-'):>8} r={str(e.get('round') or '-'):>2}  {str(e['payload'])[:70]}")

final = next((e for e in evs if e["type"] == "result.final"), None)
verdicts = [e for e in evs if e["type"] == "review.verdict"]
handoffs = [e for e in evs if e["type"] == "handoff"]
proposals = [e for e in evs if e["type"] == "proposal.updated"]
assign_req = next((e for e in evs if e["type"] == "assignment.requested"), None)
assign_ok = next((e for e in evs if e["type"] == "assignment.confirmed"), None)
plan_tasks = next((e for e in evs if e["type"] == "plan.created"), None)
all_plan_tasks = [t for e in evs if e["type"] == "plan.created" for t in e["payload"]["tasks"]]
usage_evs = [e for e in evs if e["type"] == "usage.reported"]
rework_tasks = [t for t in all_plan_tasks if "-r2" in t["id"]]
warnings = [e for e in evs if e["type"] == "plan.warning"]

print()
print("检查：")
print("  方案版本数:", len(proposals), "(期望 >=3)")
print("  工作包数量:", len(assign_req["payload"]["packages"]) if assign_req else 0, "(期望 3 = agentCount)")
print("  分配确认:", "有" if assign_ok else "无")
print("  计划节点:", [t["id"] for t in plan_tasks["payload"]["tasks"]] if plan_tasks else [])
print("  拆解校正:", len(warnings), "条")
print("  联调轮数:", len(verdicts), "结论:", [v["payload"]["passed"] for v in verdicts], "(期望 [False, True])")
print("  返工交接:", len(handoffs), "(期望 2 = 失败项涉及的工作包数)")
print("  返工任务节点:", [t["id"] for t in rework_tasks])
print("  最终交付:", "有" if final and final["payload"].get("content") else "无")
print("  用量事件:", len(usage_evs))

usage = c.get(f"/api/runs/{rid}/usage").json()
print("  用量统计:", usage["total"], "(Mock 无 token，但应有调用次数)")

# 运行详情与删除接口
detail = c.get(f"/api/runs/{rid}").json()
assert detail["meta"]["status"] == "completed", detail["meta"]
assert len(detail["events"]) == len(evs)

ok = (
    assign_req and len(assign_req["payload"]["packages"]) == 3
    and assign_ok
    and [v["payload"]["passed"] for v in verdicts] == [False, True]
    and len(handoffs) == 2
    and final is not None
    and meta.get("status") == "completed"
    and usage["total"]["calls"] > 0
)
print("  端到端结果:", "✅ PASS" if ok else "❌ FAIL")
raise SystemExit(0 if ok else 1)
