import { FolderOpen, Gauge, Globe, Loader2, Lock, RefreshCw, Save, Terminal, Wand2, Zap } from 'lucide-react'
import { useEffect, useState } from 'react'
import { api, setToken } from '../api'
import type { Provider } from '../types'
import { Modal } from './ui'

interface Props {
  onClose: () => void
}

type ProxyMode = 'none' | 'system' | 'custom'

const PROXY_MODE_LABEL: Record<ProxyMode, string> = {
  none: '不使用代理（直连）',
  system: '跟随系统代理',
  custom: '使用本机代理（自定义端口）',
}

function delayColor(ms: number | null): string {
  if (ms === null) return 'text-slate-500'
  if (ms < 200) return 'text-emerald-300'
  if (ms < 500) return 'text-amber-300'
  return 'text-rose-300'
}

export default function SettingsDialog({ onClose }: Props) {
  const [loaded, setLoaded] = useState(false)
  const [proxy, setProxy] = useState<{ mode: ProxyMode; host: string; port: number }>({
    mode: 'custom',
    host: '127.0.0.1',
    port: 7897,
  })
  const [clash, setClash] = useState<{ controllerUrl: string; secret: string }>({
    controllerUrl: 'http://127.0.0.1:9097',
    secret: '',
  })
  const [workspaceEnabled, setWorkspaceEnabled] = useState(true)
  const [authToken, setAuthToken] = useState('')
  const [sandboxEnabled, setSandboxEnabled] = useState(true)
  const [sandbox, setSandbox] = useState<{ enabled: boolean; timeoutSeconds: number; maxOutputChars: number }>({
    enabled: true,
    timeoutSeconds: 30,
    maxOutputChars: 8000,
  })

  const [subUrl, setSubUrl] = useState('')
  const [subNodes, setSubNodes] = useState<{ name: string; type: string }[]>([])
  const [groups, setGroups] = useState<{ name: string; now: string; all: string[] }[]>([])
  const [group, setGroup] = useState('')
  const [results, setResults] = useState<{ name: string; delayMs: number | null }[]>([])
  const [selected, setSelected] = useState<{ name: string; delayMs: number } | null>(null)

  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    ;(async () => {
      try {
        const s = await api.settings()
        setProxy(s.proxy)
        setClash(s.clash)
        if (s.workspace) setWorkspaceEnabled(!!s.workspace.enabled)
        if (s.sandbox) {
          setSandbox(s.sandbox)
          setSandboxEnabled(!!s.sandbox.enabled)
        }
        if (s.auth) setAuthToken(s.auth.token || '')
      } catch {
        /* 使用默认值 */
      }
      setLoaded(true)
    })()
  }, [])

  const flash = (m: string) => {
    setMsg(m)
    setTimeout(() => setMsg(''), 2500)
  }

  const saveProxy = async () => {
    setBusy('saveProxy')
    setError('')
    try {
      await api.updateSettings({ proxy })
      flash('代理设置已保存')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy('')
    }
  }

  const saveClash = async () => {
    setBusy('saveClash')
    setError('')
    try {
      await api.updateSettings({ clash })
      flash('Clash 连接信息已保存')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy('')
    }
  }

  const fetchSub = async () => {    setBusy('sub')
    setError('')
    setSubNodes([])
    try {
      const r = await api.clashSubscription(subUrl.trim())
      setSubNodes(r.nodes)
      flash(`解析成功，共 ${r.nodes.length} 个节点`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy('')
    }
  }

  const fetchGroups = async () => {
    setBusy('groups')
    setError('')
    try {
      const r = await api.clashGroups()
      setGroups(r.groups)
      if (r.groups.length > 0) setGroup(r.groups[0].name)
      else setError('Clash 中没有策略组')
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy('')
    }
  }

  const testDelay = async () => {
    if (!group) return
    setBusy('delay')
    setError('')
    setSelected(null)
    try {
      const g = groups.find((x) => x.name === group)
      const r = await api.clashDelay(g?.all || [])
      setResults(r.results)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy('')
    }
  }

  const autoSelect = async () => {
    if (!group) return
    setBusy('auto')
    setError('')
    setSelected(null)
    try {
      const r = await api.clashAutoSelect(group)
      setResults(r.results)
      setSelected({ name: r.selected, delayMs: r.delayMs })
      setGroups((gs) => gs.map((g) => (g.name === group ? { ...g, now: r.selected } : g)))
      flash(`已切换到最快节点：${r.selected}（${r.delayMs}ms）`)
    } catch (e: any) {
      setError(e.message)
    } finally {
      setBusy('')
    }
  }

  const currentGroup = groups.find((g) => g.name === group)

  return (
    <Modal title="设置" onClose={onClose} wide>
      {error && <div className="mb-3 text-xs text-rose-300 bg-rose-500/10 border border-rose-500/30 rounded px-3 py-2">{error}</div>}
      {msg && <div className="mb-3 text-xs text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 rounded px-3 py-2">{msg}</div>}
      {!loaded ? (
        <div className="flex justify-center py-10 text-slate-500">
          <Loader2 className="animate-spin" />
        </div>
      ) : (
        <div className="space-y-5">
          {/* ---------- 访问令牌 ---------- */}
          <section className="bg-[#0d1426] border border-slate-700/60 rounded-lg p-4 space-y-2">
            <div className="flex items-center gap-2">
              <Lock size={15} className="text-amber-300" />
              <span className="text-sm font-medium text-slate-200">访问令牌</span>
              <span className="text-[11px] text-slate-500">留空 = 不校验（仅本机使用）；填写后所有接口与实时连接都需携带</span>
            </div>
            <div className="flex gap-2">
              <input
                type="password"
                value={authToken}
                onChange={(e) => setAuthToken(e.target.value)}
                placeholder="留空表示不启用鉴权"
                className="flex-1 bg-[#141c33] border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-sky-500/60"
              />
              <button
                onClick={async () => {
                  setBusy('auth')
                  setError('')
                  try {
                    await api.updateSettings({ auth: { token: authToken.trim() } })
                    setToken(authToken.trim()) // 前端同步保存，后续请求自动带上
                    flash(authToken.trim() ? '访问令牌已启用' : '访问令牌已清除（不再校验）')
                  } catch (e: any) {
                    setError(e.message)
                  } finally {
                    setBusy('')
                  }
                }}
                disabled={busy === 'auth'}
                className="flex items-center gap-1 px-3 py-1.5 rounded bg-sky-600 hover:bg-sky-500 text-white text-xs disabled:opacity-50"
              >
                <Save size={12} /> 保存
              </button>
            </div>
          </section>

          {/* ---------- 工作区 ---------- */}
          <section className="bg-[#0d1426] border border-slate-700/60 rounded-lg p-4 space-y-2">
            <div className="flex items-center gap-2">
              <FolderOpen size={15} className="text-emerald-300" />
              <span className="text-sm font-medium text-slate-200">交付文件落盘</span>
              <span className="text-[11px] text-slate-500">
                把工作包产出中带 <code className="text-slate-400">path=</code> 的代码块写入
                backend/data/workspace/&lt;运行 id&gt;/
              </span>
            </div>
            <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={workspaceEnabled}
                onChange={async (e) => {
                  const enabled = e.target.checked
                  setWorkspaceEnabled(enabled)
                  try {
                    await api.updateSettings({ workspace: { enabled } })
                    flash(enabled ? '已开启交付文件落盘' : '已关闭交付文件落盘')
                  } catch (err: any) {
                    setError(err.message)
                    setWorkspaceEnabled(!enabled)
                  }
                }}
                className="accent-emerald-500"
              />
              启用（关闭后 Agent 产出只作为文本报告，不写文件）
            </label>
          </section>

          {/* ---------- 命令执行 ---------- */}
          <section className="bg-[#0d1426] border border-slate-700/60 rounded-lg p-4 space-y-2">
            <div className="flex items-center gap-2">
              <Terminal size={15} className="text-sky-300" />
              <span className="text-sm font-medium text-slate-200">命令执行（联调验收）</span>
              <span className="text-[11px] text-slate-500">
                测试工程师验收前在工作区跑测试；仅允许 python / node
              </span>
            </div>
            <label className="flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
              <input
                type="checkbox"
                checked={sandboxEnabled}
                onChange={async (e) => {
                  const enabled = e.target.checked
                  setSandboxEnabled(enabled)
                  try {
                    await api.updateSettings({ sandbox: { ...sandbox, enabled } })
                    flash(enabled ? '已开启命令执行' : '已关闭命令执行')
                  } catch (err: any) {
                    setError(err.message)
                    setSandboxEnabled(!enabled)
                  }
                }}
                className="accent-sky-500"
              />
              启用（关闭后测试工程师只看文档做验收）
            </label>
            <div className="flex items-center gap-3 text-[11px] text-slate-400">
              <label className="flex items-center gap-1.5">
                超时
                <input
                  type="number"
                  min={1}
                  max={120}
                  value={sandbox.timeoutSeconds}
                  onChange={(e) => setSandbox({ ...sandbox, timeoutSeconds: Number(e.target.value) })}
                  className="w-16 bg-[#141c33] border border-slate-700 rounded px-1.5 py-0.5 text-slate-300"
                />
                秒
              </label>
              <label className="flex items-center gap-1.5">
                输出上限
                <input
                  type="number"
                  min={200}
                  max={20000}
                  step={500}
                  value={sandbox.maxOutputChars}
                  onChange={(e) => setSandbox({ ...sandbox, maxOutputChars: Number(e.target.value) })}
                  className="w-20 bg-[#141c33] border border-slate-700 rounded px-1.5 py-0.5 text-slate-300"
                />
                字符
              </label>
              <button
                onClick={async () => {
                  setBusy('sandbox')
                  try {
                    await api.updateSettings({ sandbox })
                    flash('命令执行参数已保存')
                  } catch (err: any) {
                    setError(err.message)
                  } finally {
                    setBusy('')
                  }
                }}
                disabled={busy === 'sandbox'}
                className="flex items-center gap-1 px-2 py-1 rounded bg-sky-600/80 hover:bg-sky-600 text-white disabled:opacity-50"
              >
                <Save size={11} /> 保存参数
              </button>
            </div>
            <div className="text-[10px] text-amber-300/80 bg-amber-500/5 border border-amber-500/20 rounded px-2 py-1.5">
              ⚠️ 不是强安全沙箱：白名单内的解释器仍能读写进程可及的文件。仅在本地开发使用，勿在多租户环境开启。
            </div>
          </section>

          {/* ---------- 代理设置 ---------- */}
          <section className="bg-[#0d1426] border border-slate-700/60 rounded-lg p-4 space-y-3">
            <div className="flex items-center gap-2">
              <Globe size={15} className="text-sky-300" />
              <span className="text-sm font-medium text-slate-200">代理设置</span>
              <span className="text-[11px] text-slate-500">仅作用于真实 LLM 调用与订阅拉取，不影响本机面板通信</span>
            </div>
            <div className="grid grid-cols-[240px_1fr_1fr_auto] gap-2 items-center">
              <select
                value={proxy.mode}
                onChange={(e) => setProxy({ ...proxy, mode: e.target.value as ProxyMode })}
                className="bg-[#141c33] border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-sky-500/60"
              >
                {(Object.keys(PROXY_MODE_LABEL) as ProxyMode[]).map((m) => (
                  <option key={m} value={m}>
                    {PROXY_MODE_LABEL[m]}
                  </option>
                ))}
              </select>
              <input
                value={proxy.host}
                onChange={(e) => setProxy({ ...proxy, host: e.target.value })}
                disabled={proxy.mode !== 'custom'}
                placeholder="代理地址，如 127.0.0.1"
                className="bg-[#141c33] border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-300 disabled:opacity-40 focus:outline-none focus:border-sky-500/60"
              />
              <input
                type="number"
                value={proxy.port}
                onChange={(e) => setProxy({ ...proxy, port: parseInt(e.target.value, 10) || 0 })}
                disabled={proxy.mode !== 'custom'}
                placeholder="端口，如 7897"
                className="bg-[#141c33] border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-300 disabled:opacity-40 focus:outline-none focus:border-sky-500/60"
              />
              <button
                onClick={saveProxy}
                disabled={busy === 'saveProxy'}
                className="flex items-center gap-1 px-3 py-1.5 rounded bg-sky-600 hover:bg-sky-500 text-white text-xs disabled:opacity-50"
              >
                {busy === 'saveProxy' ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />} 保存
              </button>
            </div>
          </section>

          {/* ---------- Clash 集成 ---------- */}
          <section className="bg-[#0d1426] border border-slate-700/60 rounded-lg p-4 space-y-3">
            <div className="flex items-center gap-2">
              <Zap size={15} className="text-violet-300" />
              <span className="text-sm font-medium text-slate-200">Clash 集成</span>
              <span className="text-[11px] text-slate-500">需在 Clash Verge 设置中开启「外部控制」</span>
            </div>

            {/* 控制器连接 */}
            <div className="grid grid-cols-[1fr_180px_auto] gap-2 items-center">
              <input
                value={clash.controllerUrl}
                onChange={(e) => setClash({ ...clash, controllerUrl: e.target.value })}
                placeholder="外部控制地址，如 http://127.0.0.1:9097"
                className="bg-[#141c33] border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-sky-500/60"
              />
              <input
                type="password"
                value={clash.secret}
                onChange={(e) => setClash({ ...clash, secret: e.target.value })}
                placeholder="密钥 Secret（可空）"
                className="bg-[#141c33] border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-sky-500/60"
              />
              <div className="flex gap-1.5">
                <button
                  onClick={saveClash}
                  disabled={busy === 'saveClash'}
                  className="flex items-center gap-1 px-3 py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs"
                >
                  <Save size={12} /> 保存
                </button>
                <button
                  onClick={fetchGroups}
                  disabled={busy === 'groups'}
                  className="flex items-center gap-1 px-3 py-1.5 rounded bg-violet-600 hover:bg-violet-500 text-white text-xs disabled:opacity-50"
                >
                  {busy === 'groups' ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} 获取策略组
                </button>
              </div>
            </div>

            {/* 订阅解析 */}
            <div className="flex gap-2 items-center">
              <input
                value={subUrl}
                onChange={(e) => setSubUrl(e.target.value)}
                placeholder="粘贴订阅地址（Clash YAML 或 Base64 分享链接），拉取并解析可用节点"
                className="flex-1 bg-[#141c33] border border-slate-700 rounded px-2.5 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-sky-500/60"
              />
              <button
                onClick={fetchSub}
                disabled={busy === 'sub' || !subUrl.trim()}
                className="flex items-center gap-1 px-3 py-1.5 rounded bg-sky-600 hover:bg-sky-500 text-white text-xs disabled:opacity-50 shrink-0"
              >
                {busy === 'sub' ? <Loader2 size={12} className="animate-spin" /> : <Globe size={12} />} 拉取订阅
              </button>
            </div>
            {subNodes.length > 0 && (
              <div className="bg-[#101830] border border-slate-800 rounded-lg px-3 py-2 max-h-32 overflow-y-auto">
                <div className="text-[11px] text-slate-400 mb-1">订阅节点（{subNodes.length}）</div>
                <div className="flex flex-wrap gap-1">
                  {subNodes.map((n, i) => (
                    <span
                      key={i}
                      className="px-1.5 py-0.5 rounded-full bg-slate-700/50 border border-slate-600/60 text-[10px] text-slate-300 max-w-[240px] truncate"
                      title={`${n.name} · ${n.type}`}
                    >
                      {n.name}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* 分组操作 */}
            {groups.length > 0 && (
              <div className="space-y-2">
                <div className="flex gap-2 items-center">
                  <select
                    value={group}
                    onChange={(e) => setGroup(e.target.value)}
                    className="flex-1 bg-[#141c33] border border-slate-700 rounded px-2 py-1.5 text-xs text-slate-300 focus:outline-none focus:border-sky-500/60"
                  >
                    {groups.map((g) => (
                      <option key={g.name} value={g.name}>
                        {g.name}（当前：{g.now || '-'}，{g.all?.length || 0} 个成员）
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={testDelay}
                    disabled={busy === 'delay'}
                    className="flex items-center gap-1 px-3 py-1.5 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs disabled:opacity-50 shrink-0"
                  >
                    {busy === 'delay' ? <Loader2 size={12} className="animate-spin" /> : <Gauge size={12} />} 测速
                  </button>
                  <button
                    onClick={autoSelect}
                    disabled={busy === 'auto'}
                    className="flex items-center gap-1 px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white text-xs disabled:opacity-50 shrink-0"
                  >
                    {busy === 'auto' ? <Loader2 size={12} className="animate-spin" /> : <Wand2 size={12} />} 自动选择最快节点
                  </button>
                </div>
                {currentGroup && (
                  <div className="text-[11px] text-slate-500 flex items-center gap-1">
                    <Zap size={10} className="text-emerald-300" /> 当前选中：<span className="text-slate-300">{currentGroup.now || '-'}</span>
                  </div>
                )}
                {selected && (
                  <div className="text-[11px] text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 rounded px-2.5 py-1.5">
                    ✅ 已自动切换到最快节点：{selected.name}（{selected.delayMs}ms）
                  </div>
                )}
                {results.length > 0 && (
                  <div className="bg-[#101830] border border-slate-800 rounded-lg px-3 py-2 max-h-44 overflow-y-auto">
                    <div className="text-[11px] text-slate-400 mb-1">
                      节点延迟（{results.filter((r) => r.delayMs !== null).length}/{results.length} 可用）
                    </div>
                    <div className="space-y-0.5">
                      {[...results]
                        .sort((a, b) => (a.delayMs ?? 10 ** 9) - (b.delayMs ?? 10 ** 9))
                        .map((r) => (
                          <div key={r.name} className="flex items-center justify-between text-[11px]">
                            <span className="text-slate-300 truncate max-w-[75%]" title={r.name}>
                              {r.name}
                              {currentGroup?.now === r.name && <span className="ml-1.5 text-emerald-400">· 当前</span>}
                            </span>
                            <span className={delayColor(r.delayMs)}>{r.delayMs !== null ? `${r.delayMs}ms` : '超时'}</span>
                          </div>
                        ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      )}
    </Modal>
  )
}
