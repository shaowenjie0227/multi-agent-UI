"""依赖图清洗与环检测。"""
from __future__ import annotations

from app.engine.graph import has_cycle, sanitize_dependencies


def pkg(key: str, deps: list[str]) -> dict:
    return {"key": key, "agentName": key.upper(), "responsibility": "", "tasks": [], "integration": "", "dependsOn": list(deps)}


def test_valid_dag_untouched():
    packages = [pkg("pkg-1", []), pkg("pkg-2", ["pkg-1"]), pkg("pkg-3", ["pkg-1", "pkg-2"])]
    out, warnings = sanitize_dependencies(packages)
    assert warnings == []
    assert [p["dependsOn"] for p in out] == [[], ["pkg-1"], ["pkg-1", "pkg-2"]]
    assert not has_cycle(out)


def test_missing_and_self_dependencies_dropped():
    out, warnings = sanitize_dependencies([pkg("pkg-1", ["pkg-1", "ghost"]), pkg("pkg-2", ["pkg-1"])])
    assert out[0]["dependsOn"] == []
    assert out[1]["dependsOn"] == ["pkg-1"]
    assert any("自依赖" in w for w in warnings)
    assert any("不存在的工作包" in w for w in warnings)


def test_two_node_cycle_broken():
    out, warnings = sanitize_dependencies([pkg("pkg-1", ["pkg-2"]), pkg("pkg-2", ["pkg-1"])])
    assert not has_cycle(out)
    assert all(p["dependsOn"] == [] for p in out)
    joined = "".join(warnings)
    assert "循环依赖" in joined


def test_chain_into_cycle_keeps_acyclic_part():
    out, warnings = sanitize_dependencies([
        pkg("pkg-1", []),
        pkg("pkg-2", ["pkg-1"]),
        pkg("pkg-3", ["pkg-2", "pkg-4"]),
        pkg("pkg-4", ["pkg-3"]),
    ])
    assert not has_cycle(out)
    deps = {p["key"]: p["dependsOn"] for p in out}
    # 环被断开，但 pkg-1 → pkg-2 的正常依赖保留
    assert deps["pkg-2"] == ["pkg-1"]
    assert warnings


def test_duplicate_dependencies_deduped():
    out, _ = sanitize_dependencies([pkg("pkg-1", []), pkg("pkg-2", ["pkg-1", "pkg-1"])])
    assert out[1]["dependsOn"] == ["pkg-1"]
