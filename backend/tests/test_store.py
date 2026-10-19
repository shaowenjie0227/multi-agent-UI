"""配置存储：种子数据、原子落盘、运行收敛与删除。"""
from __future__ import annotations

import json

from app.schemas import RunEvent, RunMeta
from app.store import (
    append_run_event,
    delete_run_file,
    events_path,
    load_run_events,
    load_run_meta,
    load_run_metas,
    meta_path,
    reconcile_stale_runs,
    save_run,
    save_run_meta,
)


def test_store_seeds_providers_agents_and_knowledge(store, tmp_data):
    assert {p.id for p in store.providers} == {"zhipu", "xai", "deepseek"}
    assert len(store.agents) == 4
    assert {a.role for a in store.agents} == {"orchestrator", "analyst", "developer", "tester"}
    # 知识库从包内种子复制到数据目录，保证新环境推荐功能可用
    kb = tmp_data / "model_knowledge.json"
    assert kb.exists()
    assert json.loads(kb.read_text("utf-8"))["models"]


def test_provider_crud_persists(store, tmp_data):
    from app.schemas import Provider

    store.add_provider(Provider(id="p_x", name="测试", baseUrl="https://x.test/v1", apiKey="sk-1234567890"))
    saved = json.loads((tmp_data / "providers.json").read_text("utf-8"))
    assert any(p["id"] == "p_x" for p in saved["providers"])
    store.update_provider("p_x", {"name": "改名"})
    saved = json.loads((tmp_data / "providers.json").read_text("utf-8"))
    assert next(p for p in saved["providers"] if p["id"] == "p_x")["name"] == "改名"


def test_resolve_binding_errors(store):
    import pytest

    with pytest.raises(ValueError):
        store.resolve_binding("mock")
    with pytest.raises(ValueError):
        store.resolve_binding("nope:m_1")


def test_run_saved_and_loaded(store):
    meta = RunMeta(id="r_test1", task="t", status="running", createdAt=1.0)
    events = [RunEvent(seq=1, runId="r_test1", type="run.started", ts=1.0, payload={"task": "t"})]
    save_run(meta, events)
    assert load_run_meta("r_test1").status == "running"
    assert [e.type for e in load_run_events("r_test1")] == ["run.started"]
    assert [m.id for m in load_run_metas()] == ["r_test1"]


def test_reconcile_marks_stale_runs_interrupted(store):
    save_run(RunMeta(id="r_live", task="a", status="running", createdAt=1.0),
             [RunEvent(seq=1, runId="r_live", type="run.started", ts=1.0)])
    save_run(RunMeta(id="r_done", task="b", status="completed", createdAt=2.0),
             [RunEvent(seq=1, runId="r_done", type="run.started", ts=2.0)])

    fixed = reconcile_stale_runs()
    assert fixed == ["r_live"]
    meta = load_run_meta("r_live")
    assert meta.status == "interrupted" and meta.finishedAt
    events = load_run_events("r_live")
    assert events[-1].type == "run.failed"
    assert events[-1].payload["reason"] == "interrupted"
    # 已完成的运行不应被改动
    assert load_run_meta("r_done").status == "completed"


def test_reconcile_is_idempotent(store):
    save_run(RunMeta(id="r_x", task="a", status="running", createdAt=1.0), [])
    reconcile_stale_runs()
    before = load_run_events("r_x")
    assert reconcile_stale_runs() == []
    assert len(load_run_events("r_x")) == len(before)


def test_delete_run_file(store):
    save_run(RunMeta(id="r_del", task="a", status="completed", createdAt=1.0), [])
    assert delete_run_file("r_del") is True
    assert load_run_events("r_del") is None
    assert delete_run_file("r_del") is False


def test_corrupt_run_file_degrades_gracefully(store, tmp_data):
    (tmp_data / "runs" / "r_bad.json").write_text("{not json", "utf-8")
    assert load_run_events("r_bad") is None
    assert load_run_meta("r_bad") is None
    assert all(m.id != "r_bad" for m in load_run_metas())


# ---------------- JSONL 追加落盘 ----------------


def make_event(rid: str, seq: int, etype: str = "agent.output") -> RunEvent:
    return RunEvent(seq=seq, runId=rid, type=etype, ts=float(seq), payload={"n": seq})


def test_append_writes_one_line_per_event(store, tmp_data):
    rid = "r_jsonl"
    save_run_meta(RunMeta(id=rid, task="t", status="running", createdAt=1.0))
    for i in range(1, 6):
        append_run_event(rid, make_event(rid, i))

    raw = (tmp_data / "runs" / f"{rid}.events.jsonl").read_text("utf-8")
    assert raw.count("\n") == 5
    assert len(load_run_events(rid)) == 5
    assert [e.seq for e in load_run_events(rid)] == [1, 2, 3, 4, 5]


def test_append_is_incremental_not_rewrite(store, tmp_data):
    """追加写不应重写已有内容：先写 2 条，再追加 1 条后文件行数必须是 3（而不是 3×2 行）。"""
    rid = "r_inc"
    save_run_meta(RunMeta(id=rid, task="t", status="running", createdAt=1.0))
    append_run_event(rid, make_event(rid, 1))
    append_run_event(rid, make_event(rid, 2))
    first = (tmp_data / "runs" / f"{rid}.events.jsonl").read_text("utf-8")
    append_run_event(rid, make_event(rid, 3))
    second = (tmp_data / "runs" / f"{rid}.events.jsonl").read_text("utf-8")
    assert second.startswith(first)
    assert second.count("\n") == 3


def test_partial_last_line_is_skipped(store, tmp_data):
    """进程被 kill 可能留下半行 JSON：加载时应跳过该行、保留其余事件。"""
    rid = "r_cut"
    save_run_meta(RunMeta(id=rid, task="t", status="running", createdAt=1.0))
    append_run_event(rid, make_event(rid, 1))
    append_run_event(rid, make_event(rid, 2))
    path = events_path(rid)
    with path.open("a", encoding="utf-8") as fh:
        fh.write('{"seq": 3, "runId": "r_cut", "ty')  # 模拟写一半崩溃

    events = load_run_events(rid)
    assert [e.seq for e in events] == [1, 2]


def test_meta_snapshot_roundtrip(store):
    meta = RunMeta(id="r_meta", task="t", status="completed", createdAt=1.0, finishedAt=2.0)
    save_run_meta(meta)
    loaded = load_run_meta("r_meta")
    assert loaded.status == "completed" and loaded.finishedAt == 2.0
    assert [m.id for m in load_run_metas()] == ["r_meta"]


def test_legacy_json_layout_still_readable(store, tmp_data):
    """旧版本的 runs/{id}.json（meta+events 合并）必须仍能读取，保持历史回放兼容。"""
    legacy = tmp_data / "runs" / "r_legacy.json"
    legacy.write_text(
        json.dumps({
            "meta": {"id": "r_legacy", "task": "旧任务", "status": "completed", "createdAt": 1.0, "finishedAt": 2.0},
            "events": [
                {"seq": 1, "runId": "r_legacy", "type": "run.started", "ts": 1.0, "payload": {}},
                {"seq": 2, "runId": "r_legacy", "type": "result.final", "ts": 2.0, "payload": {"content": "x"}},
            ],
        }, ensure_ascii=False),
        "utf-8",
    )
    assert load_run_meta("r_legacy").task == "旧任务"
    assert [e.type for e in load_run_events("r_legacy")] == ["run.started", "result.final"]
    # 列表要能同时覆盖新旧两种布局，且不把 .meta.json 当旧文件重复计入
    assert [m.id for m in load_run_metas()] == ["r_legacy"]


def test_save_run_migrates_legacy_file(store, tmp_data):
    legacy = tmp_data / "runs" / "r_mig.json"
    legacy.write_text(
        json.dumps({"meta": {"id": "r_mig", "task": "t", "status": "running", "createdAt": 1.0},
                    "events": [{"seq": 1, "runId": "r_mig", "type": "run.started", "ts": 1.0, "payload": {}}]}),
        "utf-8",
    )
    meta = load_run_meta("r_mig")
    save_run(meta, load_run_events("r_mig"))
    assert events_path("r_mig").exists() and meta_path("r_mig").exists()
    assert not legacy.exists()
    assert len(load_run_events("r_mig")) == 1
    assert [m.id for m in load_run_metas()] == ["r_mig"]


def test_mixed_layout_deduped_by_id(store, tmp_data):
    """新旧布局同时存在同一 id 时，列表只出现一次，且以新 meta 为准。"""
    rid = "r_dup"
    legacy = tmp_data / "runs" / f"{rid}.json"
    legacy.write_text(
        json.dumps({"meta": {"id": rid, "task": "旧", "status": "running", "createdAt": 1.0}, "events": []}),
        "utf-8",
    )
    save_run_meta(RunMeta(id=rid, task="新", status="completed", createdAt=1.0))
    metas = [m for m in load_run_metas() if m.id == rid]
    assert len(metas) == 1
    assert metas[0].task == "新" and metas[0].status == "completed"


def test_delete_removes_both_new_files(store, tmp_data):
    rid = "r_del2"
    save_run_meta(RunMeta(id=rid, task="t", status="completed", createdAt=1.0))
    append_run_event(rid, make_event(rid, 1))
    assert events_path(rid).exists() and meta_path(rid).exists()
    assert delete_run_file(rid) is True
    assert not events_path(rid).exists() and not meta_path(rid).exists()
    assert delete_run_file(rid) is False


def test_reconcile_works_on_jsonl_layout(store):
    rid = "r_stale"
    save_run_meta(RunMeta(id=rid, task="t", status="running", createdAt=1.0))
    append_run_event(rid, make_event(rid, 1, "run.started"))
    append_run_event(rid, make_event(rid, 2, "phase.changed"))

    assert reconcile_stale_runs() == [rid]
    assert load_run_meta(rid).status == "interrupted"
    events = load_run_events(rid)
    assert [e.seq for e in events] == [1, 2, 3]
    assert events[-1].type == "run.failed"
