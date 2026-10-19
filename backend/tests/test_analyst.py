"""工作包归一化、分配校验、上下文裁剪。"""
from __future__ import annotations

import pytest

from app.engine.analyst_loop import _normalize_packages, _validate_assignments
from app.engine.context import clip, clip_history
from app.engine.errors import EngineError


def test_normalize_defaults_and_types():
    out = _normalize_packages([
        {"key": "pkg-1", "agentName": "前端", "tasks": ["a"], "dependsOn": ["pkg-2"]},
        {"name": "后端"},  # 缺 key/agentName，走默认值
        "not-a-dict",
    ])
    assert len(out) == 2
    assert out[0]["key"] == "pkg-1" and out[0]["dependsOn"] == ["pkg-2"]
    assert out[1]["key"] == "pkg-2" and out[1]["agentName"] == "后端"


def test_normalize_dedupes_keys():
    out = _normalize_packages([{"key": "pkg-1"}, {"key": "pkg-1"}, {"key": "pkg-1"}])
    assert len({p["key"] for p in out}) == 3


def test_normalize_empty():
    assert _normalize_packages(None) == []


OPTIONS = [
    {"id": "a_dev", "name": "开发", "role": "developer", "binding": "mock"},
    {"id": "a_ui", "name": "前端", "role": "custom", "binding": "xai:m1"},
]
PACKAGES = [{"key": "pkg-1", "agentName": "前端"}, {"key": "pkg-2", "agentName": "开发"}]


def test_validate_assignments_follows_agent_binding():
    out = _validate_assignments(
        [{"packageKey": "pkg-1", "agentId": "a_ui"}, {"packageKey": "pkg-2", "agentId": "a_dev"}],
        PACKAGES, OPTIONS,
    )
    assert [a["binding"] for a in out] == ["xai:m1", "mock"]
    assert [a["agentName"] for a in out] == ["前端", "开发"]


def test_validate_assignments_model_override():
    out = _validate_assignments(
        [{"packageKey": "pkg-1", "agentId": "a_ui", "model": "zhipu:m9"},
         {"packageKey": "pkg-2", "agentId": "a_dev", "model": "follow"}],
        PACKAGES, OPTIONS,
    )
    assert out[0]["binding"] == "zhipu:m9"
    assert out[1]["binding"] == "mock"


def test_validate_assignments_missing_package():
    with pytest.raises(EngineError) as exc:
        _validate_assignments([{"packageKey": "pkg-1", "agentId": "a_ui"}], PACKAGES, OPTIONS)
    assert "未分配" in str(exc.value)


def test_validate_assignments_unknown_agent():
    with pytest.raises(EngineError) as exc:
        _validate_assignments(
            [{"packageKey": "pkg-1", "agentId": "ghost"}, {"packageKey": "pkg-2", "agentId": "a_dev"}],
            PACKAGES, OPTIONS,
        )
    assert "不存在" in str(exc.value)


def test_clip_short_text_unchanged():
    assert clip("hello", 100) == "hello"


def test_clip_keeps_head_and_tail():
    text = "HEAD" + "x" * 500 + "TAIL"
    out = clip(text, 100)
    assert len(out) < len(text)
    assert out.startswith("HEAD")
    assert out.endswith("TAIL")
    assert "已省略" in out


def test_clip_history_bounds_turns_and_first_message():
    history = [{"role": "user", "content": "原始需求"}] + [
        {"role": "user", "content": "y" * 20_000} for _ in range(40)
    ]
    out = clip_history(history)
    assert out[0]["content"] == "原始需求"
    assert len(out) <= 1 + 16
    assert all(len(m["content"]) < 20_000 for m in out[1:])
