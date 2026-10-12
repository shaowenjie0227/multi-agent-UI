// 事件重放：RunState 由 RunEvent 流纯函数折叠而来，历史回放与实时推进共用同一逻辑
import type { AgentCfg, Provider, ProviderModel, RunEvent, RunMeta, RunState } from '../types'

export interface AppState {
  providers: Provider[]
  models: ProviderModel[]
  agents: AgentCfg[]
  runs: RunMeta[]
  runId: string | null
  run: RunState | null
}

export type Action =
  | { type: 'config'; providers: Provider[]; models: ProviderModel[]; agents: AgentCfg[] }
  | { type: 'runs'; runs: RunMeta[] }
  | { type: 'openRun'; runId: string }
  | { type: 'loadEvents'; runId: string; events: RunEvent[]; meta?: RunMeta }
  | { type: 'event'; event: RunEvent }

export const initialState: AppState = {
  providers: [],
  models: [],
  agents: [],
  runs: [],
  runId: null,
  run: null,
}

export function emptyRun(id: string, task = ''): RunState {
  return {
    id,
    task,
    status: 'running',
    phase: 'analyzing',
    seen: new Set(),
    events: [],
    proposals: [],
    approval: 'none',
    finalProposal: null,
    finalResult: null,
    questions: [],
    packages: [],
    assignmentOptions: [],
    assignments: [],
    tasks: {},
    taskOrder: [],
    agents: {},
    liveByTask: {},
    liveByAgent: {},
    verdicts: [],
    handoffs: [],
    userInputs: [],
  }
}

function foldRun(rs: RunState, ev: RunEvent): RunState {
  if (rs.seen.has(ev.seq)) return rs
  const seen = new Set(rs.seen)
  seen.add(ev.seq)
  const p = ev.payload || {}
  const next: RunState = { ...rs, seen, events: [...rs.events, ev] }

  switch (ev.type) {
    case 'run.started':
      next.task = p.task || rs.task
      next.status = 'running'
      break
    case 'run.completed':
      next.status = 'completed'
      break
    case 'run.failed':
      next.status = p.reason === 'stopped' ? 'stopped' : 'failed'
      next.errorMessage = p.message || ''
      break
    case 'phase.changed':
      next.phase = p.phase
      break
    case 'proposal.updated': {
      const prop = { version: p.version, content: p.content, questions: p.questions || [], packages: p.packages || [] }
      const idx = next.proposals.findIndex((x) => x.version === p.version)
      const proposals = [...next.proposals]
      if (idx >= 0) proposals[idx] = prop
      else proposals.push(prop)
      next.proposals = proposals
      next.questions = p.questions || []
      break
    }
    case 'questions.ready':
      next.questions = p.questions || []
      break
    case 'approval.requested':
      next.approval = 'requested'
      break
    case 'approval.granted':
      next.approval = 'granted'
      break
    case 'approval.rejected':
      next.approval = 'rejected'
      break
    case 'proposal.final':
      next.finalProposal = p.content
      if (p.packages?.length) next.packages = p.packages
      break
    case 'assignment.requested':
      next.packages = p.packages || []
      next.assignmentOptions = p.agents || []
      break
    case 'assignment.confirmed':
      next.assignments = p.assignments || []
      break
    case 'user.input':
      next.userInputs = [...next.userInputs, { text: p.text, kind: p.kind, ts: ev.ts }]
      break
    case 'plan.created': {
      const tasks = { ...next.tasks }
      const order = [...next.taskOrder]
      for (const t of p.tasks || []) {
        if (!tasks[t.id]) {
          tasks[t.id] = {
            id: t.id,
            title: t.title,
            role: t.role,
            agentId: t.agentId,
            round: p.round || 1,
            status: 'pending',
            dependsOn: t.dependsOn || [],
          }
          order.push(t.id)
        }
      }
      next.tasks = tasks
      next.taskOrder = order
      break
    }
    case 'task.started': {
      const id = ev.taskId || ''
      const tasks = { ...next.tasks }
      if (!tasks[id]) {
        tasks[id] = {
          id,
          title: p.title || id,
          role: p.role || '',
          agentId: ev.agentId || p.agentId,
          round: ev.round || 1,
          status: 'running',
          dependsOn: [],
        }
        next.taskOrder = [...next.taskOrder, id]
      } else {
        tasks[id] = {
          ...tasks[id],
          status: 'running',
          title: p.title || tasks[id].title,
          agentId: ev.agentId || tasks[id].agentId || p.agentId,
        }
      }
      next.tasks = tasks
      break
    }
    case 'task.completed': {
      const id = ev.taskId || ''
      if (next.tasks[id]) {
        next.tasks = { ...next.tasks, [id]: { ...next.tasks[id], status: 'done', output: p.output } }
        // 流式增量可能因 WebSocket 队列溢出丢块，用完整产出校正监控缓冲
        next.liveByTask = { ...next.liveByTask, [id]: p.output ?? '' }
      }
      break
    }
    case 'agent.output': {
      const d = p.delta || ''
      if (d) {
        if (ev.taskId) {
          next.liveByTask = { ...next.liveByTask, [ev.taskId]: (next.liveByTask[ev.taskId] || '') + d }
        } else if (ev.agentId) {
          next.liveByAgent = { ...next.liveByAgent, [ev.agentId]: (next.liveByAgent[ev.agentId] || '') + d }
        }
      }
      break
    }
    case 'agent.status': {
      if (ev.agentId) {
        next.agents = { ...next.agents, [ev.agentId]: { status: p.status, detail: p.detail } }
      }
      // 分析师多轮对话共用 req 任务：新一轮思考开始时清掉上一轮的监控缓冲
      if (ev.taskId && p.status === 'thinking') {
        next.liveByTask = { ...next.liveByTask, [ev.taskId]: '' }
      }
      break
    }
    case 'handoff':
      next.handoffs = [
        ...next.handoffs,
        { fromTask: p.fromTask, toTask: p.toTask, note: p.note, failedItems: p.failedItems || [], kind: p.kind },
      ]
      break
    case 'review.verdict':
      next.verdicts = [
        ...next.verdicts.filter((v) => v.round !== p.round),
        { round: p.round, passed: p.passed, report: p.report, failedItems: p.failedItems || [] },
      ]
      break
    case 'result.final':
      next.finalResult = p.content
      break
    default:
      break
  }
  return next
}

export function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'config':
      return { ...state, providers: action.providers, models: action.models, agents: action.agents }
    case 'runs':
      return { ...state, runs: action.runs }
    case 'openRun':
      return { ...state, runId: action.runId }
    case 'loadEvents': {
      let rs = emptyRun(action.runId)
      if (action.meta) rs.task = action.meta.task
      for (const ev of action.events) rs = foldRun(rs, ev)
      return { ...state, runId: action.runId, run: rs }
    }
    case 'event': {
      const ev = action.event
      if (state.runId && ev.runId !== state.runId) return state
      let runId = state.runId
      let rs = state.run
      if (!rs || rs.id !== ev.runId) {
        runId = ev.runId
        rs = emptyRun(ev.runId)
      }
      return { ...state, runId, run: foldRun(rs, ev) }
    }
    default:
      return state
  }
}
