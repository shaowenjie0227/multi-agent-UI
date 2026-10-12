// 与后端 Pydantic 模型一一对应

export interface Provider {
  id: string
  name: string
  baseUrl: string
  apiKey: string
  enabled: boolean
}

export interface ProviderModel {
  id: string
  providerId: string
  name: string
  note: string
}

export type AgentRole = 'orchestrator' | 'analyst' | 'developer' | 'tester' | 'custom'

export interface AgentCfg {
  id: string
  name: string
  role: AgentRole
  persona: string
  binding: string // "mock" 或 "{providerId}:{modelId}"
  effort?: 'default' | 'off' | 'low' | 'medium' | 'high' // 推理档位，default=不下发
  enabled: boolean
}

export interface RunMeta {
  id: string
  task: string
  status: 'running' | 'completed' | 'failed' | 'stopped'
  createdAt: number
  finishedAt?: number | null
}

export interface WorkPackage {
  key: string
  agentName: string
  responsibility: string
  tasks: string[]
  integration: string
  dependsOn: string[]
}

export interface AssignmentOption {
  id: string
  name: string
  role: string
  binding: string
}

export interface Assignment {
  packageKey: string
  agentId: string
  agentName: string
  binding: string
}

export interface RunEvent {
  seq: number
  runId: string
  type: string
  ts: number
  agentId?: string | null
  taskId?: string | null
  round?: number | null
  payload: Record<string, any>
}

// ---------- 派生状态（事件重放结果） ----------

export type TaskStatus = 'pending' | 'running' | 'done' | 'error'

export interface TaskNode {
  id: string
  title: string
  role: string
  agentId?: string
  round: number
  status: TaskStatus
  dependsOn: string[]
  output?: string
}

export interface AgentState {
  status?: string
  detail?: string
}

export interface Proposal {
  version: number
  content: string
  questions: string[]
  packages: WorkPackage[]
}

export interface Verdict {
  round: number
  passed: boolean
  report: string
  failedItems: string[]
}

export interface Handoff {
  fromTask: string
  toTask: string
  note: string
  failedItems: string[]
  kind: string
}

export interface UserInput {
  text: string
  kind: 'message' | 'approve' | 'reject' | 'assignment'
  ts: number
}

export interface RunState {
  id: string
  task: string
  status: 'running' | 'completed' | 'failed' | 'stopped'
  phase: string
  seen: Set<number>
  events: RunEvent[]
  proposals: Proposal[]
  approval: 'none' | 'requested' | 'granted' | 'rejected'
  finalProposal: string | null
  finalResult: string | null
  questions: string[]
  packages: WorkPackage[]
  assignmentOptions: AssignmentOption[]
  assignments: Assignment[]
  tasks: Record<string, TaskNode>
  taskOrder: string[]
  agents: Record<string, AgentState>
  liveByTask: Record<string, string> // 监控：taskId → 流式累积输出（task.completed 时校正为完整产出）
  liveByAgent: Record<string, string> // 监控：agentId → 无任务维度的流式输出（编排者汇总阶段）
  verdicts: Verdict[]
  handoffs: Handoff[]
  userInputs: UserInput[]
  errorMessage?: string
}

export type Approval = RunState['approval']

// ---------- 模型推荐 ----------

export type ReasoningEffort = 'off' | 'low' | 'medium' | 'high' | 'always'

export interface ModelRecommendation {
  modelId: string
  name: string
  vendor: string
  reasoningEffort: ReasoningEffort
  rationale: string
  confidence: number
  inWorkspace: boolean
  providerId?: string | null
  providerModelId?: string | null
}

export interface RecommendOut {
  engine: 'llm' | 'rules'
  tags: string[]
  primary: ModelRecommendation
  alternatives: ModelRecommendation[]
}

export interface KbModel {
  id: string
  name: string
  vendor: string
  family?: string
  strengths: string[]
  weaknesses: string[]
  contextWindow?: number
  reasoningLevels: string[]
  speedTier: string
  costTier: string
  bestFor: string
  apiNames?: string[]
}
