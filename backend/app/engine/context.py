"""提示词上下文裁剪：多轮对话与多工作包拼接容易超上下文，按预算保留首尾。"""
from __future__ import annotations

PROPOSAL_LIMIT = 16_000
PACKAGE_LIMIT = 8_000
DEP_LIMIT = 6_000
REPORT_LIMIT = 10_000
HISTORY_TURN_LIMIT = 6_000
HISTORY_MAX_TURNS = 16


def clip(text: str, limit: int, label: str = "内容") -> str:
    """超长文本保留前 65% + 后 25%，中间标注省略量，避免关键结论（结论通常在尾部）被截掉。"""
    text = text or ""
    if len(text) <= limit:
        return text
    head = int(limit * 0.65)
    tail = int(limit * 0.25)
    omitted = len(text) - head - tail
    return f"{text[:head]}\n\n…（{label}过长，已省略中间 {omitted} 字）…\n\n{text[-tail:]}"


def clip_history(history: list[dict], each_limit: int = HISTORY_TURN_LIMIT, max_turns: int = HISTORY_MAX_TURNS) -> list[dict]:
    """保留最近若干轮对话，并对单条消息裁剪；首条用户需求始终保留。"""
    if not history:
        return history
    first = history[:1]
    rest = history[1:]
    if len(rest) > max_turns:
        rest = rest[-max_turns:]
    out = first + [
        {"role": m.get("role", "user"), "content": clip(str(m.get("content") or ""), each_limit, "对话内容")}
        for m in rest
    ]
    return out
