import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { api } from './api'
import AgentMonitorDialog from './components/AgentMonitorDialog'
import AgentPanel from './components/AgentPanel'
import AgentsDialog from './components/AgentsDialog'
import AssignmentPanel from './components/AssignmentPanel'
import ChatPanel from './components/ChatPanel'
import EventStream from './components/EventStream'
import FlowGraph from './components/FlowGraph'
import ProvidersDialog from './components/ProvidersDialog'
import RecommendDialog from './components/RecommendDialog'
import ResultPanel from './components/ResultPanel'
import SettingsDialog from './components/SettingsDialog'
import TopBar from './components/TopBar'
import { useSocket } from './hooks/useSocket'
import { initialState, reducer } from './state/reducer'
import type { RunEvent } from './types'

type SideTab = 'chat' | 'assign' | 'agents'

export default function App() {
  const [state, dispatch] = useReducer(reducer, initialState)
  const [task, setTask] = useState('')
  const [agentCount, setAgentCount] = useState('')
  const [busy, setBusy] = useState(false)
  const [showProviders, setShowProviders] = useState(false)
  const [showAgents, setShowAgents] = useState(false)
  const [showRecommend, setShowRecommend] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [showResult, setShowResult] = useState(false)
  const [sideTab, setSideTab] = useState<SideTab>('chat')
  const [monitor, setMonitor] = useState<{ agentId: string; taskId?: string } | null>(null)
  const [errorMsg, setErrorMsg] = useState('')
  const resultShownFor = useRef<string | null>(null)

  const run = state.run

  const refreshConfig = useCallback(async () => {
    try {
      const [pv, ag] = await Promise.all([api.providers(), api.agents()])
      dispatch({ type: 'config', providers: pv.providers, models: pv.models, agents: ag.agents })
    } catch (e: any) {
      setErrorMsg(`加载配置失败：${e.message}`)
    }
  }, [])

  const refreshRuns = useCallback(async () => {
    try {
      dispatch({ type: 'runs', runs: await api.runs() })
    } catch {
      /* ignore */
    }
  }, [])

  const loadRunEvents = useCallback(async (runId: string) => {
    try {
      const r = await api.run(runId)
      dispatch({ type: 'loadEvents', runId, events: r.events, meta: r.meta })
    } catch (e: any) {
      setErrorMsg(`加载运行失败：${e.message}`)
    }
  }, [])

  useEffect(() => {
    refreshConfig()
    refreshRuns()
  }, [refreshConfig, refreshRuns])

  // 实时事件（单条 WebSocket 连接，同时提供连接状态）
  const connected = useSocket(
    useCallback(
      (ev: RunEvent) => {
        dispatch({ type: 'event', event: ev })
      },
      [dispatch],
    ),
  )

  // WS 断线重连后重拉当前 run 事件，补上断连窗口
  useEffect(() => {
    if (connected && state.runId) loadRunEvents(state.runId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected])

  // 运行结束后刷新历史列表；完成时自动弹出交付物
  useEffect(() => {
    if (!run) return
    if (run.status !== 'running') refreshRuns()
    if (run.status === 'completed' && run.finalResult && resultShownFor.current !== run.id) {
      resultShownFor.current = run.id
      setShowResult(true)
    }
  }, [run?.status, run?.finalResult, run?.id])

  // 阶段切换时自动切右侧面板
  useEffect(() => {
    if (!run) return
    setSideTab(run.phase === 'analyzing' ? 'chat' : run.phase === 'assigning' ? 'assign' : 'agents')
  }, [run?.phase])

  const startRun = async () => {
    if (!task.trim()) return
    setBusy(true)
    setErrorMsg('')
    setMonitor(null)
    try {
      const n = parseInt(agentCount, 10)
      const meta = await api.startRun(task.trim(), Number.isFinite(n) ? n : undefined)
      dispatch({ type: 'openRun', runId: meta.id })
      await loadRunEvents(meta.id)
      refreshRuns()
    } catch (e: any) {
      setErrorMsg(e.message)
    } finally {
      setBusy(false)
    }
  }

  const stopRun = async () => {
    if (!run) return
    try {
      await api.stopRun(run.id)
    } catch (e: any) {
      setErrorMsg(e.message)
    }
  }

  const sendInput = async (
    text: string,
    kind: 'message' | 'approve' | 'reject' | 'assignment',
    assignments?: { packageKey: string; agentId: string; model?: string }[],
  ) => {
    if (!run) return
    setBusy(true)
    try {
      await api.sendInput(run.id, text, kind, assignments)
    } catch (e: any) {
      setErrorMsg(e.message)
    } finally {
      setBusy(false)
    }
  }

  const openHistory = async (id: string) => {
    setMonitor(null)
    await loadRunEvents(id)
    setShowResult(false)
  }

  const showChat = sideTab === 'chat'

  return (
    <div className="h-screen flex flex-col bg-[#0a0f1e] overflow-hidden">
      <TopBar
        task={task}
        setTask={setTask}
        agentCount={agentCount}
        setAgentCount={setAgentCount}
        run={run}
        runs={state.runs}
        connected={connected}
        busy={busy}
        hasResult={!!run?.finalResult}
        onStart={startRun}
        onStop={stopRun}
        onOpenRecommend={() => setShowRecommend(true)}
        onOpenSettings={() => setShowSettings(true)}
        onOpenProviders={() => setShowProviders(true)}
        onOpenAgents={() => setShowAgents(true)}
        onOpenHistory={openHistory}
        onOpenResult={() => setShowResult(true)}
      />

      {errorMsg && (
        <div className="px-4 py-1.5 bg-rose-500/10 border-b border-rose-500/30 text-xs text-rose-300 flex items-center justify-between shrink-0">
          <span>{errorMsg}</span>
          <button onClick={() => setErrorMsg('')} className="text-rose-400 hover:text-rose-200">
            ×
          </button>
        </div>
      )}

      <div className="flex-1 flex min-h-0">
        {/* 左：工作流拓扑图 */}
        <div className="flex-[1.6] min-w-0 p-3 pb-2">
          <div className="h-full w-full border border-slate-800 rounded-xl overflow-hidden bg-[#0c1327]">
            <FlowGraph
              run={run}
              agents={state.agents}
              onOpenAgent={(agentId, taskId) => setMonitor({ agentId, taskId })}
            />
          </div>
        </div>

        {/* 右：需求对话 / 任务分配 / Agent 状态 */}
        <div className="flex-1 min-w-[420px] border-l border-slate-800 flex flex-col min-h-0 bg-[#0b1122]">
          <div className="flex border-b border-slate-800 shrink-0">
            {(
              [
                ['chat', '需求对话'],
                ['assign', '任务分配'],
                ['agents', 'Agent 状态'],
              ] as [SideTab, string][]
            ).map(([k, label]) => (
              <button
                key={k}
                onClick={() => setSideTab(k)}
                className={`px-3.5 py-2 text-xs font-medium border-b-2 transition-colors ${
                  sideTab === k
                    ? 'border-sky-400 text-sky-300'
                    : 'border-transparent text-slate-500 hover:text-slate-300'
                }`}
              >
                {label}
                {k === 'chat' && run?.approval === 'requested' && (
                  <span className="ml-1.5 inline-block w-1.5 h-1.5 rounded-full bg-emerald-400 align-middle blink" />
                )}
                {k === 'assign' && run?.phase === 'assigning' && (
                  <span className="ml-1.5 inline-block w-1.5 h-1.5 rounded-full bg-violet-400 align-middle blink" />
                )}
              </button>
            ))}
          </div>
          <div className="flex-1 min-h-0">
            {run ? (
              showChat ? (
                <ChatPanel run={run} onSend={sendInput} busy={busy} />
              ) : sideTab === 'assign' ? (
                <AssignmentPanel
                  run={run}
                  agents={run.assignmentOptions}
                  providers={state.providers}
                  models={state.models}
                  onConfirm={(assignments) => sendInput('', 'assignment', assignments)}
                  onBack={() => sendInput('（返回修改方案：我想继续调整需求与工作拆解）', 'message')}
                  busy={busy}
                />
              ) : (
                <AgentPanel
                  run={run}
                  agents={state.agents}
                  providers={state.providers}
                  models={state.models}
                  onOpenAgent={(id) => setMonitor({ agentId: id })}
                />
              )
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-slate-600 gap-2 text-sm">
                <div className="text-3xl">💬</div>
                启动运行后，这里展示需求对话、任务分配与 Agent 状态
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 底部：实时消息流 */}
      <div className="h-52 border-t border-slate-800 bg-[#0b1122] shrink-0">
        <EventStream events={run?.events || []} agents={state.agents} />
      </div>

      {showProviders && (
        <ProvidersDialog
          providers={state.providers}
          models={state.models}
          onClose={() => setShowProviders(false)}
          onChanged={refreshConfig}
        />
      )}
      {showAgents && (
        <AgentsDialog
          agents={state.agents}
          providers={state.providers}
          models={state.models}
          onClose={() => setShowAgents(false)}
          onChanged={refreshConfig}
        />
      )}
      {showSettings && <SettingsDialog onClose={() => setShowSettings(false)} />}
      {showRecommend && (
        <RecommendDialog
          agents={state.agents}
          providers={state.providers}
          models={state.models}
          onClose={() => setShowRecommend(false)}
          onChanged={refreshConfig}
        />
      )}
      {showResult && run?.finalResult && <ResultPanel run={run} onClose={() => setShowResult(false)} />}
      {monitor && run && (
        <AgentMonitorDialog
          run={run}
          agents={state.agents}
          providers={state.providers}
          models={state.models}
          agentId={monitor.agentId}
          preferredTaskId={monitor.taskId}
          onClose={() => setMonitor(null)}
        />
      )}
    </div>
  )
}
