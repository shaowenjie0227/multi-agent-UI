"""JSON 文件存储：providers.json / agents.json / runs/*.json。首次启动写入种子数据。"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

from .schemas import Agent, AppSettings, Provider, ProviderModel, RunEvent, RunMeta

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RUNS_DIR = DATA_DIR / "runs"


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def _seed_providers() -> tuple[list[Provider], list[ProviderModel]]:
    raw = [
        ("zhipu", "智谱 AI", "https://open.bigmodel.cn/api/paas/v4", ["glm-4.7", "glm-4.6"]),
        ("xai", "xAI", "https://api.x.ai/v1", ["grok-4.7", "grok-4"]),
        ("deepseek", "DeepSeek", "https://api.deepseek.com/v1", ["deepseek-chat", "deepseek-reasoner"]),
    ]
    providers: list[Provider] = []
    models: list[ProviderModel] = []
    for pid, name, base, model_names in raw:
        providers.append(Provider(id=pid, name=name, baseUrl=base, apiKey=""))
        for m in model_names:
            models.append(ProviderModel(id=new_id("m_"), providerId=pid, name=m))
    return providers, models


SEED_AGENTS: list[dict] = [
    {
        "name": "编排者",
        "role": "orchestrator",
        "persona": (
            "你是项目编排者，负责任务拆解与最终交付汇总。\n"
            "当被要求产出计划时，严格输出 JSON（不要任何多余文本）：\n"
            '{"tasks": [{"id": "dev-1", "role": "developer", "title": "开发实现", "instruction": "具体开发指令", "dependsOn": []}, '
            '{"id": "test-1", "role": "tester", "title": "需求测试", "instruction": "对照验收标准测试", "dependsOn": ["dev-1"]}]}\n'
            "计划必须包含一个开发任务与一个依赖它的测试任务。\n"
            "当被要求汇总时，输出最终交付文档（markdown），分节：一、最终需求方案；二、实现交付；三、测试结论；四、遗留风险。"
        ),
    },
    {
        "name": "需求分析师",
        "role": "analyst",
        "persona": (
            "你是资深需求分析师。根据用户需求与对话历史产出/修订需求方案。\n"
            "严格输出 JSON（不要任何多余文本）：\n"
            '{"proposal": "需求方案 markdown 全文", "questions": ["仍需用户澄清的边界问题"], "ready_for_approval": false}\n'
            "规则：\n"
            "1. 首次给出初版方案（含背景、目标、范围、功能需求），并提出 2~4 个关键边界问题（平台、规模、数据、优先级等）。\n"
            "2. 用户补充或反馈后，修订方案并保留仍未澄清的问题。\n"
            "3. 只有当需求信息足够完整、可形成含验收标准的完整方案时，才置 ready_for_approval=true，"
            "此时 questions 留空，proposal 为完整方案（背景、目标、范围、功能需求、非功能需求、验收标准）。"
        ),
    },
    {
        "name": "开发工程师",
        "role": "developer",
        "persona": (
            "你是资深开发工程师。依据需求方案与上下文产出技术实现（markdown）："
            "技术选型、架构设计、模块划分、核心实现（关键代码块）、部署与风险说明。\n"
            "若输入包含测试失败项，必须逐项修复，并在输出开头列出『本轮修复点』。"
        ),
    },
    {
        "name": "测试工程师",
        "role": "tester",
        "persona": (
            "你是验收测试工程师。严格对照需求方案中的功能需求与验收标准审查开发产出。\n"
            "严格输出 JSON（不要任何多余文本）：\n"
            '{"passed": false, "report": "测试报告 markdown", "failed_items": ["不通过项"]}\n'
            "报告包含：测试用例及结果、与验收标准逐条对照结论。不得放水：所有验收标准均有对应合理实现才可 passed=true。"
        ),
    },
]


class Store:
    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        self.providers: list[Provider] = []
        self.models: list[ProviderModel] = []
        self.agents: list[Agent] = []
        self.settings: AppSettings = AppSettings()
        self._load_or_seed()

    # ---------- 全局设置 ----------

    def _settings_file(self) -> Path:
        return DATA_DIR / "settings.json"

    def _load_settings(self) -> None:
        f = self._settings_file()
        if f.exists():
            try:
                data = json.loads(f.read_text("utf-8"))
                self.settings = AppSettings(**data)
            except Exception:
                self.settings = AppSettings()

    def update_settings(self, proxy: Optional[dict] = None, clash: Optional[dict] = None) -> AppSettings:
        if proxy is not None:
            self.settings = self.settings.model_copy(update={"proxy": self.settings.proxy.model_copy(update=proxy)})
        if clash is not None:
            self.settings = self.settings.model_copy(update={"clash": self.settings.clash.model_copy(update=clash)})
        self._settings_file().write_text(json.dumps(self.settings.model_dump(), ensure_ascii=False, indent=2), "utf-8")
        return self.settings

    # ---------- 基础 IO ----------

    def _load_or_seed(self) -> None:
        pf = DATA_DIR / "providers.json"
        af = DATA_DIR / "agents.json"
        self._load_settings()
        if pf.exists():
            data = json.loads(pf.read_text("utf-8"))
            self.providers = [Provider(**p) for p in data.get("providers", [])]
            self.models = [ProviderModel(**m) for m in data.get("models", [])]
        else:
            self.providers, self.models = _seed_providers()
            self._save_providers()
        if af.exists():
            data = json.loads(af.read_text("utf-8"))
            self.agents = [Agent(**a) for a in data.get("agents", [])]
        else:
            self.agents = [Agent(id=new_id("a_"), **a) for a in SEED_AGENTS]
            self._save_agents()

    def _save_providers(self) -> None:
        (DATA_DIR / "providers.json").write_text(
            json.dumps(
                {"providers": [p.model_dump() for p in self.providers], "models": [m.model_dump() for m in self.models]},
                ensure_ascii=False,
                indent=2,
            ),
            "utf-8",
        )

    def _save_agents(self) -> None:
        (DATA_DIR / "agents.json").write_text(
            json.dumps({"agents": [a.model_dump() for a in self.agents]}, ensure_ascii=False, indent=2),
            "utf-8",
        )

    # ---------- 供应商 / 模型 ----------

    def add_provider(self, p: Provider) -> Provider:
        self.providers.append(p)
        self._save_providers()
        return p

    def update_provider(self, pid: str, patch: dict) -> Optional[Provider]:
        p = self.find_provider(pid)
        if not p:
            return None
        for k, v in patch.items():
            if v is not None:
                setattr(p, k, v)
        self._save_providers()
        return p

    def delete_provider(self, pid: str) -> bool:
        before = len(self.providers)
        self.providers = [p for p in self.providers if p.id != pid]
        self.models = [m for m in self.models if m.providerId != pid]
        if len(self.providers) != before:
            self._save_providers()
            return True
        return False

    def find_provider(self, pid: str) -> Optional[Provider]:
        return next((p for p in self.providers if p.id == pid), None)

    def add_model(self, m: ProviderModel) -> ProviderModel:
        self.models.append(m)
        self._save_providers()
        return m

    def delete_model(self, mid: str) -> bool:
        before = len(self.models)
        self.models = [m for m in self.models if m.id != mid]
        if len(self.models) != before:
            self._save_providers()
            return True
        return False

    def find_model(self, mid: str) -> Optional[ProviderModel]:
        return next((m for m in self.models if m.id == mid), None)

    def models_of(self, pid: str) -> list[ProviderModel]:
        return [m for m in self.models if m.providerId == pid]

    # ---------- Agent ----------

    def add_agent(self, a: Agent) -> Agent:
        self.agents.append(a)
        self._save_agents()
        return a

    def update_agent(self, aid: str, patch: dict) -> Optional[Agent]:
        a = self.find_agent_by_id(aid)
        if not a:
            return None
        for k, v in patch.items():
            if v is not None:
                setattr(a, k, v)
        self._save_agents()
        return a

    def delete_agent(self, aid: str) -> bool:
        before = len(self.agents)
        self.agents = [a for a in self.agents if a.id != aid]
        if len(self.agents) != before:
            self._save_agents()
            return True
        return False

    def find_agent_by_id(self, aid: str) -> Optional[Agent]:
        return next((a for a in self.agents if a.id == aid), None)

    def find_agent_by_role(self, role: str) -> Optional[Agent]:
        return next((a for a in self.agents if a.role == role and a.enabled), None)

    def resolve_binding(self, binding: str) -> tuple[Provider, ProviderModel]:
        """binding 格式 "{providerId}:{modelId}"，解析并校验可用性。"""
        if binding == "mock" or ":" not in binding:
            raise ValueError("该 Agent 绑定的是 Mock 模拟，不是真实模型")
        pid, mid = binding.split(":", 1)
        provider = self.find_provider(pid)
        if not provider:
            raise ValueError(f"供应商 {pid} 不存在，请检查 Agent 绑定")
        if not provider.enabled:
            raise ValueError(f"供应商「{provider.name}」未启用")
        model = self.find_model(mid)
        if not model or model.providerId != pid:
            raise ValueError(f"模型 {mid} 不存在，请检查 Agent 绑定")
        if not provider.apiKey:
            raise ValueError(f"供应商「{provider.name}」未配置 API Key")
        return provider, model


# ---------------- Run 持久化 ----------------


def save_run(meta: RunMeta, events: list[RunEvent]) -> None:
    data = {
        "meta": meta.model_dump(),
        "events": [e.model_dump() for e in events],
    }
    (RUNS_DIR / f"{meta.id}.json").write_text(json.dumps(data, ensure_ascii=False), "utf-8")


def load_run_metas() -> list[RunMeta]:
    metas: list[RunMeta] = []
    if not RUNS_DIR.exists():
        return metas
    for f in sorted(RUNS_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text("utf-8"))
            metas.append(RunMeta(**data["meta"]))
        except Exception:
            continue
    metas.sort(key=lambda m: m.createdAt, reverse=True)
    return metas


def load_run_events(run_id: str) -> Optional[list[RunEvent]]:
    f = RUNS_DIR / f"{run_id}.json"
    if not f.exists():
        return None
    data = json.loads(f.read_text("utf-8"))
    return [RunEvent(**e) for e in data["events"]]


def now() -> float:
    return time.time()
