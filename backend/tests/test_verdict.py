"""联调验收结论解析：重点是解析失败不能默认放行。"""
from __future__ import annotations

import json

from app.engine.orchestrator import _parse_verdict

KEYS = {"pkg-1", "pkg-2"}


def test_pass_verdict():
    raw = json.dumps({"passed": True, "report": "ok", "failed_items": []})
    v = _parse_verdict(raw, KEYS)
    assert v["passed"] is True and v["parsed"] is True
    assert v["failed_items"] == []


def test_failed_items_grouped_by_package():
    raw = json.dumps({
        "passed": False,
        "report": "r",
        "failed_items": [
            {"package": "pkg-1", "issue": "接口字段不一致"},
            {"package": "pkg-2", "issue": "缺少错误码"},
            {"package": "unknown", "issue": "全局问题"},
            "纯字符串问题",
        ],
    })
    v = _parse_verdict(raw, KEYS)
    assert v["passed"] is False
    assert v["failed_by_pkg"]["pkg-1"] == ["接口字段不一致"]
    assert v["failed_by_pkg"]["pkg-2"] == ["缺少错误码"]
    assert v["failed_by_pkg"]["_global"] == ["全局问题", "纯字符串问题"]
    assert len(v["failed_items"]) == 4


def test_fenced_json_accepted():
    raw = '```json\n{"passed": true, "report": "fine"}\n```'
    v = _parse_verdict(raw, KEYS)
    assert v["passed"] is True and v["parsed"] is True


def test_unparseable_does_not_pass():
    """核心回归：模型输出崩掉时不能自动通过验收门。"""
    v = _parse_verdict("本次联调整体看起来还行，建议通过。", KEYS)
    assert v["passed"] is False
    assert v["parsed"] is False
    assert v["failed_by_pkg"] == {}
    assert v["failed_items"]


def test_json_without_passed_field_does_not_pass():
    v = _parse_verdict(json.dumps({"report": "ok"}), KEYS)
    assert v["passed"] is False and v["parsed"] is False


def test_report_falls_back_to_raw_when_missing():
    v = _parse_verdict(json.dumps({"passed": False, "failed_items": ["x"]}), KEYS)
    assert v["report"]
