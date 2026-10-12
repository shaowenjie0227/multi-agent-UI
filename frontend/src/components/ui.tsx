import { X } from 'lucide-react'
import type { ReactNode } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Provider, ProviderModel } from '../types'

export function Modal({
  title,
  onClose,
  children,
  wide,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  wide?: boolean
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-6" onClick={onClose}>
      <div
        className={`bg-[#101830] border border-slate-700 rounded-xl shadow-2xl w-full ${wide ? 'max-w-4xl' : 'max-w-2xl'} max-h-[85vh] flex flex-col`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-700/70">
          <h2 className="text-base font-semibold text-slate-100">{title}</h2>
          <button onClick={onClose} className="p-1 rounded hover:bg-slate-700/60 text-slate-400 hover:text-slate-200">
            <X size={18} />
          </button>
        </div>
        <div className="overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  )
}

export function MarkdownView({ children, className = '' }: { children: string; className?: string }) {
  return (
    <div className={`prose prose-invert prose-sm max-w-none break-words ${className}`}>
      <Markdown remarkPlugins={[remarkGfm]}>{children}</Markdown>
    </div>
  )
}

export const ROLE_META: Record<string, { label: string; color: string }> = {
  orchestrator: { label: '编排者', color: 'bg-violet-500/20 text-violet-300 border-violet-500/40' },
  analyst: { label: '需求分析师', color: 'bg-sky-500/20 text-sky-300 border-sky-500/40' },
  developer: { label: '开发工程师', color: 'bg-amber-500/20 text-amber-300 border-amber-500/40' },
  tester: { label: '测试工程师', color: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40' },
  custom: { label: '专家', color: 'bg-slate-500/20 text-slate-300 border-slate-500/40' },
}

export const STATUS_META: Record<string, { label: string; dot: string; text: string }> = {
  pending: { label: '待执行', dot: 'bg-slate-500', text: 'text-slate-400' },
  running: { label: '进行中', dot: 'bg-amber-400 blink', text: 'text-amber-300' },
  thinking: { label: '思考中', dot: 'bg-amber-400 blink', text: 'text-amber-300' },
  working: { label: '工作中', dot: 'bg-amber-400 blink', text: 'text-amber-300' },
  waiting_user: { label: '等待你', dot: 'bg-sky-400 blink', text: 'text-sky-300' },
  done: { label: '已完成', dot: 'bg-emerald-400', text: 'text-emerald-300' },
  error: { label: '出错', dot: 'bg-rose-500', text: 'text-rose-300' },
}

export function StatusDot({ status }: { status?: string }) {
  const meta = STATUS_META[status || 'pending'] || STATUS_META.pending
  return <span className={`inline-block w-2 h-2 rounded-full ${meta.dot}`} />
}

export function StatusText({ status }: { status?: string }) {
  const meta = STATUS_META[status || 'pending'] || STATUS_META.pending
  return <span className={`text-xs ${meta.text}`}>{meta.label}</span>
}

export function RoleBadge({ role }: { role: string }) {
  const meta = ROLE_META[role] || ROLE_META.custom
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] border ${meta.color} whitespace-nowrap`}>{meta.label}</span>
  )
}

/** binding → 显示名（如 "xAI / grok-4.7" 或 "Mock 模拟"） */
export function bindingLabel(
  binding: string,
  providers: Provider[],
  models: ProviderModel[],
): string {
  if (!binding || binding === 'mock') return 'Mock 模拟'
  const [pid, mid] = binding.split(':')
  const provider = providers.find((p) => p.id === pid)
  const model = models.find((m) => m.id === mid)
  if (!provider || !model) return '未绑定模型'
  return `${provider.name} / ${model.name}`
}
