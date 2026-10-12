import { Check, Loader2, Sparkles, Wand2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api } from '../api'
import type { AgentCfg, KbModel, ModelRecommendation, Provider, ProviderModel, RecommendOut } from '../types'
import { bindingLabel, Modal } from './ui'

interface Props {
  agents: AgentCfg[]
  providers: Provider[]
  models: ProviderModel[]
  onClose: () => void
  onChanged: () => void
}

const EFFORT_LABEL: Record<string, string> = {
  off: '关闭思考',
  low: '低档思考',
  medium: '中档思考',
  high: '高档思考',
  always: '固定深度思考',
  default: '默认',
}

const DIM_LABEL: Record<string, string> = {
  coding: '编码实现',
  debugging: '排查调试',
  refactoring: '重构',
  agent_tool_use: 'Agent/工具调用',
  math_reasoning: '数学/逻辑推理',
  long_context: '长上下文',
  multimodal: '多模态',
  writing_creative: '创意写作',
  writing_business: '商务写作',
  translation: '翻译',
  summarization: '总结提炼',
  qa_knowledge: '知识问答',
  data_analysis: '数据分析',
  instruction_following: '指令遵循',
}

const COST_LABEL: Record<string, string> = { low: '成本低', medium: '成本中', high: '成本高' }
const SPEED_LABEL: Record<string, string> = { fast: '响应快', medium: '速度中', slow: '响应慢' }

const COST_OPTIONS: { value: 'low' | 'balanced' | 'quality'; label: string }[] = [
  { value: 'low', label: '成本优先' },
  { value: 'balanced', label: '均衡' },
  { value: 'quality', label: '质量优先' },
]

function VendorBadge({ vendor }: { vendor: string }) {
  return (
    <span className="px-1.5 py-0.5 rounded text-[10px] border bg-slate-500/15 text-slate-300 border-slate-600/50 whitespace-nowrap">
      {vendor}
    </span>
  )
}

function EffortBadge({ effort }: { effort: string }) {
  return (
    <span className="px-1.5 py-0.5 rounded text-[10px] border bg-violet-500/15 text-violet-300 border-violet-500/40 whitespace-nowrap">
      推理：{EFFORT_LABEL[effort] || effort}
    </span>
  )
}

function RecommendationCard({ rec }: { rec: ModelRecommendation }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-sm font-semibold text-slate-100">{rec.name}</span>
      {rec.vendor && <VendorBadge vendor={rec.vendor} />}
      <EffortBadge effort={rec.reasoningEffort} />
      {rec.inWorkspace && (
        <span className="px-1.5 py-0.5 rounded text-[10px] border bg-emerald-500/15 text-emerald-300 border-emerald-500/40 whitespace-nowrap">
          工作区已配置
        </span>
      )}
    </div>
  )
}

export default function RecommendDialog({ agents, providers, models, onClose, onChanged }: Props) {
  const [tab, setTab] = useState<'recommend' | 'library'>('recommend')
  const [task, setTask] = useState('')
  const [cost, setCost] = useState<'low' | 'balanced' | 'quality'>('balanced')
  const [speed, setSpeed] = useState(false)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<RecommendOut | null>(null)
  const [error, setError] = useState('')

  const [applyAgentId, setApplyAgentId] = useState('')
  const [applying, setApplying] = useState(false)
  const [applyMsg, setApplyMsg] = useState('')

  const [kb, setKb] = useState<KbModel[] | null>(null)

  const recommend = async () => {
    if (!task.trim() || loading) return
    setLoading(true)
    setError('')
    setResult(null)
    setApplyMsg('')
    try {
      const r = await api.recommendModel(task.trim(), { cost, speed })
      setResult(r)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (tab === 'library' && kb === null) {
      api
        .selectorModels()
        .then((r) => setKb(r.models))
        .catch((e) => {
          setKb([])
          setError(e.message)
        })
    }
  }, [tab, kb])

  const apply = async () => {
    if (!result || !applyAgentId) return
    const p = result.primary
    if (!p.providerId || !p.providerModelId) return
    setApplying(true)
    setApplyMsg('')
    try {
      await api.updateAgent(applyAgentId, {
        binding: `${p.providerId}:${p.providerModelId}`,
        // always 表示模型固定思考不可调，落到 Agent 上等价于不下发档位
        effort: p.reasoningEffort === 'always' ? 'default' : p.reasoningEffort,
      })
      const name = agents.find((a) => a.id === applyAgentId)?.name || 'Agent'
      setApplyMsg(
        `已应用到「${name}」：${bindingLabel(`${p.providerId}:${p.providerModelId}`, providers, models)} · ${
          EFFORT_LABEL[p.reasoningEffort] || p.reasoningEffort
        }`,
      )
      onChanged()
    } catch (e: any) {
      setApplyMsg(`应用失败：${e.message}`)
    } finally {
      setApplying(false)
    }
  }

  return (
    <Modal title="模型推荐" onClose={onClose} wide>
      <div className="flex gap-1 mb-4 border-b border-slate-700/60">
        {(
          [
            ['recommend', '任务推荐'],
            ['library', '模型库'],
          ] as ['recommend' | 'library', string][]
        ).map(([k, label]) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`px-3 py-2 text-xs font-medium border-b-2 -mb-px transition-colors ${
              tab === k ? 'border-sky-400 text-sky-300' : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-3 text-xs text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded px-3 py-2">{error}</div>
      )}

      {tab === 'recommend' ? (
        <div className="space-y-4">
          <textarea
            value={task}
            onChange={(e) => setTask(e.target.value)}
            rows={4}
            placeholder="描述你的任务，例如：帮我排查一个 React 页面内存泄漏的 bug…"
            className="w-full bg-[#141c33] border border-slate-700 rounded-lg px-3 py-2.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500/60 resize-y"
          />

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[11px] text-slate-500">偏好：</span>
            {COST_OPTIONS.map((o) => (
              <button
                key={o.value}
                onClick={() => setCost(o.value)}
                className={`px-2.5 py-1 rounded-full text-[11px] border transition-colors ${
                  cost === o.value
                    ? 'bg-sky-500/20 text-sky-300 border-sky-500/50'
                    : 'border-slate-700 text-slate-400 hover:bg-slate-800'
                }`}
              >
                {o.label}
              </button>
            ))}
            <label className="flex items-center gap-1.5 text-[11px] text-slate-400 cursor-pointer select-none ml-1">
              <input type="checkbox" checked={speed} onChange={(e) => setSpeed(e.target.checked)} className="accent-sky-500" />
              追求响应速度
            </label>
            <div className="flex-1" />
            <button
              onClick={recommend}
              disabled={loading || !task.trim()}
              className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-medium disabled:opacity-40"
            >
              {loading ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
              {loading ? '分析中…' : '开始推荐'}
            </button>
          </div>

          {loading && <div className="text-[11px] text-slate-500">正在结合模型知识库分析任务（LLM 不可用时自动离线匹配）…</div>}

          {result && (
            <div className="space-y-3">
              <div className="flex items-center justify-end">
                <span
                  className={`px-2 py-0.5 rounded-full text-[10px] border ${
                    result.engine === 'llm'
                      ? 'bg-sky-500/15 text-sky-300 border-sky-500/40'
                      : 'bg-slate-500/15 text-slate-400 border-slate-600/50'
                  }`}
                >
                  {result.engine === 'llm' ? 'LLM 推荐' : '规则匹配（离线）'}
                </span>
              </div>

              <div className="bg-[#0d1426] border border-sky-500/30 rounded-lg p-4 space-y-2.5">
                <div className="flex items-start justify-between gap-2">
                  <RecommendationCard rec={result.primary} />
                  <span className="text-[10px] text-slate-500 shrink-0">置信度 {Math.round(result.primary.confidence * 100)}%</span>
                </div>
                <p className="text-xs text-slate-300 leading-5">{result.primary.rationale}</p>
                {result.tags.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-[10px] text-slate-500">任务特征：</span>
                    {result.tags.map((t) => (
                      <span
                        key={t}
                        className="px-1.5 py-0.5 rounded text-[10px] bg-slate-700/40 text-slate-400 border border-slate-700"
                      >
                        {DIM_LABEL[t] || t}
                      </span>
                    ))}
                  </div>
                )}

                {result.primary.inWorkspace ? (
                  <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-slate-700/50">
                    <span className="text-[11px] text-slate-500">应用到 Agent：</span>
                    <select
                      value={applyAgentId}
                      onChange={(e) => setApplyAgentId(e.target.value)}
                      className="bg-[#141c33] border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-sky-500/60"
                    >
                      <option value="">选择 Agent…</option>
                      {agents.map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.name}（当前 {bindingLabel(a.binding, providers, models)}）
                        </option>
                      ))}
                    </select>
                    <button
                      onClick={apply}
                      disabled={!applyAgentId || applying}
                      className="flex items-center gap-1 px-2.5 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-xs disabled:opacity-40"
                    >
                      {applying ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />} 绑定并设置档位
                    </button>
                    {applyMsg && <span className="text-[11px] text-emerald-300">{applyMsg}</span>}
                  </div>
                ) : (
                  <div className="flex items-center gap-1.5 pt-1 border-t border-slate-700/50 text-[11px] text-slate-500">
                    <Wand2 size={11} /> 该模型未在工作区配置：可在「供应商」中添加对应的 Provider 与模型后再绑定到 Agent。
                  </div>
                )}
              </div>

              {result.alternatives.length > 0 && (
                <div className="bg-[#0d1426] border border-slate-700/60 rounded-lg overflow-hidden">
                  <div className="px-4 py-2 border-b border-slate-700/50 text-xs font-medium text-slate-300">备选方案</div>
                  <div className="divide-y divide-slate-800/60">
                    {result.alternatives.map((a) => (
                      <div key={a.modelId} className="px-4 py-2.5 space-y-1">
                        <RecommendationCard rec={a} />
                        <p className="text-xs text-slate-400 leading-5">{a.rationale}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-[11px] text-slate-500">
            模型能力知识库（{kb?.length ?? 0} 个）。可编辑 backend/data/model_knowledge.json 增删条目，改完重启后端生效。
          </p>
          <div className="space-y-2">
            {kb === null && <div className="text-xs text-slate-500 text-center py-8">加载中…</div>}
            {kb?.length === 0 && <div className="text-xs text-slate-500 text-center py-8">知识库为空</div>}
            {kb?.map((m) => (
              <div key={m.id} className="bg-[#0d1426] border border-slate-700/60 rounded-lg p-3 space-y-1.5">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-xs font-semibold text-slate-100">{m.name}</span>
                  {m.vendor && <VendorBadge vendor={m.vendor} />}
                  <span className="px-1.5 py-0.5 rounded text-[10px] border bg-violet-500/15 text-violet-300 border-violet-500/40 whitespace-nowrap">
                    档位 {m.reasoningLevels.join(' / ')}
                  </span>
                  <span className="px-1.5 py-0.5 rounded text-[10px] border bg-slate-700/30 text-slate-400 border-slate-700">
                    {COST_LABEL[m.costTier] || m.costTier} · {SPEED_LABEL[m.speedTier] || m.speedTier}
                  </span>
                  {m.contextWindow ? (
                    <span className="px-1.5 py-0.5 rounded text-[10px] border bg-slate-700/30 text-slate-400 border-slate-700">
                      上下文 {Math.round(m.contextWindow / 1000)}K
                    </span>
                  ) : null}
                </div>
                <p className="text-[11px] text-slate-400 leading-5">{m.bestFor}</p>
                <div className="flex flex-wrap items-center gap-1">
                  <span className="text-[10px] text-slate-600">强项：</span>
                  {m.strengths.map((s) => (
                    <span key={s} className="px-1.5 py-0.5 rounded text-[10px] bg-emerald-500/10 text-emerald-300/80 border border-emerald-500/20">
                      {DIM_LABEL[s] || s}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </Modal>
  )
}
