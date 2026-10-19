"""共享数据模型：配置实体、运行事件、请求体。字段名与前端 TS 类型保持一致（camelCase）。"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

# ---------------- 配置实体 ----------------


class Provider(BaseModel):
    id: str
    name: str
    baseUrl: str = ""
    apiKey: str = ""
    enabled: bool = True


class ProviderModel(BaseModel):
    id: str
    providerId: str
    name: str
    note: str = ""


Effort = Literal["default", "off", "low", "medium", "high"]


class Agent(BaseModel):
    id: str
    name: str
    role: Literal["orchestrator", "analyst", "developer", "tester", "custom"] = "custom"
    persona: str = ""
    binding: str = "mock"  # "mock" 或 "{providerId}:{modelId}"
    effort: Effort = "default"  # 推理档位，default=不下发（由供应商默认行为决定）
    enabled: bool = True


# ---------------- 运行事件 ----------------


class RunEvent(BaseModel):
    seq: int
    runId: str
    type: str
    ts: float
    agentId: Optional[str] = None
    taskId: Optional[str] = None
    round: Optional[int] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class RunMeta(BaseModel):
    id: str
    task: str
    status: str = "running"  # running | completed | failed | stopped | interrupted
    createdAt: float = 0.0
    finishedAt: Optional[float] = None


# ---------------- 请求体 ----------------


class ProviderIn(BaseModel):
    name: str
    baseUrl: str = ""
    apiKey: str = ""
    enabled: bool = True


class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    baseUrl: Optional[str] = None
    apiKey: Optional[str] = None
    enabled: Optional[bool] = None


class ModelIn(BaseModel):
    name: str
    note: str = ""


class AgentIn(BaseModel):
    name: str
    role: Literal["orchestrator", "analyst", "developer", "tester", "custom"] = "custom"
    persona: str = ""
    binding: str = "mock"
    effort: Effort = "default"
    enabled: bool = True


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[Literal["orchestrator", "analyst", "developer", "tester", "custom"]] = None
    persona: Optional[str] = None
    binding: Optional[str] = None
    effort: Optional[Effort] = None
    enabled: Optional[bool] = None


class RunStartIn(BaseModel):
    task: str
    agentCount: Optional[int] = None  # 用户期望拆分为几个 Agent 协作（可空=由分析师判断）


class RunInputIn(BaseModel):
    text: str = ""
    kind: Literal["message", "approve", "reject", "assignment"] = "message"
    assignments: list[dict[str, Any]] = Field(default_factory=list)  # kind=assignment 时生效


# ---------------- 全局设置（代理 / Clash 集成） ----------------


class ProxySettings(BaseModel):
    mode: Literal["none", "system", "custom"] = "custom"  # none=直连 system=跟随系统 custom=本机代理
    host: str = "127.0.0.1"
    port: int = 7897


class ClashSettings(BaseModel):
    controllerUrl: str = "http://127.0.0.1:9097"  # Clash Verge「外部控制」地址
    secret: str = ""


class WorkspaceSettings(BaseModel):
    enabled: bool = True  # 把工作包产出中的 ```path=...``` 文件块真正写到工作区


class SandboxSettings(BaseModel):
    enabled: bool = True  # 允许在工作区执行白名单命令（python/node），用于跑测试
    timeoutSeconds: int = 30
    maxOutputChars: int = 8000


class AuthSettings(BaseModel):
    # 为空 = 不校验（仅本机使用）；设置后所有 /api 与 /ws 需带 token
    token: str = ""


class AppSettings(BaseModel):
    proxy: ProxySettings = Field(default_factory=ProxySettings)
    clash: ClashSettings = Field(default_factory=ClashSettings)
    workspace: WorkspaceSettings = Field(default_factory=WorkspaceSettings)
    sandbox: SandboxSettings = Field(default_factory=SandboxSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)


class SettingsUpdate(BaseModel):
    proxy: Optional[ProxySettings] = None
    clash: Optional[ClashSettings] = None
    workspace: Optional[WorkspaceSettings] = None
    sandbox: Optional[SandboxSettings] = None
    auth: Optional[AuthSettings] = None


class SubscriptionIn(BaseModel):
    url: str


class ClashDelayIn(BaseModel):
    names: list[str] = Field(default_factory=list)  # 为空则测当前分组的全部节点


class ClashSelectIn(BaseModel):
    group: str
    name: str


# ---------------- 模型推荐 ----------------


class PreferIn(BaseModel):
    cost: Literal["low", "balanced", "quality"] = "balanced"
    speed: bool = False


class RecommendIn(BaseModel):
    task: str
    prefer: PreferIn = Field(default_factory=PreferIn)
