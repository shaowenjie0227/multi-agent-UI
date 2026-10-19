import { AlertTriangle, CheckCircle2, Radar } from 'lucide-react'
import type { AgentCfg, Provider, ProviderModel, RunState } from '../types'
import { bindingLabel, RoleBadge, StatusDot } from './ui'

interface Props {
  run: RunState
  agents: AgentCfg[]
  providers: Provider[]
  models: ProviderModel[]
  onOpenAgent: (id: string) => void
}

export default function AgentPanel({ run, agents, providers, models, onOpenAgent }: Props) {
  const latestVerdict = run.verdicts[run.verdicts.length - 1]
  const involvedIds = Array.from(
    new Set([...Object.keys(run.agents), ...run.taskOrder.map((id) => run.tasks[id]?.agentId).filter(Boolean)]),
  ) as string[]
  const cards = involvedIds.map((id) => ({ cfg: agents.find((a) => a.id === id), id }))

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-2.5 border-b border-slate-700/60 flex items-center gap-2 shrink-0">
        <span className="text-sm font-medium text-slate-200">Agent 状态</span>
        <span className="text-[10px] text-slate-500">点击卡片查看实时输出</span>
        {latestVerdict && (
          <span
            className={`ml-auto flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] border ${
              latestVerdict.passed
                ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40'
                : 'bg-rose-500/15 text-rose-300 border-rose-500/40'
            }`}
          >
            {latestVerdict.passed ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />}
            第 {latestVerdict.round} 轮测试：{latestVerdict.passed ? '通过' : '不通过'}
            {latestVerdict.parsed === false && '（需人工复核）'}
          </span>
        )}
      </div>

      {latestVerdict && !latestVerdict.passed && (
        <div className="mx-4 mt-3 bg-rose-500/10 border border-rose-500/30 rounded-lg px-3.5 py-2.5 shrink-0">
          <div className="text-[11px] text-rose-300 font-medium mb-1">测试失败项（将随需求方案返回开发返工）</div>
          <ul className="space-y-0.5">
            {latestVerdict.failedItems.map((f, i) => (
              <li key={i} className="text-xs text-rose-100/90">· {f}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {cards.length === 0 && <div className="text-xs text-slate-600 text-center pt-10">等待执行…</div>}
        {cards.map(({ cfg, id }) => (
          <AgentCard
            key={id}
            cfg={cfg}
            id={id}
            status={run.agents[id]?.status}
            detail={run.agents[id]?.detail}
            run={run}
            providers={providers}
            models={models}
            onOpen={onOpenAgent}
          />
        ))}
      </div>
    </div>
  )
}

function AgentCard({
  cfg,
  id,
  status,
  detail,
  run,
  providers,
  models,
  onOpen,
}: {
  cfg?: AgentCfg
  id: string
  status?: string
  detail?: string
  run: RunState
  providers: Provider[]
  models: ProviderModel[]
  onOpen: (id: string) => void
}) {
  const name = cfg?.name || 'Agent'
  const role = cfg?.role || 'custom'
  const binding = cfg?.binding || 'mock'
  const myTasks = run.taskOrder.map((t) => run.tasks[t]).filter((t) => t.agentId === id)
  const working = status === 'working' || status === 'thinking'
  const sub =
    detail ||
    (myTasks.length > 0
      ? `共 ${myTasks.length} 个任务`
      : role === 'orchestrator'
        ? '负责需求确认与最终交付汇总'
        : '暂无任务')

  return (
    <button
      className="w-full text-left bg-[#111a30] border border-slate-700/60 rounded-lg px-3.5 py-2.5 hover:border-sky-500/50 hover:bg-[#13203a] transition-colors cursor-pointer"
      onClick={() => onOpen(id)}
    >
      <div className="flex items-center gap-2.5">
        <StatusDot status={status || (myTasks.some((t) => t.status === 'done') ? 'done' : 'pending')} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[13px] font-medium text-slate-200">{name}</span>
            <RoleBadge role={role} />
            <span className="text-[10px] text-slate-500 truncate">{bindingLabel(binding, providers, models)}</span>
          </div>
          <div className="text-[11px] text-slate-500 truncate mt-0.5">{sub}</div>
        </div>
        <Radar
          size={15}
          className={`shrink-0 ${working ? 'text-amber-300 animate-pulse' : 'text-slate-600'}`}
        />
      </div>
    </button>
  )
}
