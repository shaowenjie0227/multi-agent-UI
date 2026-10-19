import { Coins, Download, FileCode2, FolderOpen, Loader2, PackageCheck, Timer } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, type RunUsage } from '../api'
import type { RunState } from '../types'
import { MarkdownView, Modal } from './ui'

function fmtTokens(n: number): string {
  if (!n) return '0'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

function download(name: string, content: string) {
  const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

export default function ResultPanel({ run, onClose }: { run: RunState; onClose: () => void }) {
  // 用量统计走后端 /usage 端点，与历史回放口径一致
  const [usage, setUsage] = useState<RunUsage | null>(null)
  useEffect(() => {
    let alive = true
    api
      .runUsage(run.id)
      .then((r) => alive && setUsage(r))
      .catch(() => undefined)
    return () => {
      alive = false
    }
  }, [run.id])
  const total = usage?.total ?? { calls: 0, totalTokens: 0, elapsedMs: 0 }
  const byModel = usage?.byModel ?? []

  // 工作区落盘文件：Agent 产出里的 ```path=...``` 块
  const [artifacts, setArtifacts] = useState<{ path: string; bytes: number }[]>([])
  const [artifactsRoot, setArtifactsRoot] = useState('')
  const [preview, setPreview] = useState<{ path: string; content: string; truncated: boolean } | null>(null)
  const [artifactBusy, setArtifactBusy] = useState(false)

  useEffect(() => {
    let alive = true
    setArtifactBusy(true)
    api
      .artifacts(run.id)
      .then((r) => {
        if (!alive) return
        setArtifacts(r.files)
        setArtifactsRoot(r.root)
      })
      .catch(() => undefined)
      .finally(() => alive && setArtifactBusy(false))
    return () => {
      alive = false
    }
  }, [run.id])

  const openArtifact = async (path: string) => {
    try {
      setPreview(await api.artifactFile(run.id, path))
    } catch {
      /* 读取失败时保持列表 */
    }
  }

  return (
    <Modal title="最终交付物" onClose={onClose} wide>
      <div className="flex flex-wrap items-center gap-2 mb-4 text-xs text-slate-400">
        <PackageCheck size={14} className="text-emerald-300" />
        <span className="truncate max-w-md">任务：{run.task}</span>
        <span className="ml-auto flex items-center gap-3">
          {total.calls > 0 && (
            <span className="flex items-center gap-1 text-slate-400" title="模型调用次数与 token 用量">
              <Coins size={12} className="text-amber-300" />
              {total.calls} 次调用 · {fmtTokens(total.totalTokens)} tokens
              {total.elapsedMs > 0 && (
                <>
                  <Timer size={11} className="ml-1.5 text-slate-500" />
                  {(total.elapsedMs / 1000).toFixed(1)}s
                </>
              )}
            </span>
          )}
          <button
            onClick={() => download(`交付物_${run.id}.md`, run.finalResult || '')}
            className="flex items-center gap-1 px-2 py-1 rounded border border-slate-700 text-slate-300 hover:bg-slate-800"
          >
            <Download size={12} /> 下载交付物
          </button>
          <button
            onClick={() => download(`需求方案_${run.id}.md`, run.finalProposal || '')}
            disabled={!run.finalProposal}
            className="flex items-center gap-1 px-2 py-1 rounded border border-slate-700 text-slate-300 hover:bg-slate-800 disabled:opacity-40"
          >
            <Download size={12} /> 下载方案
          </button>
        </span>
      </div>

      {/* 工作区落盘文件 */}
      {(artifacts.length > 0 || artifactBusy) && (
        <div className="mb-4">
          <div className="flex items-center gap-1.5 text-xs text-slate-400 mb-2">
            <FolderOpen size={13} className="text-sky-300" />
            交付文件（{artifacts.length}）
            {artifactBusy && <Loader2 size={11} className="animate-spin text-slate-500" />}
            <span className="text-[10px] text-slate-600 truncate ml-auto">{artifactsRoot}</span>
          </div>
          <div className="bg-[#0d1426] rounded-lg border border-slate-800 divide-y divide-slate-800/60 max-h-40 overflow-y-auto">
            {artifacts.map((f) => (
              <button
                key={f.path}
                onClick={() => openArtifact(f.path)}
                className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left hover:bg-slate-800/60 ${
                  preview?.path === f.path ? 'bg-slate-800/60' : ''
                }`}
              >
                <FileCode2 size={12} className="text-slate-500 shrink-0" />
                <span className="text-slate-300 truncate flex-1">{f.path}</span>
                <span className="text-[10px] text-slate-600 shrink-0">{f.bytes} B</span>
              </button>
            ))}
          </div>
          {preview && (
            <div className="mt-2 bg-[#0a0f1e] rounded-lg border border-slate-800">
              <div className="flex items-center gap-2 px-3 py-1.5 border-b border-slate-800">
                <span className="text-[11px] text-sky-300 truncate flex-1">{preview.path}</span>
                {preview.truncated && <span className="text-[10px] text-amber-300">已截断</span>}
                <button
                  onClick={() => download(preview.path.split('/').pop() || 'file.txt', preview.content)}
                  className="text-[10px] text-slate-400 hover:text-slate-200 flex items-center gap-1"
                >
                  <Download size={10} /> 下载
                </button>
              </div>
              <pre className="px-3 py-2 text-[11px] text-slate-300 overflow-auto max-h-56 whitespace-pre-wrap break-words">
                {preview.content}
              </pre>
            </div>
          )}
        </div>
      )}

      {byModel.length > 0 && (
        <details className="mb-4 text-xs">
          <summary className="cursor-pointer text-slate-500 hover:text-slate-300">
            按模型用量明细（{byModel.length} 个）
          </summary>
          <div className="mt-2 bg-[#0d1426] rounded-lg border border-slate-800 overflow-hidden">
            <table className="w-full text-left">
              <thead className="text-[10px] text-slate-500 border-b border-slate-800">
                <tr>
                  <th className="px-3 py-1.5 font-medium">供应商 / 模型</th>
                  <th className="px-3 py-1.5 font-medium text-right">调用</th>
                  <th className="px-3 py-1.5 font-medium text-right">Tokens</th>
                </tr>
              </thead>
              <tbody>
                {byModel.map((m) => (
                  <tr key={`${m.provider}/${m.model}`} className="border-b border-slate-800/60 last:border-0">
                    <td className="px-3 py-1.5 text-slate-300">
                      {m.provider} / {m.model}
                    </td>
                    <td className="px-3 py-1.5 text-right text-slate-400">{m.calls}</td>
                    <td className="px-3 py-1.5 text-right text-slate-300">{fmtTokens(m.totalTokens)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}

      {run.finalProposal && (
        <details className="mb-4">
          <summary className="cursor-pointer text-xs text-sky-300 hover:text-sky-200">查看最终需求方案</summary>
          <div className="mt-2 bg-[#0d1426] rounded-lg px-4 py-3 max-h-[50vh] overflow-y-auto border border-slate-800">
            <MarkdownView>{run.finalProposal}</MarkdownView>
          </div>
        </details>
      )}
      <div className="bg-[#0d1426] rounded-lg px-5 py-4 max-h-[65vh] overflow-y-auto border border-slate-800">
        <MarkdownView>{run.finalResult || '（暂无）'}</MarkdownView>
      </div>
    </Modal>
  )
}
