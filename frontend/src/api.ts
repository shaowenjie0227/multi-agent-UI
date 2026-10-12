// REST 客户端：走 vite 代理（/api → localhost:3001）

async function req<T>(method: string, url: string, body?: any): Promise<T> {
  const resp = await fetch(url, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!resp.ok) {
    let detail = `${resp.status}`
    try {
      const j = await resp.json()
      detail = j.detail || JSON.stringify(j)
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return resp.json()
}

const GET = <T,>(url: string) => req<T>('GET', url)

export const api = {
  // 配置
  providers: () => GET<{ providers: any[]; models: any[] }>('/api/providers'),
  createProvider: (b: any) => req<any>('POST', '/api/providers', b),
  updateProvider: (id: string, b: any) => req<any>('PUT', `/api/providers/${id}`, b),
  deleteProvider: (id: string) => req<void>('DELETE', `/api/providers/${id}`),
  addModel: (pid: string, b: { name: string; note?: string }) => req<any>('POST', `/api/providers/${pid}/models`, b),
  deleteModel: (pid: string, mid: string) => req<void>('DELETE', `/api/providers/${pid}/models/${mid}`),
  fetchModels: (pid: string) => GET<{ models: string[] }>(`/api/providers/${pid}/fetch-models`),

  agents: () => GET<{ agents: any[] }>('/api/agents'),
  createAgent: (b: any) => req<any>('POST', '/api/agents', b),
  updateAgent: (id: string, b: any) => req<any>('PUT', `/api/agents/${id}`, b),
  deleteAgent: (id: string) => req<void>('DELETE', `/api/agents/${id}`),

  // 运行
  startRun: (task: string, agentCount?: number) =>
    req<any>('POST', '/api/runs', { task, agentCount: agentCount || null }),
  runs: () => GET<any[]>('/api/runs'),
  run: (id: string) => GET<{ meta: any; events: any[] }>(`/api/runs/${id}`),
  sendInput: (id: string, text: string, kind: 'message' | 'approve' | 'reject' | 'assignment', assignments?: any[]) =>
    req<void>('POST', `/api/runs/${id}/input`, { text, kind, assignments: assignments || [] }),
  stopRun: (id: string) => req<void>('POST', `/api/runs/${id}/stop`),

  // 模型推荐
  recommendModel: (task: string, prefer: { cost: string; speed: boolean }) =>
    req<import('./types').RecommendOut>('POST', '/api/recommend-model', { task, prefer }),
  selectorModels: () => GET<{ models: import('./types').KbModel[] }>('/api/selector/models'),

  // 设置（代理 / Clash 集成）
  settings: () => GET<any>('/api/settings'),
  updateSettings: (b: { proxy?: any; clash?: any }) => req<any>('PUT', '/api/settings', b),
  clashSubscription: (url: string) => req<{ nodes: { name: string; type: string; server: string }[] }>('POST', '/api/clash/subscription', { url }),
  clashGroups: () => GET<{ groups: { name: string; now: string; all: string[] }[] }>('/api/clash/groups'),
  clashDelay: (names: string[]) => req<{ results: { name: string; delayMs: number | null }[] }>('POST', '/api/clash/delay', { names }),
  clashSelect: (group: string, name: string) => req<void>('POST', '/api/clash/select', { group, name }),
  clashAutoSelect: (group: string) =>
    req<{ selected: string; delayMs: number; results: { name: string; delayMs: number | null }[] }>('POST', '/api/clash/auto-select', { group, name: '' }),
}
