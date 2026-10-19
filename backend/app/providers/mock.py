"""Mock LLM：按角色/任务类型脚本化输出 + 模拟延迟，无 API key 也能完整演示全流程。"""
from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable, Optional

DELAY = 1.2
STREAM_CHUNK_LINES = 3  # 每块行数
STREAM_CHUNK_DELAY = 0.06  # 块间隔秒数，让监控面板有流式观感


async def mock_chat(role: str, messages: list[dict], hint: dict, on_delta: Optional[Callable[[str], Awaitable[None]]] = None) -> str:
    await asyncio.sleep(DELAY)
    kind = hint.get("taskKind")
    if kind == "work_package":
        text = _mock_work_package(hint)
    elif kind == "integration":
        text = _mock_integration(hint)
    elif role == "analyst":
        text = _mock_analyst(hint)
    elif role == "developer":
        text = _mock_developer(hint)
    elif role == "tester":
        text = _mock_tester(hint)
    elif role == "orchestrator":
        text = _mock_orchestrator(hint)
    else:
        text = "（Mock）该角色暂无脚本输出。"
    if on_delta is not None:
        lines = text.splitlines(keepends=True)
        for i in range(0, len(lines), STREAM_CHUNK_LINES):
            await on_delta("".join(lines[i : i + STREAM_CHUNK_LINES]))
            await asyncio.sleep(STREAM_CHUNK_DELAY)
    return text


def _task_of(messages: list[dict]) -> str:
    first = next((m for m in messages if m["role"] == "user"), None)
    return (first or {}).get("content", "用户需求")


# ---------------- 需求分析师 ----------------


def _build_packages(count: int) -> list[dict]:
    n = max(1, min(5, int(count or 3)))
    names = ["前端工程师", "后端工程师", "数据工程师", "算法工程师", "运维工程师"][:n]
    packages = []
    for i, name in enumerate(names):
        packages.append(
            {
                "key": f"pkg-{i + 1}",
                "agentName": name,
                "responsibility": f"负责第 {i + 1} 号模块的设计、实现与自测",
                "tasks": [f"完成「{name}」承担的功能开发", "输出接口说明与交付清单"],
                "integration": "按统一接口约定与其他工作包对接，共同形成最终交付物",
                "dependsOn": ["pkg-1"] if i % 2 == 1 else [],
            }
        )
    return packages


def _mock_analyst(hint: dict) -> str:
    turns = hint.get("analyst_turns", 0)
    task = hint.get("task", "用户需求")
    if turns == 0:
        proposal = (
            f"# 需求方案（初版 v1）\n\n"
            f"## 背景\n针对需求「{task[:60]}」的初步分析。\n\n"
            f"## 目标\n- 明确产品核心价值与目标用户\n- 圈定首版范围\n\n"
            f"## 范围\n- 包含：核心业务流程\n- 暂不包含：运营后台、数据看板\n\n"
            f"## 功能需求\n1. 核心流程主链路\n2. 基础数据管理\n3. 基础权限控制\n"
        )
        questions = [
            "目标用户与使用平台是什么（Web / 移动端 / 桌面）？",
            "预期用户量级与并发规模大概多少？",
            "数据是否需要持久化？有无安全合规要求？",
        ]
    elif turns == 1:
        proposal = (
            f"# 需求方案（修订版 v2）\n\n已根据您的反馈修订：\n\n"
            f"## 背景\n针对需求「{task[:60]}」，结合澄清信息调整。\n\n"
            f"## 目标\n- 明确产品核心价值与目标用户\n- 圈定首版范围\n\n"
            f"## 范围\n- 包含：核心业务流程、数据持久化\n- 暂不包含：运营后台\n\n"
            f"## 功能需求\n1. 核心流程主链路\n2. 数据管理与查询\n3. 基础权限控制\n4. 异常与边界处理\n"
        )
        questions = ["交付优先级上，首版先做核心流程完整可用，还是功能面铺开？"]
    else:
        packages = _build_packages(hint.get("agent_count"))
        breakdown = "\n".join(
            f"{i + 1}. **{p['agentName']}**：{p['responsibility']}（联调：{p['integration']}）"
            for i, p in enumerate(packages)
        )
        proposal = (
            f"# 需求方案（完整版 · 待确认）\n\n"
            f"## 一、背景\n针对需求「{task[:60]}」形成的完整需求定义。\n\n"
            f"## 二、目标\n- 首版实现核心业务闭环，可用可验收\n\n"
            f"## 三、范围\n- 包含：核心业务流程、数据持久化、权限控制、异常处理\n- 不包含：运营后台、数据看板、第三方生态对接\n\n"
            f"## 四、功能需求\n1. 核心流程主链路（创建 → 处理 → 完成）\n2. 数据管理与多条件查询\n3. 角色权限：管理员 / 普通用户\n4. 输入校验与异常提示\n\n"
            f"## 五、非功能需求\n- 支持 1000+ 用户并发访问\n- 核心接口响应 < 500ms\n- 数据每日自动备份\n\n"
            f"## 六、验收标准\n1. 主流程可端到端走通，无阻断缺陷\n2. 越权访问被拒绝并记录\n3. 非法输入有校验与友好提示\n4. 连续失败登录触发锁定\n\n"
            f"## 七、工作拆解（{len(packages)} 个工作包）\n{breakdown}\n"
        )
        questions = []
    return json.dumps(
        {"proposal": proposal, "questions": questions, "ready_for_approval": turns >= 2,
         "work_packages": _build_packages(hint.get("agent_count")) if turns >= 2 else []},
        ensure_ascii=False,
    )


# ---------------- 工作包执行（任务分配后的通用产出） ----------------


def _mock_work_package(hint: dict) -> str:
    round_no = hint.get("round", 1)
    name = hint.get("packageName", "工作包")
    tasks = hint.get("packageTasks") or []
    issues = hint.get("issues") or []
    head = "" if round_no <= 1 else "## 本轮修复点\n" + "".join(f"- 已修复：{i}\n" for i in issues) + "\n"
    slug = _slug(name)
    fix_note = "（返工修订）" if round_no > 1 else ""
    # 交付真实文件块：让 Mock 模式也能演示"产出落盘到工作区"
    files = (
        f"## 交付文件\n\n"
        f"```python path=src/{slug}/service.py\n"
        f'"""{name} · 核心实现{fix_note}"""\n\n'
        f"def handle(request):\n"
        f"    \"\"\"{name} 主入口{fix_note}。\"\"\"\n"
        f"    if not request:\n"
        f"        raise ValueError(\"request 不能为空\")\n"
        f"    return {{\"module\": \"{slug}\", \"round\": {round_no}, \"payload\": request}}\n"
        f"```\n\n"
        f"```markdown path=docs/{slug}.md\n"
        f"# {name} 交付说明{fix_note}\n\n"
        + "".join(f"- [x] {t}\n" for t in tasks) +
        f"\n## 联调约定\n与上下游工作包按统一 JSON 结构对接。\n"
        f"```"
    )
    return (
        f"{head}"
        f"# {name} · 工作包结果报告（第 {round_no} 轮）\n\n"
        f"## 任务完成情况\n" + "".join(f"- [x] {t}\n" for t in tasks) + "\n"
        f"## 产出说明\n- 已按联调约定完成本工作包全部任务（Mock 演示输出）\n- 接口与数据结构已按约定对齐\n\n"
        f"{files}\n\n"
        f"## 移交清单\n- 模块实现与说明文档\n- 联调对接说明"
    )


def _slug(name: str) -> str:
    """角色名 → 目录名（中文保留，去掉标点空格）。"""
    import re

    cleaned = re.sub(r"[^\w\u4e00-\u9fff-]", "", name or "pkg")
    return cleaned or "pkg"


def _mock_integration(hint: dict) -> str:
    round_no = hint.get("round", 1)
    packages = hint.get("packages") or []
    # 真实工作区校验结果：让 Mock 也能反映机器执行这一客观依据
    check_failures = hint.get("checkFailures") or []
    check_block = ""
    if check_failures:
        check_block = "\n## 机器校验\n" + "".join(f"- ❌ {f}\n" for f in check_failures)
    else:
        check_block = "\n## 机器校验\n- ✅ 工作区命令全部通过（或未产生可执行文件）\n"

    if round_no <= 1 and packages:
        p1 = packages[0]
        p2 = packages[min(1, len(packages) - 1)]
        issues = [
            {"package": p1, "issue": "与其他工作包的接口字段命名不一致，联调对接失败"},
            {"package": p2, "issue": "异常场景缺少统一错误码约定，需补充联调约定"},
        ]
        rows = "\n".join(f"| {p} | 接口对接与异常约定 | {'❌' if p in (p1, p2) else '✅'} |" for p in packages)
        report = (
            f"# 联调验收报告（第 1 轮）\n\n## 验收对照\n| 工作包 | 检查项 | 结果 |\n|---|---|---|\n{rows}\n"
            f"{check_block}\n"
            f"## 结论\n❌ 联调未通过，存在 {len(issues)} 个失败项，需按工作包返工。"
        )
    else:
        issues = []
        rows = "\n".join(f"| {p} | 接口对接与异常约定 | ✅ |" for p in packages)
        report = (
            f"# 联调验收报告（第 {round_no} 轮 · 复测）\n\n## 验收对照\n| 工作包 | 检查项 | 结果 |\n|---|---|---|\n{rows}\n"
            f"{check_block}\n"
            f"## 结论\n✅ 全部工作包对接通过，满足验收标准，建议进入交付。"
        )
    return json.dumps({"passed": not issues, "report": report, "failed_items": issues}, ensure_ascii=False)


# ---------------- 兼容保留：固定角色脚本（历史回放/直接使用内置角色时） ----------------


def _mock_developer(hint: dict) -> str:
    round_no = hint.get("round", 1)
    issues = hint.get("issues", [])
    fix_head = "" if round_no <= 1 else "## 本轮修复点\n" + "".join(f"- 已修复：{i}\n" for i in issues) + "\n"
    return (
        f"{fix_head}"
        f"# 技术实现方案（第 {round_no} 轮）\n\n"
        f"## 技术选型\n- 前端：React + TypeScript\n- 后端：FastAPI + PostgreSQL\n- 部署：Docker Compose\n\n"
        f"## 架构设计\n```\n[Web 前端] --HTTPS--> [API 网关] --> [业务服务] --> [(PostgreSQL)]\n```\n\n"
        f"## 模块划分\n1. 用户与权限模块：登录、JWT 鉴权、失败锁定（**满足验收标准 2/4**）\n2. 核心业务模块：主流程状态机\n3. 数据模块：校验、备份任务\n\n"
        f"## 核心实现\n```python\n"
        f"def login(user, pwd):\n"
        f"    if is_locked(user): raise HTTPException(423, '账号已锁定')\n"
        f"    if not verify(user, pwd):\n"
        f"        record_failure(user)          # 连续失败 5 次锁定 30 分钟\n"
        f"        raise HTTPException(401, '用户名或密码错误')\n"
        f"    return issue_jwt(user)\n```\n\n"
        f"## 部署与风险\n- 每日 02:00 自动备份数据库\n- 风险：历史数据迁移需灰度"
    )


def _mock_tester(hint: dict) -> str:
    round_no = hint.get("round", 1)
    if round_no <= 1:
        report = (
            f"# 测试报告（第 1 轮）\n\n## 测试用例\n"
            f"| 编号 | 用例 | 结果 |\n|---|---|---|\n| TC1 | 主流程端到端 | ✅ |\n| TC2 | 越权访问拒绝 | ✅ |\n"
            f"| TC3 | 非法输入校验 | ❌ 未实现统一校验 |\n| TC4 | 连续失败登录锁定 | ❌ 未实现锁定逻辑 |\n\n"
            f"## 结论\n未全部通过，存在 2 个不通过项。"
        )
        failed = ["输入校验缺失：表单与接口未做统一校验，非法输入直接落库", "登录失败锁定未实现：连续失败不触发锁定，不满足验收标准 4"]
    else:
        report = (
            f"# 测试报告（第 {round_no} 轮 · 复测）\n\n## 测试用例\n"
            f"| 编号 | 用例 | 结果 |\n|---|---|---|\n| TC1 | 主流程端到端 | ✅ |\n| TC2 | 越权访问拒绝 | ✅ |\n"
            f"| TC3 | 非法输入校验 | ✅ 已修复 |\n| TC4 | 连续失败登录锁定 | ✅ 已修复 |\n\n"
            f"## 结论\n✅ 全部通过，满足验收标准，建议进入交付。"
        )
        failed = []
    return json.dumps({"passed": round_no > 1, "report": report, "failed_items": failed}, ensure_ascii=False)


def _mock_orchestrator(hint: dict) -> str:
    purpose = hint.get("purpose", "plan")
    if purpose == "plan":
        return json.dumps(
            {
                "tasks": [
                    {"id": "dev-1", "role": "developer", "title": "开发实现", "instruction": "依据最终需求方案完成技术实现", "dependsOn": []},
                    {"id": "test-1", "role": "tester", "title": "需求测试", "instruction": "对照验收标准测试开发产出", "dependsOn": ["dev-1"]},
                ]
            },
            ensure_ascii=False,
        )
    proposal = hint.get("proposal", "")
    implementation = hint.get("implementation", "")
    report = hint.get("report", "")
    issues = hint.get("issues") or []
    leftover = ("\n".join(f"- {i}" for i in issues)) if issues else "- 无"
    return (
        f"# 最终交付\n\n## 一、最终需求方案\n{proposal}\n\n## 二、实现交付\n{implementation}\n\n"
        f"## 三、测试/联调结论\n{report}\n\n## 四、遗留问题\n{leftover}"
    )
