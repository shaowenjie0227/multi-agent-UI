"""工作包依赖图：依赖清洗与环路检测（分配前就拦下非法拆解，避免执行期才失败）。"""
from __future__ import annotations


def sanitize_dependencies(packages: list[dict]) -> tuple[list[dict], list[str]]:
    """就地清洗工作包依赖，返回 (packages, warnings)。

    - 丢弃自依赖与指向不存在工作包的依赖
    - 用 Kahn 拓扑排序找出处于环路中的节点，并断开这些节点之间的依赖边

    保证结果一定是可调度的 DAG，同时把被修正的内容作为告警交给上层展示。
    """
    warnings: list[str] = []
    keys = [str(p.get("key") or "") for p in packages]
    keyset = {k for k in keys if k}

    for p in packages:
        key = str(p.get("key") or "")
        kept: list[str] = []
        for d in p.get("dependsOn") or []:
            d = str(d)
            if not key or d == key:
                warnings.append(f"工作包「{key}」存在自依赖，已忽略")
                continue
            if d not in keyset:
                warnings.append(f"工作包「{key}」依赖了不存在的工作包「{d}」，已忽略")
                continue
            if d not in kept:
                kept.append(d)
        p["dependsOn"] = kept

    # Kahn：无法被剥离的节点即处于环中
    remaining = {k: set(str(d) for d in (next(p for p in packages if p["key"] == k).get("dependsOn") or [])) for k in keyset}
    removed = True
    while removed:
        removed = False
        for k in list(remaining):
            if not remaining[k]:
                del remaining[k]
                for other in remaining.values():
                    other.discard(k)
                removed = True

    if remaining:
        cycle_nodes = set(remaining)
        for p in packages:
            if p["key"] not in cycle_nodes:
                continue
            kept = [d for d in p.get("dependsOn") or [] if d not in cycle_nodes]
            if len(kept) != len(p.get("dependsOn") or []):
                warnings.append(f"工作包「{p['key']}」与其他工作包形成循环依赖，已断开环内侧依赖")
            p["dependsOn"] = kept

    return packages, warnings


def has_cycle(packages: list[dict]) -> bool:
    """检测工作包依赖是否存在环（供测试与上层快速判断）。"""
    keys = {str(p.get("key") or "") for p in packages}
    deps = {str(p.get("key") or ""): {str(d) for d in (p.get("dependsOn") or []) if str(d) in keys} for p in packages}
    resolved: set[str] = set()
    changed = True
    while changed:
        changed = False
        for k, ds in list(deps.items()):
            if k in resolved:
                continue
            if ds <= resolved:
                resolved.add(k)
                changed = True
    return len(resolved) != len(deps)
