import { AlertTriangle, ArrowRightLeft, Bot, CheckCircle2, ClipboardCheck, FileText, MessageSquare, Play, Terminal, User, XCircle, Zap } from 'lucide-react'
import { useEffect, useRef } from 'react'
import type { AgentCfg, RunEvent } from '../types'

const STYLE: Record<string, { icon: any; color: string; label: string }> = {
  'run.started': { icon: Play, color: 'text-violet-300', label: '运行开始' },
  'run.completed': { icon: CheckCircle2, color: 'text-emerald-300', label: '运行完成' },
  'run.failed': { icon: XCircle, color: 'text-rose-300', label: '运行失败' },
  'phase.changed': { icon: Zap, color: 'text-violet-300', label: '阶段切换' },
  'proposal.updated': { icon: FileText, color: 'text-sky-300', label: '方案更新' },
  'proposal.final': { icon: FileText, color: 'text-emerald-300', label: '方案定稿' },
  'questions.ready': { icon: MessageSquare, color: 'text-amber-300', label: '提出边界问题' },
  'approval.requested': { icon: ClipboardCheck, color: 'text-emerald-300', label: '等待你确认方案' },
  'approval.granted': { icon: CheckCircle2, color: 'text-emerald-300', label: '你确认了方案' },
  'approval.rejected': { icon: RefreshCcwIcon, color: 'text-amber-300', label: '你要求继续修改' },
  'user.input': { icon: User, color: 'text-slate-300', label: '你的输入' },
  'plan.created': { icon: Zap, color: 'text-violet-300', label: '生成执行计划' },
  'task.started': { icon: Bot, color: 'text-amber-300', label: '任务开始' },
  'task.completed': { icon: CheckCircle2, color: 'text-emerald-300', label: '任务完成' },
  'agent.status': { icon: Bot, color: 'text-slate-400', label: '状态' },
  handoff: { icon: ArrowRightLeft, color: 'text-rose-300', label: '返工交接' },
  'review.verdict': { icon: ClipboardCheck, color: 'text-emerald-300', label: '测试结论' },
  'plan.warning': { icon: AlertTriangle, color: 'text-amber-300', label: '拆解校正' },
  'artifact.written': { icon: FileText, color: 'text-emerald-300', label: '文件落盘' },
  'artifact.rejected': { icon: AlertTriangle, color: 'text-rose-300', label: '文件被拒' },
  'check.finished': { icon: Terminal, color: 'text-sky-300', label: '命令校验' },
  'result.final': { icon: CheckCircle2, color: 'text-emerald-300', label: '最终交付' },
}

function RefreshCcwIcon(props: any) {
  return <Zap {...props} />
}

const PHASE_LABEL: Record<string, string> = {
  analyzing: '需求分析（对话中）',
  assigning: '任务分配',
  approved: '需求已确认',
  executing: '开发 ⇄ 测试执行中',
  delivering: '汇总交付',
}

function describe(ev: RunEvent, agentName: (id?: string) => string): string {
  const p = ev.payload || {}
  switch (ev.type) {
    case 'run.started':
      return `任务：${p.task}`
    case 'phase.changed':
      return PHASE_LABEL[p.phase] || p.phase
    case 'proposal.updated':
      return `产出需求方案 v${p.version}${(p.questions || []).length ? `，${p.questions.length} 个边界问题` : ''}`
    case 'questions.ready':
      return (p.questions || []).map((q: string, i: number) => `${i + 1}. ${q}`).join('　')
    case 'approval.requested':
      return `方案 v${p.version} 已完整，等待确认`
    case 'approval.granted':
      return '已确认方案'
    case 'approval.rejected':
      return p.note || '要求继续修改'
    case 'assignment.requested':
      return `${(p.packages || []).length} 个工作包待分配执行 Agent`
    case 'assignment.confirmed':
      return (p.assignments || []).map((a: any) => `${a.packageKey} → ${a.agentName}`).join('，')
    case 'user.input':
      return p.text || '（继续修改）'
    case 'task.started':
      return `${agentName(ev.agentId || undefined)} 开始「${p.title}」`
    case 'task.completed':
      return `「${p.title}」完成，产出已记录`
    case 'agent.status':
      return `${agentName(ev.agentId || undefined)}：${p.detail || p.status}`
    case 'handoff':
      return `${p.note}（失败项 ${p.failedItems?.length || 0} 个）`
    case 'review.verdict':
      return `第 ${p.round} 轮测试${p.passed ? '通过 ✅' : '不通过 ❌'}${
        p.parsed === false ? '（结论解析失败，需人工复核）' : ''
      }`
    case 'plan.created':
      return `编排者生成 ${(p.tasks || []).length} 个任务（第 ${p.round} 轮）`
    case 'plan.warning':
      return (p.warnings || []).join('；')
    case 'usage.reported':
      return `${p.provider || 'Mock'} / ${p.model || 'Mock'} · ${p.totalTokens || 0} tokens`
    case 'artifact.written':
      return `已写入 ${p.path}（${p.bytes} B）${p.package ? ` · ${p.package}` : ''}`
    case 'artifact.rejected':
      return `${p.path}：${p.reason}`
    case 'check.finished': {
      const status = !p.allowed
        ? '被安全策略拒绝'
        : p.timedOut
          ? '超时'
          : `exit=${p.exitCode}`
      return `$ ${p.command} → ${status}（${p.durationMs || 0}ms）`
    }
    case 'run.failed':
      return p.message || ''
    default:
      return ''
  }
}

export default function EventStream({ events, agents }: { events: RunEvent[]; agents: AgentCfg[] }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight })
  }, [events.length])
  const agentName = (id?: string | null) => agents.find((a) => a.id === id)?.name || '系统'

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-2 border-b border-slate-700/60 shrink-0">
        <span className="text-xs font-medium text-slate-300">实时消息流</span>
      </div>
      <div ref={ref} className="flex-1 overflow-y-auto px-4 py-2 space-y-1">
        {events.length === 0 && <div className="text-xs text-slate-600 text-center pt-8">暂无消息</div>}
        {events
          .filter((e) => e.type !== 'agent.status' && e.type !== 'agent.output' && e.type !== 'usage.reported') // 高频/明细事件不进消息流
          .map((ev) => {
            const st = STYLE[ev.type] || { icon: Zap, color: 'text-slate-400', label: ev.type }
            const text = describe(ev, agentName)
            const Icon = st.icon
            const time = new Date(ev.ts * 1000).toLocaleTimeString('zh-CN', { hour12: false })
            const isHandoff = ev.type === 'handoff'
            return (
              <div
                key={ev.seq}
                className={`flex items-start gap-2 text-xs py-1 ${isHandoff ? 'bg-rose-500/10 rounded px-2 -mx-2' : ''}`}
              >
                <Icon size={12} className={`${st.color} mt-0.5 shrink-0`} />
                <span className="text-slate-500 shrink-0 tabular-nums">{time}</span>
                <span className={`${st.color} shrink-0 font-medium`}>{st.label}</span>
                <span className="text-slate-300 min-w-0">{text || '—'}</span>
              </div>
            )
          })}
      </div>
    </div>
  )
}
