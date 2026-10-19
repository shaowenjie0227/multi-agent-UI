"""模型推荐引擎：知识库 + LLM 匹配，LLM 不可用时降级为规则评分。"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

from .providers.base import parse_json_tolerant
from .providers.openai_compat import real_chat
from .store import DATA_DIR

KB_PATH = DATA_DIR / "model_knowledge.json"

# 维度中文标签（规则路径的解释文案与 LLM 提示词共用）
DIM_LABELS: dict[str, str] = {
    "coding": "编码实现",
    "debugging": "排查调试",
    "refactoring": "重构",
    "agent_tool_use": "Agent/工具调用",
    "math_reasoning": "数学/逻辑推理",
    "long_context": "长上下文",
    "multimodal": "多模态",
    "writing_creative": "创意写作",
    "writing_business": "商务写作",
    "translation": "翻译",
    "summarization": "总结提炼",
    "qa_knowledge": "知识问答",
    "data_analysis": "数据分析",
    "instruction_following": "指令遵循",
}

# 规则分类关键词（小写匹配，中英混合）
_KEYWORDS: dict[str, list[str]] = {
    "coding": ["代码", "编码", "写个", "写一个", "开发", "实现", "函数", "接口", "脚本", "程序", "组件", "页面", "前端", "后端", "部署", "正则", "python", "javascript", "typescript", "java", "react", "vue", "css", "html", "docker", "api"],
    "debugging": ["报错", "bug", "错误", "修复", "排查", "调试", "不工作", "跑不起来", "异常", "崩溃", "error", "fix", "crash", "exception", "traceback", "内存泄漏", "死循环"],
    "refactoring": ["重构", "重写", "代码质量", "技术债", "整理代码", "refactor", "性能优化", "优化代码"],
    "agent_tool_use": ["agent", "智能体", "工具调用", "多步", "自主", "function calling", "function-calling", "mcp", "自动化工作流", "编排", "浏览器操作"],
    "math_reasoning": ["数学", "推理", "证明", "逻辑", "奥数", "概率", "方程", "演算", "算法题", "计算题", "悖论", "博弈"],
    "long_context": ["长文", "长文档", "全文", "整本", "几万字", "超长", "整个仓库", "整个代码库", "整个项目", "代码库", "全仓库", "全量", "上百页", "monorepo", "万行"],
    "multimodal": ["图片", "图像", "截图", "视频", "语音", "看图", "ocr", "识别图", "拍照"],
    "writing_creative": ["小说", "故事", "文案", "创意", "剧本", "诗", "歌词", "起名", "slogan", "文风", "段子"],
    "writing_business": ["报告", "方案", "邮件", "简历", "周报", "公文", "标书", "商业计划", "产品说明", "申请书", "ppt"],
    "translation": ["翻译", "译成", "英译", "中译", "translate", "本地化", "翻译成"],
    "summarization": ["总结", "摘要", "提炼", "归纳", "纪要", "summarize", "缩写成"],
    "qa_knowledge": ["是什么", "为什么", "解释", "介绍", "区别", "咨询", "问答", "怎么理解", "科普"],
    "data_analysis": ["数据分析", "统计", "表格", "excel", "报表", "趋势", "可视化", "sql", "csv", "图表", "数据集"],
    "instruction_following": ["严格按照", "格式要求", "按格式", "输出为 json", "输出成 json", "表格形式", "必须包含", "步骤执行"],
}

# 维度权重
_DIM_WEIGHT: dict[str, float] = {
    "coding": 1.2,
    "debugging": 1.2,
    "refactoring": 1.1,
    "agent_tool_use": 1.2,
    "math_reasoning": 1.2,
    "long_context": 1.3,
    "multimodal": 1.3,
    "writing_creative": 1.0,
    "writing_business": 1.0,
    "translation": 1.0,
    "summarization": 1.0,
    "qa_knowledge": 0.9,
    "data_analysis": 1.1,
    "instruction_following": 0.8,
}

# 硬推理维度（命中倾向给高档位）
_HEAVY_DIMS = {"math_reasoning", "agent_tool_use", "debugging", "refactoring", "long_context", "data_analysis"}
# 轻任务维度（只命中这些时倾向关思考）
_LIGHT_DIMS = {"summarization", "translation", "qa_knowledge", "writing_creative", "writing_business"}

_LEVEL_ORDER = ["off", "low", "medium", "high"]


def load_knowledge() -> list[dict]:
    """读取知识库，每次现读保证用户编辑后尽快生效。"""
    try:
        data = json.loads(KB_PATH.read_text("utf-8"))
        models = [m for m in data.get("models", []) if isinstance(m, dict) and m.get("id")]
        return models
    except Exception:
        return []


# ---------------- 规则路径 ----------------


def classify_rules(task: str) -> list[str]:
    text = task.lower()
    return [dim for dim, words in _KEYWORDS.items() if any(w in text for w in words)]


_COST_RANK = {"low": 2, "medium": 1, "high": 0}
_SPEED_RANK = {"fast": 2, "medium": 1, "slow": 0}


def score_rules(models: list[dict], tags: list[str], prefer: dict, ws_names: set[str] | None = None) -> list[tuple[dict, float]]:
    scored: list[tuple[dict, float]] = []
    for m in models:
        strengths = set(m.get("strengths") or [])
        weaknesses = set(m.get("weaknesses") or [])
        s = 0.02 * len(strengths)  # 综合能力基础分，保证无标签时排序仍然合理
        for dim in tags:
            w = _DIM_WEIGHT.get(dim, 1.0)
            if dim in strengths:
                s += w
            elif dim in weaknesses:
                s -= 0.9 * w
        cost, speed = m.get("costTier", "medium"), m.get("speedTier", "medium")
        if prefer.get("cost") == "low":
            s += 0.8 if cost == "low" else (-0.6 if cost == "high" else 0.0)
        elif prefer.get("cost") == "quality":
            s += 0.5 if cost == "high" else (-0.2 if cost == "low" else 0.0)
        if prefer.get("speed"):
            s += 0.8 if speed == "fast" else (-0.6 if speed == "slow" else 0.0)
        if "long_context" in tags and (m.get("contextWindow") or 0) >= 400_000:
            s += 0.5
        if ws_names and _norm_name(str(m.get("id", ""))) in ws_names:
            s += 0.15  # 工作区已有的模型加一点分，便于直接绑定
        scored.append((m, s))
    # 分数并列时，便宜且快的优先（避免旗舰靠基础分内卷胜出）
    scored.sort(
        key=lambda t: (
            t[1],
            _COST_RANK[t[0].get("costTier", "medium")] + _SPEED_RANK[t[0].get("speedTier", "medium")],
        ),
        reverse=True,
    )
    return scored


def _closest_level(levels: list[str], target: str) -> str:
    avail = [lv for lv in _LEVEL_ORDER if lv in levels]
    if not avail:
        return levels[0]
    return min(avail, key=lambda lv: abs(_LEVEL_ORDER.index(lv) - _LEVEL_ORDER.index(target)))


def pick_effort(model: dict, tags: list[str], prefer: dict) -> str:
    """规则路径的推理档位：硬推理给高档，轻任务/求快给低档，其余取中。"""
    levels = [str(x) for x in (model.get("reasoningLevels") or ["off"])]
    if "always" in levels:
        return "always"
    if set(tags) & _HEAVY_DIMS:
        # 硬推理倾向高档；但明确要求速度时折中取中档
        target = "medium" if prefer.get("speed") else "high"
    elif (tags and set(tags) <= _LIGHT_DIMS) or prefer.get("speed"):
        target = "off"
    else:
        target = "medium"
    return _closest_level(levels, target)


def _clamp_effort(model: dict, val: Any) -> str:
    """把 LLM 给的档位钳制到该模型支持的档位内。"""
    levels = [str(x) for x in (model.get("reasoningLevels") or ["off"])]
    v = str(val or "").strip().lower()
    if v in levels:
        return v
    return pick_effort(model, [], {"cost": "balanced", "speed": False})


def _norm_name(s: str) -> str:
    return (s or "").strip().lower().replace(" ", "")


def match_workspace(store, model: dict) -> Optional[tuple[str, str]]:
    """知识库条目 → 工作区 (providerId, providerModelId)；按模型名归一化匹配。"""
    names = {_norm_name(str(model.get("id", "")))} | {_norm_name(x) for x in (model.get("apiNames") or [])}
    names.discard("")
    for m in store.models:
        if _norm_name(m.name) in names:
            p = store.find_provider(m.providerId)
            if p and p.enabled:
                return p.id, m.id
    return None


def _rec(store, m: dict, effort: str, rationale: str, confidence: float) -> dict:
    ws = match_workspace(store, m)
    return {
        "modelId": m["id"],
        "name": m.get("name") or m["id"],
        "vendor": m.get("vendor", ""),
        "reasoningEffort": effort,
        "rationale": rationale,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "inWorkspace": bool(ws),
        "providerId": ws[0] if ws else None,
        "providerModelId": ws[1] if ws else None,
    }


def _rule_primary(store, scored: list[tuple[dict, float]], tags: list[str], prefer: dict) -> dict:
    top_m, top_s = scored[0]
    second_s = scored[1][1] if len(scored) > 1 else top_s
    strengths = set(top_m.get("strengths") or [])
    if tags:
        labels = "、".join(DIM_LABELS.get(d, d) for d in tags)
        cover = "、".join(DIM_LABELS.get(d, d) for d in tags if d in strengths) or "与该模型专长部分匹配"
        rationale = f"识别到任务特征：{labels}；{cover}正是其强项。{top_m.get('bestFor', '')}"
        conf = 0.5 + min(0.35, max(0.0, top_s - second_s) * 0.5)
    else:
        rationale = f"任务特征不明显，按综合能力与你的偏好给出均衡推荐。{top_m.get('bestFor', '')}"
        conf = 0.4
    return _rec(store, top_m, pick_effort(top_m, tags, prefer), rationale, conf)


# ---------------- LLM 路径 ----------------


def _pick_meta_model(store) -> Optional[tuple[Any, Any]]:
    """用于推荐的元模型：第一个启用且配了 Key 的供应商的第一个模型。"""
    for p in store.providers:
        if p.enabled and p.apiKey:
            ms = store.models_of(p.id)
            if ms:
                return p, ms[0]
    return None


async def recommend_llm(store, task: str, prefer: dict, models: list[dict]) -> Optional[dict]:
    picked = _pick_meta_model(store)
    if not picked:
        return None
    provider, model = picked
    digest = [
        {
            "id": m.get("id"),
            "vendor": m.get("vendor"),
            "strengths": m.get("strengths"),
            "weaknesses": m.get("weaknesses"),
            "contextWindow": m.get("contextWindow"),
            "reasoningLevels": m.get("reasoningLevels"),
            "speedTier": m.get("speedTier"),
            "costTier": m.get("costTier"),
            "bestFor": m.get("bestFor"),
        }
        for m in models
    ]
    system = (
        "你是模型选型专家。根据用户任务描述与候选模型知识库，推荐最合适的模型与推理档位。\n\n"
        f"候选模型知识库（JSON）：\n{json.dumps(digest, ensure_ascii=False)}\n\n"
        "任务维度词表（tags 只能取这些值）：\n"
        + "、".join(f"{k}（{v}）" for k, v in DIM_LABELS.items())
        + "\n\n"
        "推理档位取值：off / low / medium / high / always（always 表示该模型固定深度思考、不可调）。"
        "所选档位必须在该模型 reasoningLevels 列表内。\n\n"
        "严格输出 JSON（不要任何多余文本）：\n"
        '{"tags": ["任务维度..."], "primary": {"modelId": "知识库中的 id", "reasoningEffort": "档位", '
        '"confidence": 0.0到1.0, "rationale": "中文推荐理由，1~2句，结合任务特点说明为什么选它"}, '
        '"alternatives": [{"modelId": "...", "reasoningEffort": "档位", "why": "中文，一句话说清与首选的差异点"}]}\n\n'
        "要求：modelId 必须来自知识库；alternatives 给 1~3 个与首选有差异化的备选；"
        "兼顾用户的成本/速度偏好；理由具体不空泛。"
    )
    user = (
        f"任务描述：{task}\n"
        f"偏好：成本={'成本优先' if prefer.get('cost') == 'low' else '质量优先' if prefer.get('cost') == 'quality' else '均衡'}，"
        f"追求响应速度={'是' if prefer.get('speed') else '否'}"
    )
    raw = await real_chat(
        provider,
        model,
        system,
        [{"role": "user", "content": user}],
        proxy=store.settings.proxy,
    )
    return parse_json_tolerant(raw)


# ---------------- 主流程 ----------------


async def recommend(store, task: str, prefer: dict) -> dict:
    models = load_knowledge()
    if not models:
        raise ValueError("模型知识库为空，请检查 backend/data/model_knowledge.json")

    tags = classify_rules(task)
    ws_names = {_norm_name(m.name) for m in store.models}
    scored = score_rules(models, tags, prefer, ws_names=ws_names)

    primary: Optional[dict] = None
    alts: list[dict] = []
    engine = "rules"
    tags_out = list(tags)

    try:
        llm = await asyncio.wait_for(recommend_llm(store, task, prefer, models), timeout=45)
    except Exception:
        llm = None

    if llm:
        by_id = {m["id"]: m for m in models}
        p = llm.get("primary") if isinstance(llm.get("primary"), dict) else {}
        pm = by_id.get(str(p.get("modelId", "")).strip())
        if pm:
            engine = "llm"
            for t in llm.get("tags") or []:
                if isinstance(t, str) and t in _DIM_WEIGHT and t not in tags_out:
                    tags_out.append(t)
            try:
                conf = float(p.get("confidence", 0.75))
            except (TypeError, ValueError):
                conf = 0.75
            rationale = str(p.get("rationale") or "").strip()
            if not rationale:
                rationale = f"综合任务特征与模型专长推荐。{pm.get('bestFor', '')}"
            primary = _rec(store, pm, _clamp_effort(pm, p.get("reasoningEffort")), rationale, conf)
            seen = {pm["id"]}
            for a in llm.get("alternatives") or []:
                if not isinstance(a, dict):
                    continue
                am = by_id.get(str(a.get("modelId", "")).strip())
                if not am or am["id"] in seen:
                    continue
                seen.add(am["id"])
                why = str(a.get("why") or "").strip() or am.get("bestFor", "")
                alts.append(_rec(store, am, _clamp_effort(am, a.get("reasoningEffort")), why, max(0.3, conf - 0.15)))

    if primary is None:
        primary = _rule_primary(store, scored, tags_out, prefer)

    # 备选不足时用规则排序补齐
    if len(alts) < 2:
        seen = {primary["modelId"]} | {a["modelId"] for a in alts}
        for m, _s in scored:
            if m["id"] in seen:
                continue
            alts.append(_rec(store, m, pick_effort(m, tags_out, prefer), m.get("bestFor", ""), 0.5))
            if len(alts) >= 3:
                break

    return {"engine": engine, "tags": tags_out, "primary": primary, "alternatives": alts}
