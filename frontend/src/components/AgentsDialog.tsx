import { Plus, Save, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api'
import type { AgentCfg, Provider, ProviderModel } from '../types'
import { Modal } from './ui'

interface Props {
  agents: AgentCfg[]
  providers: Provider[]
  models: ProviderModel[]
  onClose: () => void
  onChanged: () => void
}

type Draft = { name: string; role: string; persona: string; binding: string; effort: string; enabled: boolean }

const ROLE_OPTIONS = [
  { value: 'orchestrator', label: '编排者' },
  { value: 'analyst', label: '需求分析师' },
  { value: 'developer', label: '开发工程师' },
  { value: 'tester', label: '测试工程师' },
  { value: 'custom', label: '自定义专家' },
]

const EFFORT_OPTIONS = [
  { value: 'default', label: '推理：默认' },
  { value: 'off', label: '推理：关' },
  { value: 'low', label: '推理：低' },
  { value: 'medium', label: '推理：中' },
  { value: 'high', label: '推理：高' },
]

export default function AgentsDialog({ agents, providers, models, onClose, onChanged }: Props) {
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const [error, setError] = useState('')

  const draftOf = (a: AgentCfg): Draft =>
    drafts[a.id] || {
      name: a.name,
      role: a.role,
      persona: a.persona,
      binding: a.binding,
      effort: a.effort || 'default',
      enabled: a.enabled,
    }

  const setDraft = (id: string, patch: Partial<Draft>) => {
    setDrafts((d) => ({
      ...d,
      [id]: {
        ...(d[id] || { name: '', role: 'custom', persona: '', binding: 'mock', effort: 'default', enabled: true }),
        ...patch,
      },
    }))
  }

  const save = async (a: AgentCfg) => {
    setError('')
    try {
      await api.updateAgent(a.id, draftOf(a))
      onChanged()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const del = async (a: AgentCfg) => {
    if (!window.confirm(`删除 Agent「${a.name}」？`)) return
    setError('')
    try {
      await api.deleteAgent(a.id)
      onChanged()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const add = async () => {
    setError('')
    try {
      await api.createAgent({
        name: '新专家 Agent',
        role: 'custom',
        persona: '你是领域专家。根据分配的任务与上下文产出专业结果（markdown）。',
        binding: 'mock',
        enabled: false,
      })
      onChanged()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const bindingSelect = (d: Draft, onChange: (v: string) => void) => (
    <select
      value={d.binding}
      onChange={(e) => onChange(e.target.value)}
      className="bg-[#141c33] border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-sky-500/60"
    >
      <option value="mock">Mock 模拟（无需 API Key）</option>
      {providers
        .filter((p) => p.enabled)
        .map((p) => {
          const ms = models.filter((m) => m.providerId === p.id)
          if (ms.length === 0) return null
          return (
            <optgroup key={p.id} label={p.name}>
              {ms.map((m) => (
                <option key={m.id} value={`${p.id}:${m.id}`}>
                  {p.name} / {m.name}
                </option>
              ))}
            </optgroup>
          )
        })}
    </select>
  )

  return (
    <Modal title="Agent 管理" onClose={onClose} wide>
      {error && <div className="mb-3 text-xs text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded px-3 py-2">{error}</div>}
      <p className="mb-3 text-[11px] text-slate-500">
        提示：编排者按角色调度「已启用」的 Agent；每个 Agent 可绑定不同供应商的模型，或先用 Mock 模拟。
      </p>
      <div className="space-y-4">
        {agents.map((a) => {
          const d = draftOf(a)
          return (
            <div key={a.id} className="bg-[#0d1426] border border-slate-700/60 rounded-lg p-4 space-y-2.5">
              <div className="flex items-center gap-2">
                <input
                  value={d.name}
                  onChange={(e) => setDraft(a.id, { name: e.target.value })}
                  placeholder="Agent 名称"
                  className="flex-1 bg-[#141c33] border border-slate-700 rounded px-2.5 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-sky-500/60"
                />
                <select
                  value={d.role}
                  onChange={(e) => setDraft(a.id, { role: e.target.value })}
                  className="bg-[#141c33] border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300 focus:outline-none"
                >
                  {ROLE_OPTIONS.map((r) => (
                    <option key={r.value} value={r.value}>
                      {r.label}
                    </option>
                  ))}
                </select>
                {bindingSelect(d, (v) => setDraft(a.id, { binding: v }))}
                <select
                  value={d.effort}
                  onChange={(e) => setDraft(a.id, { effort: e.target.value })}
                  title="推理档位（不支持的供应商会忽略；默认=不下发）"
                  className="bg-[#141c33] border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300 focus:outline-none"
                >
                  {EFFORT_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
                <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={d.enabled}
                    onChange={(e) => setDraft(a.id, { enabled: e.target.checked })}
                    className="accent-sky-500"
                  />
                  启用
                </label>
              </div>
              <textarea
                value={d.persona}
                onChange={(e) => setDraft(a.id, { persona: e.target.value })}
                rows={5}
                placeholder="角色人设（System Prompt）"
                className="w-full bg-[#141c33] border border-slate-700 rounded px-2.5 py-2 text-xs text-slate-300 font-mono focus:outline-none focus:border-sky-500/60 resize-y"
              />
              <div className="flex gap-2">
                <button
                  onClick={() => save(a)}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded bg-sky-600 hover:bg-sky-500 text-white text-xs"
                >
                  <Save size={12} /> 保存
                </button>
                <button
                  onClick={() => del(a)}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded bg-slate-700 hover:bg-rose-600 text-slate-200 text-xs"
                >
                  <Trash2 size={12} /> 删除
                </button>
              </div>
            </div>
          )
        })}
      </div>
      <button onClick={add} className="mt-4 flex items-center gap-1.5 text-xs text-sky-300 hover:text-sky-200">
        <Plus size={13} /> 添加 Agent
      </button>
    </Modal>
  )
}
