import { PackageCheck } from 'lucide-react'
import type { RunState } from '../types'
import { MarkdownView, Modal } from './ui'

export default function ResultPanel({ run, onClose }: { run: RunState; onClose: () => void }) {
  return (
    <Modal title="最终交付物" onClose={onClose} wide>
      <div className="flex items-center gap-2 mb-4 text-xs text-slate-400">
        <PackageCheck size={14} className="text-emerald-300" />
        <span>任务：{run.task}</span>
        {run.finalProposal && (
          <details className="ml-auto">
            <summary className="cursor-pointer text-sky-300 hover:text-sky-200">查看最终需求方案</summary>
            <div className="mt-2 bg-[#0d1426] rounded-lg px-4 py-3 max-h-[50vh] overflow-y-auto border border-slate-800">
              <MarkdownView>{run.finalProposal}</MarkdownView>
            </div>
          </details>
        )}
      </div>
      <div className="bg-[#0d1426] rounded-lg px-5 py-4 max-h-[65vh] overflow-y-auto border border-slate-800">
        <MarkdownView>{run.finalResult || '（暂无）'}</MarkdownView>
      </div>
    </Modal>
  )
}
