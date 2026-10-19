#!/bin/bash
# 一键启动：后端 uvicorn + 前端 Vite
# 端口可用环境变量覆盖：BACKEND_PORT / FRONTEND_PORT（默认 3001 / 5173）
set -e
cd "$(dirname "$0")"

BACKEND_PORT="${BACKEND_PORT:-3001}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
export BACKEND_PORT FRONTEND_PORT

PY=backend/.venv/bin/python
if [ ! -x "$PY" ]; then
  echo "[dev] 创建 Python 虚拟环境…"
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn -r backend/requirements.txt
fi

if [ ! -d frontend/node_modules ]; then
  echo "[dev] 安装前端依赖…"
  (cd frontend && npm install --no-audit --no-fund)
fi

# 端口被占用时直接给出提示，避免 uvicorn 启动失败后前端 502 一片
if lsof -iTCP:"$BACKEND_PORT" -sTCP:LISTEN -n -P >/dev/null 2>&1; then
  echo "[dev] 端口 $BACKEND_PORT 已被占用，请先停掉占用进程，或用 BACKEND_PORT=其它端口 ./dev.sh"
  lsof -iTCP:"$BACKEND_PORT" -sTCP:LISTEN -n -P | head -3
  exit 1
fi

cleanup() { kill $BACK_PID $FRONT_PID 2>/dev/null; wait 2>/dev/null; }
trap cleanup EXIT INT TERM

echo "[dev] 启动后端 http://localhost:$BACKEND_PORT"
(cd backend && .venv/bin/python -m uvicorn app.main:app --port "$BACKEND_PORT") &
BACK_PID=$!

echo "[dev] 启动前端 http://localhost:$FRONTEND_PORT"
(cd frontend && npm run dev) &
FRONT_PID=$!

echo "[dev] 就绪后打开 http://localhost:$FRONTEND_PORT"
wait
