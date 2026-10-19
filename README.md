# 多 Agent 协同工作台

配置驱动的多 Agent 协作系统：**供应商 → 模型 → Agent** 三层配置，实时可视化监控面板。
内置软件交付流水线：交互式需求分析（人机对话）→ 开发实现 ⇄ 需求测试（测试不通过自动带方案返工）→ 汇总交付。

## 启动

```bash
./dev.sh          # 首次会自动建 venv / 装 npm 依赖
# 打开 http://localhost:5173
```

端口被占用时可覆盖（前后端一起生效）：

```bash
BACKEND_PORT=3002 FRONTEND_PORT=5174 ./dev.sh
```

手动分步：

```bash
# 后端（默认 :3001）
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --port 3001

# 前端（默认 :5173）
cd frontend && npm install && npm run dev
```

## 使用流程

1. **供应商管理**（顶栏「供应商」）：添加供应商（Base URL + API Key，如 xAI `https://api.x.ai/v1`），手动添加或「拉取模型列表」（如 `grok-4.7`）
2. **Agent 管理**（顶栏「Agent」）：每个 Agent 绑定「某供应商的某模型」或 Mock 模拟；默认 4 角色全绑 Mock，开箱即跑
3. 顶栏输入任务 + **期望 Agent 数**（可留空由分析师判断）启动：
   - **阶段一 · 需求分析（对话闭环）**：分析师出初版方案 + 边界问题 → 对话修订 → 完整方案（含**工作包拆解**：每个包的建议角色、职责、任务、联调方式、依赖）→ 确认门〔满意进入开发〕/〔不满意继续修改〕
   - **阶段二 · 任务分配**：为每个工作包选择执行 **Agent** 与**模型**（可覆盖 Agent 默认绑定，可混搭 Mock/真实模型），也可返回继续修改方案
   - **阶段三 · 执行 ⇄ 联调**：无依赖的工作包**并行执行** → 测试工程师**联调验收** → 不通过则失败项**按工作包精准返工**（红色回环，上限 2 轮）→ 编排者汇总交付
4. 左图为实时拓扑（依赖分级布局 + 返工回环），底部实时消息流，「交付物」查看最终文档并下载 Markdown，「历史」回放任意运行（可删除记录）

## 配置文件

- `backend/data/providers.json` — 供应商与模型（API Key 只在后端保存，接口回传掩码）
- `backend/data/agents.json` — Agent 角色人设与绑定
- `backend/data/settings.json` — 代理设置 + Clash 外部控制配置
- `backend/data/model_knowledge.json` — 模型推荐知识库；首次启动自动从 `backend/app/seed/` 复制，之后可自由编辑
- `backend/data/runs/{id}.events.jsonl` — 事件流，逐行追加（写一半崩溃只丢最后一行）
- `backend/data/runs/{id}.meta.json` — 运行元数据快照（创建时、状态变更时与每 50 个事件写入）
- 旧版 `backend/data/runs/{id}.json`（meta+events 合并）仍可读取，重新写入时自动迁移为上面的 JSONL 布局
- `backend/data/workspace/<运行 id>/` — **交付文件工作区**：Agent 产出中带 `path=` 的代码块会真正写成文件（可在「设置」里关闭）

## 可靠性设计

- **事件重放**：前端状态由事件流纯函数折叠而来，历史回放与实时推进共用同一逻辑
- **依赖校验前置**：分析师产出的工作包依赖在确认前清洗（自依赖/悬空依赖/环路），修正结果以「拆解校正」事件展示，不会拖到执行期才报错
- **失败隔离**：并行工作包中任一失败会取消同批兄弟任务，避免运行已失败后事件流继续增长
- **重试**：LLM 调用对 429/5xx/连接错误最多重试 3 次（流式已产出内容后不重试，防重复输出）
- **验收门不放水**：联调结论解析失败时标记 `parsed=false` 且不判定通过，交付物里提示人工复核
- **上下文预算**：多轮对话与工作包拼接按预算裁剪（保留首尾），避免长任务把上下文撑爆
- **重启收敛**：服务启动时把磁盘上仍标记 running 的运行收敛为 `interrupted`，历史列表不会出现幽灵"运行中"
- **用量统计**：每次模型调用记录 provider/model/token/耗时，交付物面板展示汇总与按模型明细
- **事件流追加落盘**：事件写 JSONL 逐行追加（约 0.045ms/事件，比原全量重写快 30 倍以上），崩溃最多丢最后一行；损坏行在读取时跳过，不影响其余事件回放
- **交付物可落盘**：工作包输出里的 ` ```python path=src/main.py ` 代码块会被写入 `data/workspace/<runId>/`，交付物面板可浏览/预览/下载这些真实文件；路径被限制在工作区内（拒绝绝对路径、`..`、符号链接逃逸），单文件 200KB 上限
- **工作区受限命令执行**：测试工程师验收前，系统在工作区自动跑白名单命令（有测试跑 `pytest`，否则 `py_compile`，JS 用 `node --check`），结果作为客观依据喂给验收；**机器校验失败时即使模型判通过也强制降级为不通过并触发返工**。限制：仅允许 `python`/`node`、不经 shell、拒绝绝对路径与 `..` 参数、强制超时、输出截断、最小环境变量。⚠️ 这不是强安全沙箱，仅用于本地开发
- **可选鉴权**：设置里填访问令牌后，全部 REST 与 WebSocket 都要求 Bearer token；留空即保持本机免登录
- **代理贯通**：LLM 调用、模型列表拉取、订阅拉取都遵循「设置 → 代理」的 none/system/custom

## 设置：代理 / 工作区 / 访问令牌 / Clash Verge 集成

顶栏「设置」对话框：

0. **访问令牌**：留空 = 不校验（默认，仅本机使用）；填写后所有 `/api/*` 与 `/ws` 都要求 `Authorization: Bearer <token>`（前端会自动带上并保存在 localStorage）。只有 `/api/settings` 保持公开，供前端判断是否已启用鉴权。
1. **交付文件落盘**：开启后，工作包产出中带 `path=` 的代码块会写入 `backend/data/workspace/<runId>/`；关闭则只保留文本报告。
2. **命令执行（联调验收）**：开启后测试工程师验收前会在工作区跑白名单校验命令；可配置超时（默认 30s）与输出上限（默认 8000 字符）。关闭则退回纯文档验收。
3. **代理设置**：LLM 调用、模型列表拉取与订阅拉取的出网方式 —— 不使用代理 / 跟随系统代理 / 自定义本机代理（默认 `127.0.0.1:7897`）。不影响面板与本机后端通信。
4. **Clash 集成**：
   - 填「外部控制」地址（Verge 设置中开启「外部控制」，默认 `http://127.0.0.1:9097`，如有密钥一并填写）→「获取策略组」
   - 粘贴**订阅地址**（支持 Clash YAML 与 Base64 分享链接）→「拉取订阅」解析出节点列表
   - 选择策略组 →「测速」看全部节点延迟，或「**自动选择最快节点**」一键测速并把组切换到最低延迟节点
   - 该选择会通过 External Controller 同步到 Clash Verge 本体，后续 LLM 调用即经所选节点出网

## 测试

```bash
cd backend
.venv/bin/pip install -r requirements.txt   # 含 pytest / pytest-asyncio
.venv/bin/python -m pytest                  # 140 项单元测试（隔离数据目录，不污染 backend/data）
.venv/bin/python e2e_mock.py                # Mock 全流程 E2E（需先启动后端）
.venv/bin/python test_clash.py              # Clash 订阅解析/测速/切换（内置 mock controller）
```

其中 `tests/test_openai_compat.py` 用本地假 OpenAI 兼容服务验证**真实 HTTP 链路**：SSE 流式逐块回调、`reasoning_effort` 透传、不支持流式时自动回退、429/500 重试、已流出内容不重试、usage 上报。

CI（`.github/workflows/ci.yml`）在 push/PR 时跑后端 pytest + 导入自检，以及前端 `tsc -b` + 生产构建。

本地开发辅助：`backend/test_clash_rest.py`（REST 冒烟）、`backend/mock_clash_services.py`（常驻 mock 订阅+控制器，端口 19097，GUI 联调用）。

## 真实 LLM 接入

默认 4 个 Agent 全部绑定 Mock，开箱即跑。接真实模型：

1. 顶栏「供应商」→ 填写 Base URL 与 API Key（如 xAI `https://api.x.ai/v1`、智谱 `https://open.bigmodel.cn/api/paas/v4`、DeepSeek `https://api.deepseek.com/v1`，也可用任意 OpenAI 兼容中转）
2. 「拉取模型列表」或手动添加模型名
3. 顶栏「Agent」→ 把角色的绑定改成该供应商 + 模型；需要推理档位时设置 `effort`
4. 顶栏「设置 → 代理」按需选择出网方式

> 注意：`reasoning_effort` 是 OpenAI 新参数，部分供应商会忽略或报错。若某供应商不兼容，把对应 Agent 的档位保持「默认」即可不下发该参数。

**已用真实模型验证过的行为**（DeepSeek 系，经 OpenAI 兼容中转）：SSE 流式逐块输出、`reasoning_effort` 的 low/medium/high 三档均被接受、token 用量统计、交付文件落盘、工作区 pytest 校验、机器校验失败强制返工。实测案例：模型生成 src-layout 库时第 1 轮 `pytest` 因 `ModuleNotFoundError` 退出码 2，验收被强制判不通过并触发返工，第 3 轮通过；最终产出的库手跑 **183 tests passed**。

## 技术栈

FastAPI + WebSocket + openai SDK（OpenAI 兼容协议，一个适配层通吃智谱/xAI/DeepSeek/OpenAI）｜React 18 + Vite + Tailwind v4 + React Flow + react-markdown。前端状态 = 事件重放（纯函数 reducer），历史回放与实时推进共用同一逻辑。
