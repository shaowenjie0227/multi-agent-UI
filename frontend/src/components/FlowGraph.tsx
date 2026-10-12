import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
} from '@xyflow/react'
import { Crown, FlaskConical, ListChecks, Code2, Package } from 'lucide-react'
import { useEffect, useMemo } from 'react'
import type { AgentCfg, RunState, TaskNode } from '../types'
import { ROLE_META, StatusText } from './ui'

const NODE_W = 230
const COL_W = NODE_W + 70

const ROLE_ICON: Record<string, any> = {
  analyst: ListChecks,
  developer: Code2,
  tester: FlaskConical,
}

type NodeData = {
  kind: 'orchestrator' | 'task'
  title: string
  role: string
  round?: number
  status?: string
  detail?: string
  agentName: string
  agentId?: string
}

function TaskCard({ data }: { data: NodeData }) {
  const Icon = ROLE_ICON[data.role] || Package
  const waiting = data.status === 'waiting_user'
  const running = data.status === 'running' || data.status === 'working' || data.status === 'thinking'
  const border =
    data.status === 'done'
      ? 'border-emerald-500/60'
      : data.status === 'error'
        ? 'border-rose-500/70'
        : waiting
          ? 'border-sky-400/80 waiting-pulse'
          : running
            ? 'border-amber-400/70'
            : 'border-slate-600/70'
  const glow =
    data.status === 'done'
      ? 'shadow-[0_0_18px_rgba(16,185,129,0.15)]'
      : waiting
        ? 'shadow-[0_0_20px_rgba(56,189,248,0.25)]'
        : running
          ? 'shadow-[0_0_18px_rgba(245,158,11,0.18)]'
          : ''
  return (
    <div
      className={`cursor-pointer hover:brightness-110 bg-[#141c33] border ${border} ${glow} rounded-lg px-3 py-2.5 w-[230px] transition-all duration-300`}
    >
      <Handle type="target" position={Position.Left} className="!bg-slate-500 !w-1.5 !h-1.5 !border-0" />
      <div className="flex items-center gap-1.5 mb-1">
        {Icon && <Icon size={13} className="text-slate-400" />}
        <span className="text-[12px] font-medium text-slate-200 truncate flex-1">{data.title}</span>
        {data.round && data.round > 1 && (
          <span className="px-1 rounded bg-rose-500/20 text-rose-300 text-[10px] border border-rose-500/40">
            R{data.round}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2">
        <span
          className={`px-1.5 py-0.5 rounded text-[10px] border ${ROLE_META[data.role]?.color || ROLE_META.custom.color}`}
        >
          {data.agentName || ROLE_META[data.role]?.label}
        </span>
        <StatusText status={data.status} />
      </div>
      {data.detail && <div className="mt-1 text-[10px] text-slate-500 truncate">{data.detail}</div>}
      <Handle type="source" position={Position.Right} className="!bg-slate-500 !w-1.5 !h-1.5 !border-0" />
    </div>
  )
}

function OrchCard({ data }: { data: NodeData }) {
  const running = data.status === 'working' || data.status === 'thinking'
  return (
    <div
      className={`cursor-pointer hover:brightness-110 bg-gradient-to-b from-violet-950/80 to-[#141c33] border ${
        running ? 'border-amber-400/70' : data.status === 'done' ? 'border-emerald-500/50' : 'border-violet-500/50'
      } rounded-lg px-3 py-2.5 w-[230px] transition-all duration-300`}
    >
      <Handle type="source" position={Position.Bottom} className="!bg-slate-500 !w-1.5 !h-1.5 !border-0" />
      <div className="flex items-center gap-1.5 mb-1">
        <Crown size={13} className="text-violet-300" />
        <span className="text-[12px] font-medium text-slate-100">{data.title}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className={`px-1.5 py-0.5 rounded text-[10px] border ${ROLE_META.orchestrator.color}`}>编排者</span>
        <StatusText status={data.status} />
      </div>
      {data.detail && <div className="mt-1 text-[10px] text-slate-500 truncate">{data.detail}</div>}
    </div>
  )
}

// 必须定义在组件外：组件内每次渲染产生新引用会导致 React Flow 反复重挂节点、测量失效（节点一直 visibility:hidden）
const nodeTypes = { taskCard: TaskCard, orchCard: OrchCard }

type IdKind = { kind: 'pkg' } | { kind: 'test'; round: number } | { kind: 'rework'; round: number }

function classify(id: string, tasks: Record<string, TaskNode>): IdKind {
  let m = id.match(/^test-(\d+)$/)
  if (m) return { kind: 'test', round: parseInt(m[1], 10) }
  m = id.match(/^(.+)-r(\d+)$/)
  if (m && tasks[m[1]]) return { kind: 'rework', round: parseInt(m[2], 10) }
  m = id.match(/^dev-(\d+)$/)
  if (m && parseInt(m[1], 10) > 1 && tasks['dev-1']) return { kind: 'rework', round: parseInt(m[1], 10) }
  return { kind: 'pkg' }
}

function FlowGraphInner({ run, agents, onOpenAgent }: { run: RunState | null; agents: AgentCfg[]; onOpenAgent: (agentId: string, taskId?: string) => void }) {
  const rf = useReactFlow()

  const { nodes, edges } = useMemo(() => {
    const nodes: Node[] = []
    const edges: Edge[] = []
    if (!run) return { nodes, edges }

    const agentName = (id?: string) => agents.find((a) => a.id === id)?.name || ''
    const agentDetail = (id?: string) => (id ? run.agents[id]?.detail : undefined)
    const taskIds = run.taskOrder.filter((id) => id !== 'req' && run.tasks[id])
    const infos = taskIds.map((id) => ({ id, t: run.tasks[id], c: classify(id, run.tasks) }))

    // ---- 列布局：工作包按依赖最长链分级；联调/返工按轮次排在其后
    const levelOf: Record<string, number> = {}
    for (const x of infos) levelOf[x.id] = x.c.kind === 'pkg' ? 0 : x.c.kind === 'test' ? 1 : 2
    const isPkg = (id: string) => infos.find((x) => x.id === id)?.c.kind === 'pkg'
    for (let iter = 0; iter < infos.length + 1; iter++) {
      for (const x of infos) {
        if (x.c.kind !== 'pkg') continue
        for (const d of x.t.dependsOn || []) {
          if (levelOf[d] !== undefined && isPkg(d)) levelOf[x.id] = Math.max(levelOf[x.id], levelOf[d] + 1)
        }
      }
    }
    const pkgLevels = infos.filter((x) => x.c.kind === 'pkg').map((x) => levelOf[x.id])
    const maxPkg = pkgLevels.length ? Math.max(...pkgLevels) : 0
    for (const x of infos) {
      if (x.c.kind === 'test') levelOf[x.id] = maxPkg + 2 * x.c.round - 1
      if (x.c.kind === 'rework') levelOf[x.id] = maxPkg + 2 * x.c.round - 2
    }

    const occupied: Record<number, number> = {}
    const place = (id: string, x: number) => {
      const col = Math.round(x / COL_W)
      const idx = occupied[col] || 0
      occupied[col] = idx + 1
      return { x, y: 60 + idx * 195 }
    }

    // 需求分析节点（列 -1）
    const reqTask = run.tasks['req']
    if (reqTask) {
      nodes.push({
        id: 'req',
        type: 'taskCard',
        position: { x: -COL_W, y: 60 },
        data: {
          kind: 'task',
          title: reqTask.title || '需求分析',
          role: 'analyst',
          status: run.agents[reqTask.agentId || '']?.status || (reqTask.status === 'done' ? 'done' : reqTask.status),
          detail: agentDetail(reqTask.agentId),
          agentName: agentName(reqTask.agentId) || '需求分析师',
          agentId: reqTask.agentId,
        } as NodeData,
      })
    }

    // 任务节点
    for (const x of infos) {
      const pos = place(x.id, levelOf[x.id] * COL_W)
      nodes.push({
        id: x.id,
        type: 'taskCard',
        position: pos,
        data: {
          kind: 'task',
          title: x.t.title,
          role: x.t.role,
          round: x.c.kind === 'test' ? x.c.round : x.c.kind === 'rework' ? x.c.round : x.t.round,
          status: x.t.status,
          detail: x.t.status === 'done' && x.t.output ? '已产出 · 点击查看' : undefined,
          agentName: agentName(x.t.agentId) || ROLE_META[x.t.role]?.label || '',
          agentId: x.t.agentId,
        } as NodeData,
      })
    }

    // 编排者节点（悬于需求分析上方）
    const orch = agents.find((a) => a.role === 'orchestrator')
    nodes.push({
      id: 'orchestrator',
      type: 'orchCard',
      position: { x: -COL_W, y: -130 },
      data: {
        kind: 'orchestrator',
        title: orch?.name || '编排者',
        role: 'orchestrator',
        status: orch ? run.agents[orch.id]?.status : undefined,
        detail: orch ? agentDetail(orch.id) : undefined,
        agentName: orch?.name || '',
        agentId: orch?.id,
      } as NodeData,
    })

    const baseEdge = (id: string, source: string, target: string, label?: string, animated?: boolean): Edge => ({
      id,
      source,
      target,
      animated: !!animated,
      label,
      labelStyle: { fill: '#94a3b8', fontSize: 10 },
      labelBgStyle: { fill: '#141c33' },
      style: { stroke: '#475569' },
      markerEnd: { type: MarkerType.ArrowClosed, color: '#475569' },
    })

    if (reqTask) {
      edges.push(baseEdge('e-orch-req', 'orchestrator', 'req', undefined, reqTask.status !== 'done'))
      // 需求方案 → 各无依赖工作包
      for (const x of infos) {
        if (x.c.kind !== 'pkg') continue
        const hasPkgDep = (x.t.dependsOn || []).some((d) => isPkg(d) && run.tasks[d])
        if (!hasPkgDep) {
          edges.push(baseEdge(`e-req-${x.id}`, 'req', x.id, '需求方案', x.t.status === 'running'))
        }
      }
    }

    // 依赖边
    for (const x of infos) {
      for (const d of x.t.dependsOn || []) {
        if (!run.tasks[d] || d === 'req') continue
        const label = x.c.kind === 'test' ? (x.c.round > 1 ? '再次提交' : '提交联调') : undefined
        edges.push(baseEdge(`e-${d}-${x.id}`, d, x.id, label, x.t.status === 'running' || run.tasks[d]?.status === 'running'))
      }
    }

    // 返工回环边（红色虚线）
    for (const h of run.handoffs) {
      edges.push({
        id: `e-rework-${h.fromTask}-${h.toTask}`,
        source: h.fromTask,
        target: h.toTask,
        animated: true,
        label: '不通过 · 返工',
        labelStyle: { fill: '#fda4af', fontSize: 10 },
        labelBgStyle: { fill: '#141c33' },
        style: { stroke: '#f43f5e', strokeDasharray: '6 4' },
        markerEnd: { type: MarkerType.ArrowClosed, color: '#f43f5e' },
      })
    }

    return { nodes, edges }
  }, [run, agents])

  // 节点集合变化（含返工轮新节点）后自动适配视野
  const nodeCount = nodes.length
  useEffect(() => {
    if (nodeCount > 0) {
      const t = setTimeout(() => rf.fitView({ padding: 0.25, duration: 400 }), 80)
      return () => clearTimeout(t)
    }
  }, [nodeCount, rf])

  return (
    <div className="h-full w-full">
      {run ? (
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.25 }}
          minZoom={0.3}
          nodesConnectable={false}
          onNodeClick={(_, node) => {
            const d = node.data as NodeData
            if (d.agentId) onOpenAgent(d.agentId, node.id !== 'orchestrator' ? node.id : undefined)
          }}
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#1e293b" gap={18} />
          <Controls
            className="!bg-[#141c33] !border-slate-700 !rounded-md [&>button]:!bg-[#141c33] [&>button]:!border-slate-700 [&>button]:!fill-slate-300"
            showInteractive={false}
          />
        </ReactFlow>
      ) : (
        <div className="h-full flex flex-col items-center justify-center text-slate-600 gap-2">
          <div className="text-4xl">🤖</div>
          <div className="text-sm">输入任务并启动，即可观看 Agent 协同过程</div>
        </div>
      )}
    </div>
  )
}

export default function FlowGraph(props: {
  run: RunState | null
  agents: AgentCfg[]
  onOpenAgent: (agentId: string, taskId?: string) => void
}) {
  return (
    <ReactFlowProvider>
      <FlowGraphInner {...props} />
    </ReactFlowProvider>
  )
}
