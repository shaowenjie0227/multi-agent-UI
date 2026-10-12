import { useEffect, useRef, useState } from 'react'
import type { AgentCfg, Provider, ProviderModel, RunState } from '../types'
import { bindingLabel, MarkdownView, RoleBadge, StatusDot, StatusText } from './ui'

interface Props {
  run: RunState
  agents: AgentCfg[]
  providers: Provider[]
  models: ProviderModel[]
  agentId: string
  preferredTaskId?: string | null // 从图节点点入时，默认定位到该任务
  onClose: () => void
}

/** Agent 监控：点击图节点 / Agent 卡片打开，实时查看该 Agent 正在产出的内容。 */
export default function AgentMonitorDialog({ run, agents, providers, models, agentId, preferredTaskId, onClose }: Props) {
  const cfg = agents.find((a) => a.id === agentId)
  const myTasks = run.taskOrder.map((id) => run.tasks[id]).filter((t) => t && t.agentId === agentId)
  const running = myTasks.find((t) => t.status === 'running')
  const [picked, setPicked] = useState<string | null>(preferredTaskId ?? null)
  // 默认跟随正在执行的任务，其次最后一个任务；用户点击 chip 后锁定
  const selected = picked ?? running?.id ?? (myTasks.length ? myTasks[myTasks.length - 1].id : null)
  const selectedTask = myTasks.find((t) => t.id === selected)

  // 编排者无任务维度：汇总阶段的实时流按 agentId 记录
  const agentStream = run.liveByAgent[agentId] || ''
  const streamText = selectedTask ? run.liveByTask[selectedTask.id] || '' : agentStream
  const waitingUser = run.agents[agentId]?.status === 'waiting_user'
  const isStreaming = waitingUser
    ? false
    : selectedTask
      ? selectedTask.status === 'running'
      : run.agents[agentId]?.status === 'working'

  const bodyRef = useRef<HTMLDivElement>(null)
  const stickRef = useRef(true)
  const onScroll = () => {
    const el = bodyRef.current
    if (el) stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 60
  }
  useEffect(() => {
    const el = bodyRef.current
    if (el && stickRef.current) el.scrollTop = el.scrollHeight
  }, [streamText, selectedTask?.output, selected])

  const status = run.agents[agentId]?.status

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-6" onClick={onClose}>
      <div
        className="bg-[#101830] border border-slate-700 rounded-xl shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2.5 px-5 py-3 border-b border-slate-700/70 shrink-0">
          <StatusDot status={status || (selectedTask?.status === 'done' ? 'done' : 'pending')} />
          <h2 className="text-base font-semibold text-slate-100">Agent 监控 · {cfg?.name || '未知 Agent'}</h2>
          <RoleBadge role={cfg?.role || 'custom'} />
          <span className="text-[10px] text-slate-500 truncate">{bindingLabel(cfg?.binding || 'mock', providers, models)}</span>
          <span className="ml-auto text-xs text-slate-400">
            <StatusText status={status || selectedTask?.status} />
          </span>
          <button onClick={onClose} className="p-1 rounded hover:bg-slate-700/60 text-slate-400 hover:text-slate-200 text-lg leading-none">
            ×
          </button>
        </div>

        {myTasks.length > 0 && (
          <div className="flex flex-wrap gap-1.5 px-5 pt-3 shrink-0">
            {myTasks.map((t) => (
              <button
                key={t.id}
                onClick={() => setPicked(t.id)}
                className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] border transition-colors ${
                  selected === t.id
                    ? 'bg-sky-500/15 border-sky-500/50 text-sky-200'
                    : 'bg-[#0d1426] border-slate-700/60 text-slate-400 hover:text-slate-200 hover:border-slate-600'
                }`}
              >
                <StatusDot status={t.status} />
                <span className="max-w-52 truncate">{t.title}</span>
                {t.round > 1 && <span className="px-1 rounded bg-rose-500/20 text-rose-300 text-[9px] border border-rose-500/40">R{t.round}</span>}
              </button>
            ))}
          </div>
        )}

        <div className="flex-1 min-h-0 p-5 pt-3 flex flex-col">
          <div className="flex items-center gap-2 mb-2 shrink-0">
            <span className="text-[11px] text-slate-500 truncate">
              {selectedTask ? `任务：${selectedTask.title}` : myTasks.length ? '' : '该 Agent 无独立任务，产出为最终交付汇总'}
            </span>
            {isStreaming && (
              <span className="ml-auto flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] bg-amber-500/15 text-amber-300 border border-amber-500/40 shrink-0">
                <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400 blink" />
                实时输出中
              </span>
            )}
          </div>
          <div
            ref={bodyRef}
            onScroll={onScroll}
            className={`flex-1 min-h-0 overflow-y-auto rounded-lg border border-slate-800 px-4 py-3 bg-[#0a0f1e] ${
              isStreaming ? 'font-mono text-[11.5px] leading-relaxed whitespace-pre-wrap break-words text-slate-200' : ''
            }`}
          >
            {isStreaming ? (
              streamText ? (
                <>
                  {streamText}
                  <span className="text-amber-300 animate-pulse">▍</span>
                </>
              ) : (
                <span className="text-slate-500 font-sans text-xs">已启动，等待模型输出…</span>
              )
            ) : selectedTask?.output ? (
              <MarkdownView>{selectedTask.output}</MarkdownView>
            ) : streamText ? (
              // 等待用户输入 / 多轮任务间歇：展示已产出的流式内容
              streamText
            ) : selectedTask ? (
              <span className="text-slate-500 text-xs">{selectedTask.status === 'error' ? '该任务执行失败，无产出' : '暂无产出'}</span>
            ) : (
              <span className="text-slate-500 text-xs">暂无输出（汇总阶段开始后这里会实时滚动显示）</span>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
