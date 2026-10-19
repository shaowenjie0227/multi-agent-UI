import { Eye, EyeOff, Loader2, Plus, RefreshCw, Save, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api'
import type { Provider, ProviderModel } from '../types'
import { Modal } from './ui'

interface Props {
  providers: Provider[]
  models: ProviderModel[]
  onClose: () => void
  onChanged: () => void
}

type Draft = { name: string; baseUrl: string; apiKey: string; enabled: boolean }

export default function ProvidersDialog({ providers, models, onClose, onChanged }: Props) {
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const [showKey, setShowKey] = useState<Record<string, boolean>>({})
  const [newModel, setNewModel] = useState<Record<string, string>>({})
  const [suggestions, setSuggestions] = useState<Record<string, string[]>>({})
  const [fetching, setFetching] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState<Draft | null>(null)

  const draftOf = (p: Provider): Draft =>
    drafts[p.id] || { name: p.name, baseUrl: p.baseUrl, apiKey: p.apiKey, enabled: p.enabled }

  const setDraft = (id: string, patch: Partial<Draft>) => {
    setDrafts((d) => ({ ...d, [id]: { ...(d[id] || { name: '', baseUrl: '', apiKey: '', enabled: true }), ...patch } }))
  }

  const save = async (p: Provider) => {
    setError('')
    try {
      await api.updateProvider(p.id, draftOf(p))
      onChanged()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const del = async (p: Provider) => {
    if (!window.confirm(`删除供应商「${p.name}」及其全部模型？绑定它的 Agent 将失效。`)) return
    setError('')
    try {
      await api.deleteProvider(p.id)
      onChanged()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const addModel = async (pid: string, name: string) => {
    if (!name.trim()) return
    setError('')
    try {
      await api.addModel(pid, { name: name.trim() })
      setNewModel((m) => ({ ...m, [pid]: '' }))
      onChanged()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const fetchModelList = async (p: Provider) => {
    setError('')
    setFetching(p.id)
    try {
      const r = await api.fetchModels(p.id)
      setSuggestions((s) => ({ ...s, [p.id]: r.models }))
    } catch (e: any) {
      setError(e.message)
    } finally {
      setFetching(null)
    }
  }

  const createProvider = async () => {
    if (!creating?.name.trim()) return
    setError('')
    try {
      await api.createProvider(creating)
      setCreating(null)
      onChanged()
    } catch (e: any) {
      setError(e.message)
    }
  }

  const modelsOf = (pid: string) => models.filter((m) => m.providerId === pid)
  const existing = new Set(models.map((m) => m.name))

  return (
    <Modal title="供应商管理" onClose={onClose} wide>
      {error && <div className="mb-3 text-xs text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded px-3 py-2">{error}</div>}
      <div className="space-y-4">
        {providers.map((p) => {
          const d = draftOf(p)
          const sug = (suggestions[p.id] || []).filter((s) => !existing.has(s))
          return (
            <div key={p.id} className="bg-[#0d1426] border border-slate-700/60 rounded-lg p-4 space-y-3">
              <div className="flex items-center gap-2">
                <input
                  value={d.name}
                  onChange={(e) => setDraft(p.id, { name: e.target.value })}
                  placeholder="供应商名称"
                  className="flex-1 bg-[#141c33] border border-slate-700 rounded px-2.5 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-sky-500/60"
                />
                <label className="flex items-center gap-1.5 text-xs text-slate-400 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={d.enabled}
                    onChange={(e) => setDraft(p.id, { enabled: e.target.checked })}
                    className="accent-sky-500"
                  />
                  启用
                </label>
              </div>
              <div className="grid grid-cols-[1fr_240px_auto] gap-2">
                <input
                  value={d.baseUrl}
                  onChange={(e) => setDraft(p.id, { baseUrl: e.target.value })}
                  placeholder="Base URL（如 https://api.x.ai/v1）"
                  className="bg-[#141c33] border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-sky-500/60"
                />
                <div className="relative">
                  <input
                    type={showKey[p.id] ? 'text' : 'password'}
                    value={d.apiKey}
                    onChange={(e) => setDraft(p.id, { apiKey: e.target.value })}
                    onFocus={() => {
                      // 后端只回传掩码：聚焦时清空，避免用户把掩码当作真实 Key 保存
                      if (d.apiKey.includes('*')) setDraft(p.id, { apiKey: '' })
                    }}
                    placeholder={p.hasApiKey ? '已配置（留空表示不修改）' : 'API Key'}
                    className="w-full bg-[#141c33] border border-slate-700 rounded px-2.5 py-1.5 pr-8 text-xs text-slate-300 focus:outline-none focus:border-sky-500/60"
                  />
                  <button
                    onClick={() => setShowKey((s) => ({ ...s, [p.id]: !s[p.id] }))}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
                  >
                    {showKey[p.id] ? <EyeOff size={13} /> : <Eye size={13} />}
                  </button>
                </div>
                <div className="flex gap-1.5">
                  <button
                    onClick={() => save(p)}
                    className="flex items-center gap-1 px-2.5 py-1.5 rounded bg-sky-600 hover:bg-sky-500 text-white text-xs"
                  >
                    <Save size={12} /> 保存
                  </button>
                  <button
                    onClick={() => del(p)}
                    className="flex items-center gap-1 px-2.5 py-1.5 rounded bg-slate-700 hover:bg-rose-600 text-slate-200 text-xs"
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
              </div>
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-[11px] text-slate-500">模型列表</span>
                  <button
                    onClick={() => fetchModelList(p)}
                    disabled={fetching === p.id}
                    className="flex items-center gap-1 text-[11px] text-sky-300 hover:text-sky-200 disabled:opacity-50"
                  >
                    {fetching === p.id ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
                    拉取模型列表
                  </button>
                </div>
                <div className="flex flex-wrap gap-1.5 mb-2">
                  {modelsOf(p.id).map((m) => (
                    <span
                      key={m.id}
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-violet-500/15 border border-violet-500/40 text-[11px] text-violet-200"
                    >
                      {m.name}
                      <button
                        onClick={async () => {
                          await api.deleteModel(p.id, m.id)
                          onChanged()
                        }}
                        className="text-violet-300/60 hover:text-rose-300"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                  {modelsOf(p.id).length === 0 && <span className="text-[11px] text-slate-600">暂无模型，手动添加或拉取</span>}
                </div>
                {sug.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mb-2">
                    {sug.slice(0, 30).map((s) => (
                      <button
                        key={s}
                        onClick={() => addModel(p.id, s)}
                        className="px-2 py-0.5 rounded-full border border-dashed border-sky-500/50 text-[11px] text-sky-300 hover:bg-sky-500/15"
                      >
                        ＋ {s}
                      </button>
                    ))}
                  </div>
                )}
                <div className="flex gap-2">
                  <input
                    value={newModel[p.id] || ''}
                    onChange={(e) => setNewModel((m) => ({ ...m, [p.id]: e.target.value }))}
                    onKeyDown={(e) => e.key === 'Enter' && addModel(p.id, newModel[p.id] || '')}
                    placeholder="手动输入模型名（如 grok-4.7）回车添加"
                    className="flex-1 bg-[#141c33] border border-slate-700 rounded px-2.5 py-1 text-xs text-slate-300 focus:outline-none focus:border-sky-500/60"
                  />
                </div>
              </div>
            </div>
          )
        })}
      </div>

      <div className="mt-4">
        {creating ? (
          <div className="bg-[#0d1426] border border-sky-500/40 rounded-lg p-4 space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <input
                value={creating.name}
                onChange={(e) => setCreating({ ...creating, name: e.target.value })}
                placeholder="供应商名称（如 OpenAI）"
                className="bg-[#141c33] border border-slate-700 rounded px-2.5 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-sky-500/60"
              />
              <input
                value={creating.baseUrl}
                onChange={(e) => setCreating({ ...creating, baseUrl: e.target.value })}
                placeholder="Base URL（如 https://api.openai.com/v1）"
                className="bg-[#141c33] border border-slate-700 rounded px-2.5 py-1.5 text-sm text-slate-200 focus:outline-none focus:border-sky-500/60"
              />
            </div>
            <input
              type="password"
              value={creating.apiKey}
              onChange={(e) => setCreating({ ...creating, apiKey: e.target.value })}
              placeholder="API Key（可稍后填写）"
              className="w-full bg-[#141c33] border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-sky-500/60"
            />
            <div className="flex gap-2">
              <button onClick={createProvider} className="px-3 py-1.5 rounded bg-sky-600 hover:bg-sky-500 text-white text-xs">
                创建
              </button>
              <button onClick={() => setCreating(null)} className="px-3 py-1.5 rounded bg-slate-700 text-slate-200 text-xs">
                取消
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => setCreating({ name: '', baseUrl: '', apiKey: '', enabled: true })}
            className="flex items-center gap-1.5 text-xs text-sky-300 hover:text-sky-200"
          >
            <Plus size={13} /> 添加供应商
          </button>
        )}
      </div>
    </Modal>
  )
}
