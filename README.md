# 多 Agent 协同工作台

配置驱动的多 Agent 协作系统：**供应商 → 模型 → Agent** 三层配置，实时可视化监控面板。
内置软件交付流水线：交互式需求分析（人机对话）→ 开发实现 ⇄ 需求测试（测试不通过自动带方案返工）→ 汇总交付。

## 启动

```bash
./dev.sh          # 首次会自动建 venv / 装 npm 依赖
# 打开 http://localhost:5173
```

手动分步：

```bash
# 后端（:3001）
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn app.main:app --port 3001

# 前端（:5173）
cd frontend && npm install && npm run dev
```

## 使用流程

1. **供应商管理**（顶栏「供应商」）：添加供应商（Base URL + API Key，如 xAI `https://api.x.ai/v1`），手动添加或「拉取模型列表」（如 `grok-4.7`）
2. **Agent 管理**（顶栏「Agent」）：每个 Agent 绑定「某供应商的某模型」或 Mock 模拟；默认 4 角色全绑 Mock，开箱即跑
3. 顶栏输入任务 + **期望 Agent 数**（可留空由分析师判断）启动：
   - **阶段一 · 需求分析（对话闭环）**：分析师出初版方案 + 边界问题 → 对话修订 → 完整方案（含**工作包拆解**：每个包的建议角色、职责、任务、联调方式、依赖）→ 确认门〔满意进入开发〕/〔不满意继续修改〕
   - **阶段二 · 任务分配**：为每个工作包选择执行 **Agent** 与**模型**（可覆盖 Agent 默认绑定，可混搭 Mock/真实模型），也可返回继续修改方案
   - **阶段三 · 执行 ⇄ 联调**：无依赖的工作包**并行执行** → 测试工程师**联调验收** → 不通过则失败项**按工作包精准返工**（红色回环，上限 2 轮）→ 编排者汇总交付
4. 左图为实时拓扑（依赖分级布局 + 返工回环），底部实时消息流，「交付物」查看最终文档，「历史」回放任意运行

## 配置文件

- `backend/data/providers.json` — 供应商与模型
- `backend/data/agents.json` — Agent 角色人设与绑定
- `backend/data/settings.json` — 代理设置 + Clash 外部控制配置
- `backend/data/runs/*.json` — 每次运行的完整事件流（历史回放数据源）

## 设置：本机代理 + Clash Verge 集成

顶栏「设置」对话框：

1. **代理设置**：LLM 调用与订阅拉取的出网方式 —— 不使用代理 / 跟随系统代理 / 自定义本机代理（默认 `127.0.0.1:7897`）。不影响面板与本机后端通信。
2. **Clash 集成**：
   - 填「外部控制」地址（Verge 设置中开启「外部控制」，默认 `http://127.0.0.1:9097`，如有密钥一并填写）→「获取策略组」
   - 粘贴**订阅地址**（支持 Clash YAML 与 Base64 分享链接）→「拉取订阅」解析出节点列表
   - 选择策略组 →「测速」看全部节点延迟，或「**自动选择最快节点**」一键测速并把组切换到最低延迟节点
   - 该选择会通过 External Controller 同步到 Clash Verge 本体，后续 LLM 调用即经所选节点出网

本地开发辅助：`backend/test_clash.py`（解析/测速/切换单测，含 mock controller）、`backend/test_clash_rest.py`（REST 冒烟）、`backend/mock_clash_services.py`（常驻 mock 订阅+控制器，GUI 联调用，端口 19097）。

## 技术栈

FastAPI + WebSocket + openai SDK（OpenAI 兼容协议，一个适配层通吃智谱/xAI/DeepSeek/OpenAI）｜React 18 + Vite + Tailwind v4 + React Flow + react-markdown。前端状态 = 事件重放（纯函数 reducer），历史回放与实时推进共用同一逻辑。
