import { ArrowRight, GitBranch, ListChecks, Play, Undo2, Users } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import type { AssignmentOption, Provider, ProviderModel, RunState, WorkPackage } from '../types'
import { bindingLabel, RoleBadge } from './ui'

interface Props {
  run: RunState
  agents: AssignmentOption[]
  providers: Provider[]
  models: ProviderModel[]
  onConfirm: (assignments: { packageKey: string; agentId: string; model?: string }[]) => void
  onBack: () => void
  busy?: boolean
}

type Selection = { agentId: string; model: string } // model: 'follow' | 'mock' | '{pid}:{mid}'

export default function AssignmentPanel({ run, agents, providers, models, onConfirm, onBack, busy }: Props) {
  const packages: WorkPackage[] = run.packages
  const [sel, setSel] = useState<Record<string, Selection>>({})

  // 默认分配：按建议角色名匹配 Agent，否则优先开发类角色（工作包通常是开发性质）
  const defaultSel = useMemo(() => {
    const fallback =
      agents.find((a) => a.role === 'developer') || agents.find((a) => a.role !== 'orchestrator') || agents[0]
    const map: Record<string, Selection> = {}
    for (const p of packages) {
      const matched =
        agents.find((a) => a.name === p.agentName) ||
        agents.find((a) => p.agentName.includes(a.name) || a.name.includes(p.agentName.replace('工程师', '')))
      const agent = matched || fallback
      map[p.key] = { agentId: agent?.id || '', model: 'follow' }
    }
    return map
  }, [packages, agents])

  useEffect(() => {
    if (Object.keys(sel).length === 0 && packages.length > 0) setSel(defaultSel)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [packages.length, agents.length])

  const confirm = () => {
    const assignments = packages.map((p) => {
      const s = sel[p.key] || defaultSel[p.key]
      const a: { packageKey: string; agentId: string; model?: string } = { packageKey: p.key, agentId: s.agentId }
      if (s.model !== 'follow') a.model = s.model
      return a
    })
    onConfirm(assignments)
  }

  const setPackageSel = (key: string, patch: Partial<Selection>) =>
    setSel((s) => ({ ...s, [key]: { ...(s[key] || defaultSel[key] || { agentId: '', model: 'follow' }), ...patch } }))

  const modelOptions: [string, string][] = []
  for (const p of providers.filter((x) => x.enabled)) {
    for (const m of models.filter((m) => m.providerId === p.id)) {
      modelOptions.push([`${p.id}:${m.id}`, `${p.name} / ${m.name}`])
    }
  }

  if (packages.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-slate-600 gap-2 text-sm">
        <div className="text-3xl">🧩</div>
        等待需求分析师产出工作拆解…
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-2.5 border-b border-slate-700/60 flex items-center gap-2 shrink-0">
        <GitBranch size={15} className="text-violet-300" />
        <span className="text-sm font-medium text-slate-200">任务分配</span>
        <span className="text-[11px] text-slate-500">为每个工作包选择执行 Agent 与模型</span>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {packages.map((p) => {
          const s = sel[p.key] || defaultSel[p.key] || { agentId: '', model: 'follow' }
          const agent = agents.find((a) => a.id === s.agentId)
          const effectiveBinding =
            s.model === 'follow' ? agent?.binding || 'mock' : s.model === 'mock' ? 'mock' : s.model
          return (
            <div key={p.key} className="bg-[#111a30] border border-slate-700/60 rounded-lg p-3.5 space-y-2.5">
              <div className="flex items-center gap-2">
                <span className="px-1.5 py-0.5 rounded bg-slate-700/60 text-slate-300 text-[10px] border border-slate-600">
                  {p.key}
                </span>
                <Users size={13} className="text-violet-300" />
                <span className="text-[13px] font-medium text-slate-100">{p.agentName}</span>
                {p.dependsOn.length > 0 && (
                  <span className="text-[10px] text-amber-300/80 flex items-center gap-0.5">
                    <ArrowRight size={10} /> 依赖 {p.dependsOn.join(', ')}
                  </span>
                )}
              </div>
              {p.responsibility && <div className="text-xs text-slate-400">{p.responsibility}</div>}
              {p.tasks.length > 0 && (
                <ul className="space-y-0.5">
                  {p.tasks.map((t, i) => (
                    <li key={i} className="text-xs text-slate-300 flex gap-1.5">
                      <ListChecks size={11} className="text-slate-500 mt-0.5 shrink-0" /> {t}
                    </li>
                  ))}
                </ul>
              )}
              {p.integration && (
                <div className="text-[11px] text-sky-300/80 bg-sky-500/5 border border-sky-500/20 rounded px-2 py-1">
                  联调：{p.integration}
                </div>
              )}
              <div className="flex items-center gap-2 pt-1">
                <select
                  value={s.agentId}
                  onChange={(e) => setPackageSel(p.key, { agentId: e.target.value, model: 'follow' })}
                  className="flex-1 bg-[#141c33] border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-sky-500/60"
                >
                  {agents.length === 0 && <option value="">（没有启用的 Agent）</option>}
                  {agents.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}（{a.role}）
                    </option>
                  ))}
                </select>
                <select
                  value={s.model}
                  onChange={(e) => setPackageSel(p.key, { model: e.target.value })}
                  className="flex-1 bg-[#141c33] border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-sky-500/60"
                >
                  <option value="follow">模型：跟随 Agent 绑定</option>
                  <option value="mock">模型：Mock 模拟</option>
                  {modelOptions.map(([value, label]) => (
                    <option key={value} value={value}>
                      模型：{label}
                    </option>
                  ))}
                </select>
              </div>
              {agent && (
                <div className="flex items-center gap-1.5">
                  <RoleBadge role={agent.role} />
                  <span className="text-[10px] text-slate-500">
                    {s.model === 'follow' ? '将使用' : '覆盖为'} {bindingLabel(effectiveBinding, providers, models)}
                  </span>
                </div>
              )}
            </div>
          )
        })}
      </div>

      <div className="p-3 border-t border-slate-700/60 shrink-0 flex gap-2">
        <button
          onClick={confirm}
          disabled={busy || agents.length === 0}
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-xs font-medium disabled:opacity-50"
        >
          <Play size={13} /> 确认分配，开始执行
        </button>
        <button
          onClick={onBack}
          disabled={busy}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-slate-700/80 hover:bg-slate-700 text-slate-200 text-xs font-medium disabled:opacity-50"
        >
          <Undo2 size={12} /> 返回修改方案
        </button>
      </div>
    </div>
  )
}
