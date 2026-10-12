import { Activity, Bot, History, Package, Play, Settings, Settings2, Sparkles, Square, Users, Wifi, WifiOff } from 'lucide-react'
import { useState } from 'react'
import type { RunMeta, RunState } from '../types'

interface Props {
  task: string
  setTask: (v: string) => void
  agentCount: string
  setAgentCount: (v: string) => void
  run: RunState | null
  runs: RunMeta[]
  connected: boolean
  busy: boolean
  hasResult: boolean
  onStart: () => void
  onStop: () => void
  onOpenRecommend: () => void
  onOpenSettings: () => void
  onOpenProviders: () => void
  onOpenAgents: () => void
  onOpenHistory: (id: string) => void
  onOpenResult: () => void
}

const RUN_STATUS: Record<string, { label: string; cls: string }> = {
  running: { label: '运行中', cls: 'bg-amber-500/15 text-amber-300 border-amber-500/40' },
  completed: { label: '已完成', cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40' },
  failed: { label: '失败', cls: 'bg-rose-500/15 text-rose-300 border-rose-500/40' },
  stopped: { label: '已停止', cls: 'bg-slate-500/15 text-slate-300 border-slate-500/40' },
}

export default function TopBar(p: Props) {
  const [histOpen, setHistOpen] = useState(false)
  const active = p.run?.status === 'running'
  const status = p.run ? RUN_STATUS[p.run.status] : null

  return (
    <div className="flex items-center gap-3 px-4 py-2.5 border-b border-slate-800 bg-[#0c1327] shrink-0 relative z-10">
      <div className="flex items-center gap-2 shrink-0">
        <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-violet-500 to-sky-500 flex items-center justify-center">
          <Bot size={16} className="text-white" />
        </div>
        <span className="text-sm font-semibold text-slate-100 whitespace-nowrap">多 Agent 协同工作台</span>
      </div>

      <textarea
        value={p.task}
        onChange={(e) => p.setTask(e.target.value)}
        rows={1}
        placeholder="输入任务需求，如：做一个用户登录与权限管理系统…（Enter 发起）"
        className="flex-1 min-w-0 bg-[#0d1426] border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 placeholder-slate-600 resize-none focus:outline-none focus:border-sky-500/60 h-9 leading-5"
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !active) {
            e.preventDefault()
            p.onStart()
          }
        }}
      />

      <input
        type="number"
        min={1}
        max={5}
        value={p.agentCount}
        onChange={(e) => p.setAgentCount(e.target.value)}
        placeholder="Agent 数"
        title="希望拆分为几个 Agent 协作（留空由需求分析师自行判断）"
        className="w-24 shrink-0 bg-[#0d1426] border border-slate-700 rounded-lg px-2.5 py-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-sky-500/60 h-9"
      />

      {active ? (
        <button
          onClick={p.onStop}
          className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-rose-600/90 hover:bg-rose-600 text-white text-xs font-medium shrink-0"
        >
          <Square size={12} /> 停止
        </button>
      ) : (
        <button
          onClick={p.onStart}
          disabled={p.busy || !p.task.trim()}
          className="flex items-center gap-1.5 px-3.5 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-medium disabled:opacity-40 shrink-0"
        >
          <Play size={12} /> 启动
        </button>
      )}

      {status && (
        <span className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] border ${status.cls} shrink-0`}>
          <Activity size={11} />
          {status.label}
        </span>
      )}

      {p.hasResult && (
        <button
          onClick={p.onOpenResult}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-emerald-600/20 border border-emerald-500/40 text-emerald-300 text-xs font-medium hover:bg-emerald-600/30 shrink-0"
        >
          <Package size={13} /> 交付物
        </button>
      )}

      <div className="flex items-center gap-1.5 shrink-0">
        <button
          onClick={p.onOpenRecommend}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-sky-500/40 text-sky-300 text-xs hover:bg-sky-500/10"
        >
          <Sparkles size={13} /> 模型推荐
        </button>
        <button
          onClick={p.onOpenProviders}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-700 text-slate-300 text-xs hover:bg-slate-800"
        >
          <Settings2 size={13} /> 供应商
        </button>
        <button
          onClick={p.onOpenSettings}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-700 text-slate-300 text-xs hover:bg-slate-800"
        >
          <Settings size={13} /> 设置
        </button>
        <button
          onClick={p.onOpenAgents}
          className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-700 text-slate-300 text-xs hover:bg-slate-800"
        >
          <Users size={13} /> Agent
        </button>
        <div className="relative">
          <button
            onClick={() => setHistOpen(!histOpen)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-700 text-slate-300 text-xs hover:bg-slate-800"
          >
            <History size={13} /> 历史
          </button>
          {histOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setHistOpen(false)} />
              <div className="absolute right-0 top-11 z-20 w-80 bg-[#101830] border border-slate-700 rounded-lg shadow-2xl overflow-hidden max-h-80 overflow-y-auto">
                {p.runs.length === 0 && <div className="px-4 py-6 text-xs text-slate-500 text-center">暂无历史运行</div>}
                {p.runs.map((r) => (
                  <button
                    key={r.id}
                    onClick={() => {
                      setHistOpen(false)
                      p.onOpenHistory(r.id)
                    }}
                    className={`w-full text-left px-3.5 py-2.5 hover:bg-slate-800/70 border-b border-slate-800/60 ${
                      p.run?.id === r.id ? 'bg-slate-800/50' : ''
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <span
                        className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                          r.status === 'running'
                            ? 'bg-amber-400 blink'
                            : r.status === 'completed'
                              ? 'bg-emerald-400'
                              : r.status === 'failed'
                                ? 'bg-rose-500'
                                : 'bg-slate-500'
                        }`}
                      />
                      <span className="text-xs text-slate-200 truncate flex-1">{r.task}</span>
                    </div>
                    <div className="text-[10px] text-slate-500 mt-0.5">
                      {new Date(r.createdAt * 1000).toLocaleString('zh-CN', { hour12: false })} · {r.id}
                    </div>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      </div>

      <div className="flex items-center gap-1 text-[11px] shrink-0" title={p.connected ? '已连接' : '未连接'}>
        {p.connected ? <Wifi size={13} className="text-emerald-400" /> : <WifiOff size={13} className="text-rose-400" />}
      </div>
    </div>
  )
}
