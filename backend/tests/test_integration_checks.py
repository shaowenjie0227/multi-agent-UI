"""联调验收与机器校验的联动：模型说通过但命令失败时必须降级为不通过。"""
from __future__ import annotations

import json

import pytest

from app.engine.bus import EventBus, Run
from app.engine.orchestrator import _execute_packages
from app.schemas import Agent, ProviderModel
from app.store import Store


class FakeChat:
    """按角色脚本化返回；记录收到的 tester prompt。"""

    def __init__(self, tester_raw: str) -> None:
        self.tester_raw = tester_raw
        self.tester_prompts: list[str] = []
        self.calls: list[str] = []

    async def __call__(self, store, agent: Agent, system, messages, hint=None, binding=None, on_delta=None, on_usage=None):
        hint = hint or {}
        self.calls.append(agent.role)
        if hint.get("taskKind") == "work_package":
            return "工作包产出"
        if hint.get("taskKind") == "integration":
            self.tester_prompts.append(messages[0]["content"])
            return self.tester_raw
        return "ok"


@pytest.fixture()
def store(tmp_data):
    s = Store()
    # 只留一个开发 + 一个测试，简化流程
    s.agents = [
        Agent(id="a_dev", name="开发", role="developer", binding="mock"),
        Agent(id="a_test", name="测试", role="tester", binding="mock"),
        Agent(id="a_orch", name="编排", role="orchestrator", binding="mock"),
    ]
    s._save_agents()
    return s


PACKAGES = [
    {"key": "pkg-1", "agentName": "开发", "responsibility": "实现", "tasks": ["写代码"], "integration": "接口对齐", "dependsOn": []},
]
ASSIGNMENTS = [{"packageKey": "pkg-1", "agentId": "a_dev", "agentName": "开发", "binding": "mock"}]


def make_run(store) -> Run:
    return Run("r_t", "任务", store, EventBus())


@pytest.mark.asyncio
async def test_check_failure_overrides_model_pass(store, tmp_path, monkeypatch):
    """模型判 passed=true，但工作区 py_compile 失败 → 最终必须判不通过。"""
    ws = tmp_path / "r_t"
    ws.mkdir()
    (ws / "broken.py").write_text("def f(:\n", "utf-8")
    monkeypatch.setattr("app.engine.orchestrator.WORKSPACE_DIR", tmp_path)
    store.update_settings(workspace={"enabled": True}, sandbox={"enabled": True, "timeoutSeconds": 20})

    run = make_run(store)
    chat = FakeChat(json.dumps({"passed": True, "report": "看着没问题", "failed_items": []}))
    _, report, passed, failed = await _execute_packages(run, chat, PACKAGES, ASSIGNMENTS, "需求方案")

    assert passed is False
    assert any("py_compile" in f for f in failed)
    assert "工作区命令校验未通过" in report
    # tester 的 prompt 里应带上机器执行结果
    assert "机器执行结果" in chat.tester_prompts[0]
    # 必须有 check.finished 事件
    checks = [e for e in run.events if e.type == "check.finished"]
    assert checks and checks[0].payload["exitCode"] != 0


@pytest.mark.asyncio
async def test_check_pass_keeps_model_verdict(store, tmp_path, monkeypatch):
    ws = tmp_path / "r_t"
    ws.mkdir()
    (ws / "ok.py").write_text("print('hi')\n", "utf-8")
    monkeypatch.setattr("app.engine.orchestrator.WORKSPACE_DIR", tmp_path)
    store.update_settings(workspace={"enabled": True}, sandbox={"enabled": True})

    run = make_run(store)
    chat = FakeChat(json.dumps({"passed": True, "report": "ok", "failed_items": []}))
    _, _, passed, failed = await _execute_packages(run, chat, PACKAGES, ASSIGNMENTS, "需求方案")
    assert passed is True
    assert failed == []
    check = next(e for e in run.events if e.type == "check.finished")
    assert check.payload["exitCode"] == 0


@pytest.mark.asyncio
async def test_sandbox_disabled_skips_checks(store, tmp_path, monkeypatch):
    ws = tmp_path / "r_t"
    ws.mkdir()
    (ws / "broken.py").write_text("def f(:\n", "utf-8")
    monkeypatch.setattr("app.engine.orchestrator.WORKSPACE_DIR", tmp_path)
    store.update_settings(workspace={"enabled": True}, sandbox={"enabled": False})

    run = make_run(store)
    chat = FakeChat(json.dumps({"passed": True, "report": "ok", "failed_items": []}))
    _, _, passed, _ = await _execute_packages(run, chat, PACKAGES, ASSIGNMENTS, "需求方案")
    assert passed is True  # 关闭后不做机器校验，完全听模型
    assert not [e for e in run.events if e.type == "check.finished"]
    assert "命令执行已在设置中关闭" in chat.tester_prompts[0]


@pytest.mark.asyncio
async def test_workspace_disabled_skips_checks(store, tmp_path, monkeypatch):
    monkeypatch.setattr("app.engine.orchestrator.WORKSPACE_DIR", tmp_path)
    store.update_settings(workspace={"enabled": False}, sandbox={"enabled": True})

    run = make_run(store)
    chat = FakeChat(json.dumps({"passed": True, "report": "ok", "failed_items": []}))
    _, _, passed, _ = await _execute_packages(run, chat, PACKAGES, ASSIGNMENTS, "需求方案")
    assert passed is True
    assert not [e for e in run.events if e.type == "check.finished"]


@pytest.mark.asyncio
async def test_rework_triggered_by_check_failure(store, tmp_path, monkeypatch):
    """机器校验失败且无法归属工作包时归到 _global，触发全部工作包返工。"""
    ws = tmp_path / "r_t"
    ws.mkdir()
    (ws / "broken.py").write_text("def f(:\n", "utf-8")
    monkeypatch.setattr("app.engine.orchestrator.WORKSPACE_DIR", tmp_path)
    store.update_settings(workspace={"enabled": True}, sandbox={"enabled": True})

    run = make_run(store)
    # 第一轮模型判通过（会被机器校验压成不通过）→ 第二轮复测改判通过
    chat = FakeChat(json.dumps({"passed": True, "report": "ok", "failed_items": []}))

    async def chat_seq(*args, **kwargs):
        hint = kwargs.get("hint") or (args[4] if len(args) > 4 else {})
        if hint.get("taskKind") == "integration":
            round_no = hint.get("round", 1)
            # 第二轮前修掉语法错误，模拟返工后通过
            if round_no >= 2:
                (ws / "broken.py").write_text("print('fixed')\n", "utf-8")
        return await chat(*args, **kwargs)

    _, _, passed, _ = await _execute_packages(run, chat_seq, PACKAGES, ASSIGNMENTS, "需求方案")
    assert passed is True
    handoffs = [e for e in run.events if e.type == "handoff"]
    assert handoffs, "机器校验失败应触发返工交接"
