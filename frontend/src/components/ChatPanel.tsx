import { Bot, CheckCircle2, ChevronDown, GitBranch, HelpCircle, MessageSquarePlus, RefreshCcw, ShieldCheck, User } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { RunState } from '../types'
import { MarkdownView, StatusDot, StatusText } from './ui'

interface Props {
  run: RunState
  onSend: (text: string, kind: 'message' | 'approve' | 'reject') => void
  busy?: boolean
}

export default function ChatPanel({ run, onSend, busy }: Props) {
  const [text, setText] = useState('')
  const [showOld, setShowOld] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const latest = run.proposals[run.proposals.length - 1]
  const older = run.proposals.slice(0, -1)
  const gate = run.approval === 'requested'
  const waiting = latest && run.agents[Object.keys(run.agents).find((id) => run.agents[id].status === 'waiting_user') || '']

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [run.userInputs.length, run.proposals.length, run.approval])

  const send = (kind: 'message' | 'approve' | 'reject', t?: string) => {
    const v = (t ?? text).trim()
    if (!v && kind === 'message') return
    onSend(v, kind)
    setText('')
  }

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-2.5 border-b border-slate-700/60 flex items-center gap-2 shrink-0">
        <Bot size={16} className="text-sky-300" />
        <span className="text-sm font-medium text-slate-200">需求分析对话</span>
        <span className="ml-auto flex items-center gap-1.5">
          <StatusDot status={waiting?.status || (gate ? 'waiting_user' : 'thinking')} />
          <StatusText status={waiting?.status || (gate ? 'waiting_user' : 'thinking')} />
        </span>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {older.length > 0 && (
          <div>
            <button
              onClick={() => setShowOld(!showOld)}
              className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300"
            >
              <ChevronDown size={12} className={showOld ? 'rotate-180 transition-transform' : 'transition-transform'} />
              历史版本（{older.length}）
            </button>
            {showOld && (
              <div className="mt-2 space-y-2">
                {older.map((p) => (
                  <details key={p.version} className="bg-[#0d1426] border border-slate-800 rounded-lg px-3 py-2">
                    <summary className="text-xs text-slate-500 cursor-pointer">方案 v{p.version}</summary>
                    <MarkdownView className="mt-2">{p.content}</MarkdownView>
                  </details>
                ))}
              </div>
            )}
          </div>
        )}

        {latest && (
          <div className="flex gap-2">
            <div className="mt-1 shrink-0 w-7 h-7 rounded-full bg-sky-500/20 border border-sky-500/40 flex items-center justify-center">
              <Bot size={14} className="text-sky-300" />
            </div>
            <div className="flex-1 bg-[#12203a] border border-sky-500/30 rounded-lg rounded-tl-sm px-3.5 py-2.5">
              <div className="text-[10px] text-sky-300/80 mb-1">
                需求分析师 · 方案 v{latest.version}
                {gate && <span className="ml-2 text-emerald-300">· 完整方案待确认</span>}
              </div>
              <MarkdownView>{latest.content}</MarkdownView>
            </div>
          </div>
        )}

        {run.questions.length > 0 && !gate && (
          <div className="ml-9 bg-amber-500/10 border border-amber-500/30 rounded-lg px-3.5 py-2.5">
            <div className="flex items-center gap-1.5 text-[11px] text-amber-300 mb-1.5 font-medium">
              <HelpCircle size={12} /> 边界问题，期待你的回答
            </div>
            <ul className="space-y-1">
              {run.questions.map((q, i) => (
                <li key={i} className="text-xs text-amber-100/90 flex gap-1.5">
                  <span className="text-amber-400/70">{i + 1}.</span> {q}
                </li>
              ))}
            </ul>
          </div>
        )}

        {latest && latest.packages.length > 0 && (
          <div className="ml-9 bg-violet-500/10 border border-violet-500/30 rounded-lg px-3.5 py-2.5">
            <div className="flex items-center gap-1.5 text-[11px] text-violet-300 mb-1.5 font-medium">
              <GitBranch size={12} /> 工作拆解 · {latest.packages.length} 个工作包
            </div>
            <ul className="space-y-1.5">
              {latest.packages.map((p) => (
                <li key={p.key} className="text-xs text-slate-200">
                  <span className="text-violet-300 font-medium">{p.agentName}</span>
                  <span className="text-slate-500"> · {p.responsibility}</span>
                  {p.tasks.length > 0 && (
                    <div className="text-[11px] text-slate-400 mt-0.5 pl-3">
                      {p.tasks.slice(0, 3).join('；')}
                    </div>
                  )}
                </li>
              ))}
            </ul>
            <div className="text-[10px] text-slate-500 mt-2">确认方案后，你将在此为每个工作包分配 Agent 与模型。</div>
            {run.planWarnings.length > 0 && (
              <div className="mt-2 pt-2 border-t border-violet-500/20 text-[10px] text-amber-300/90 space-y-0.5">
                {run.planWarnings.slice(-4).map((w, i) => (
                  <div key={i}>⚠️ {w}</div>
                ))}
              </div>
            )}
          </div>
        )}

        {gate && (
          <div className="ml-9 bg-emerald-500/10 border border-emerald-500/40 rounded-lg px-3.5 py-3">
            <div className="flex items-center gap-1.5 text-[11px] text-emerald-300 mb-2 font-medium">
              <ShieldCheck size={13} /> 需求方案确认门
            </div>
            <p className="text-xs text-slate-300 mb-2.5">请确认方案是否满意：满意将锁定方案并进入开发；不满意可继续对话修改。</p>
            <div className="flex gap-2">
              <button
                disabled={busy}
                onClick={() => send('approve', '满意，进入开发')}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-emerald-500/90 hover:bg-emerald-500 text-white text-xs font-medium disabled:opacity-50"
              >
                <CheckCircle2 size={13} /> 满意，进入开发
              </button>
              <button
                disabled={busy}
                onClick={() => send('reject', '')}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-slate-700/80 hover:bg-slate-700 text-slate-200 text-xs font-medium disabled:opacity-50"
              >
                <RefreshCcw size={12} /> 不满意，继续修改
              </button>
            </div>
          </div>
        )}

        {run.userInputs.map((u, i) => (
          <div key={i} className="flex gap-2 justify-end">
            <div className="max-w-[80%] bg-[#1d2a4a] border border-slate-600/60 rounded-lg rounded-tr-sm px-3 py-2">
              <div className="flex items-center gap-1 text-[10px] text-slate-400 mb-0.5 justify-end">
                <User size={10} />
                {u.kind === 'approve' ? '你 · 确认满意' : u.kind === 'reject' ? '你 · 要求继续修改' : '你'}
              </div>
              <div className="text-xs text-slate-200 whitespace-pre-wrap">{u.text || '（继续修改）'}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="p-3 border-t border-slate-700/60 shrink-0">
        <div className="flex gap-2 items-end">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                send('message')
              }
            }}
            rows={2}
            placeholder={gate ? '填写修改意见后发送，或点击上方按钮…' : '回答边界问题 / 提出修改意见（Enter 发送）…'}
            className="flex-1 bg-[#0d1426] border border-slate-700 rounded-lg px-3 py-2 text-xs text-slate-200 placeholder-slate-600 resize-none focus:outline-none focus:border-sky-500/60"
          />
          <button
            onClick={() => send('message')}
            disabled={busy}
            className="px-3 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-medium flex items-center gap-1 disabled:opacity-50"
          >
            <MessageSquarePlus size={13} /> 发送
          </button>
        </div>
      </div>
    </div>
  )
}
