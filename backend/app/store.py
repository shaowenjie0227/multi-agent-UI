"""JSON 文件存储：providers.json / agents.json / runs/*.json。首次启动写入种子数据。"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Optional

from .schemas import Agent, AppSettings, Provider, ProviderModel, RunEvent, RunMeta

DATA_DIR = Path(os.environ.get("MAS_DATA_DIR") or (Path(__file__).resolve().parent.parent / "data"))
RUNS_DIR = DATA_DIR / "runs"
SEED_DIR = Path(__file__).resolve().parent / "seed"
KB_NAME = "model_knowledge.json"


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def _atomic_write(path: Path, text: str) -> None:
    """先写临时文件再原子替换，避免进程中断留下半截 JSON。"""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, "utf-8")
    os.replace(tmp, path)


def _seed_knowledge() -> None:
    """模型知识库首次启动时从包内种子复制到 data/，之后以 data/ 下用户可编辑版本为准。"""
    target = DATA_DIR / KB_NAME
    if target.exists():
        return
    source = SEED_DIR / KB_NAME
    if source.exists():
        _atomic_write(target, source.read_text("utf-8"))


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

    def update_settings(
        self,
        proxy: Optional[dict] = None,
        clash: Optional[dict] = None,
        workspace: Optional[dict] = None,
        sandbox: Optional[dict] = None,
        auth: Optional[dict] = None,
    ) -> AppSettings:
        if proxy is not None:
            self.settings = self.settings.model_copy(update={"proxy": self.settings.proxy.model_copy(update=proxy)})
        if clash is not None:
            self.settings = self.settings.model_copy(update={"clash": self.settings.clash.model_copy(update=clash)})
        if workspace is not None:
            self.settings = self.settings.model_copy(
                update={"workspace": self.settings.workspace.model_copy(update=workspace)}
            )
        if sandbox is not None:
            self.settings = self.settings.model_copy(
                update={"sandbox": self.settings.sandbox.model_copy(update=sandbox)}
            )
        if auth is not None:
            self.settings = self.settings.model_copy(update={"auth": self.settings.auth.model_copy(update=auth)})
        self._settings_file().write_text(json.dumps(self.settings.model_dump(), ensure_ascii=False, indent=2), "utf-8")
        return self.settings

    # ---------- 基础 IO ----------

    def _load_or_seed(self) -> None:
        pf = DATA_DIR / "providers.json"
        af = DATA_DIR / "agents.json"
        self._load_settings()
        _seed_knowledge()
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
        _atomic_write(
            DATA_DIR / "providers.json",
            json.dumps(
                {"providers": [p.model_dump() for p in self.providers], "models": [m.model_dump() for m in self.models]},
                ensure_ascii=False,
                indent=2,
            ),
        )

    def _save_agents(self) -> None:
        _atomic_write(
            DATA_DIR / "agents.json",
            json.dumps({"agents": [a.model_dump() for a in self.agents]}, ensure_ascii=False, indent=2),
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
            if v is not None and k in Provider.model_fields:
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
#
# 存储布局（每次运行两个文件）：
#   runs/{id}.events.jsonl —— 事件流，逐行追加（O(1)/事件，崩溃最多丢最后一行）
#   runs/{id}.meta.json    —— 元数据快照，创建时写一次、终态再写一次（少量周期性快照兜底）
#
# 兼容旧布局 runs/{id}.json（meta+events 合并的全量文件）：仍可读取，遇到写入时自动迁移成新布局。

EVENTS_SUFFIX = ".events.jsonl"
META_SUFFIX = ".meta.json"
META_SNAPSHOT_EVERY = 50  # 每 N 个事件补写一次 meta 快照，防进程被杀时状态过旧


def events_path(run_id: str) -> Path:
    return RUNS_DIR / f"{run_id}{EVENTS_SUFFIX}"


def meta_path(run_id: str) -> Path:
    return RUNS_DIR / f"{run_id}{META_SUFFIX}"


def legacy_path(run_id: str) -> Path:
    return RUNS_DIR / f"{run_id}.json"


def append_run_event(run_id: str, event: RunEvent) -> None:
    """追加一行事件。只做一次 append，不再全量重写整个运行。"""
    path = events_path(run_id)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event.model_dump(), ensure_ascii=False))
        fh.write("\n")


def save_run_meta(meta: RunMeta) -> None:
    _atomic_write(meta_path(meta.id), json.dumps(meta.model_dump(), ensure_ascii=False))


def save_run(meta: RunMeta, events: list[RunEvent]) -> None:
    """整份重写（迁移旧格式 / 重启收敛时使用）；日常写入走 append_run_event。"""
    lines = "".join(json.dumps(e.model_dump(), ensure_ascii=False) + "\n" for e in events)
    _atomic_write(events_path(meta.id), lines)
    save_run_meta(meta)
    old = legacy_path(meta.id)
    if old.exists():
        old.unlink()


def _read_jsonl(path: Path) -> list[RunEvent]:
    events: list[RunEvent] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(RunEvent(**json.loads(line)))
                except Exception:
                    # 崩溃可能留下半行；跳过损坏行，保留其余完整事件
                    continue
    except Exception:
        return events
    return events


def load_run_metas() -> list[RunMeta]:
    metas: dict[str, RunMeta] = {}
    if not RUNS_DIR.exists():
        return []
    for f in sorted(RUNS_DIR.glob(f"*{META_SUFFIX}")):
        try:
            m = RunMeta(**json.loads(f.read_text("utf-8")))
            metas[m.id] = m
        except Exception:
            continue
    # 旧布局：{id}.json（排除新的 {id}.meta.json）；新布局已存在时以新布局为准
    for f in sorted(RUNS_DIR.glob("*.json")):
        if f.name.endswith(META_SUFFIX):
            continue
        try:
            m = RunMeta(**json.loads(f.read_text("utf-8"))["meta"])
            metas.setdefault(m.id, m)
        except Exception:
            continue
    return sorted(metas.values(), key=lambda m: m.createdAt, reverse=True)


def load_run_events(run_id: str) -> Optional[list[RunEvent]]:
    path = events_path(run_id)
    if path.exists():
        return _read_jsonl(path)
    legacy = legacy_path(run_id)
    if not legacy.exists():
        return None
    try:
        data = json.loads(legacy.read_text("utf-8"))
    except Exception:
        return None
    try:
        return [RunEvent(**e) for e in data.get("events", [])]
    except Exception:
        return None


def load_run_meta(run_id: str) -> Optional[RunMeta]:
    path = meta_path(run_id)
    if path.exists():
        try:
            return RunMeta(**json.loads(path.read_text("utf-8")))
        except Exception:
            pass
    legacy = legacy_path(run_id)
    if not legacy.exists():
        return None
    try:
        return RunMeta(**json.loads(legacy.read_text("utf-8"))["meta"])
    except Exception:
        return None


def delete_run_file(run_id: str) -> bool:
    removed = False
    for path in (events_path(run_id), meta_path(run_id), legacy_path(run_id)):
        if path.exists():
            path.unlink()
            removed = True
    return removed


def reconcile_stale_runs() -> list[str]:
    """进程重启后，磁盘上仍标记 running 的运行不可能再推进，统一收敛为 interrupted。"""
    fixed: list[str] = []
    for meta in load_run_metas():
        if meta.status != "running":
            continue
        events = load_run_events(meta.id) or []
        meta.status = "interrupted"
        meta.finishedAt = meta.finishedAt or now()
        events.append(
            RunEvent(
                seq=len(events) + 1,
                runId=meta.id,
                type="run.failed",
                ts=now(),
                payload={"reason": "interrupted", "message": "服务重启，运行已中断"},
            )
        )
        save_run(meta, events)  # 顺带把旧布局迁移成 JSONL
        fixed.append(meta.id)
    return fixed


def now() -> float:
    return time.time()
