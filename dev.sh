#!/bin/bash
# 一键启动：后端 uvicorn :3001 + 前端 Vite :5173
set -e
cd "$(dirname "$0")"

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

cleanup() { kill $BACK_PID $FRONT_PID 2>/dev/null; wait 2>/dev/null; }
trap cleanup EXIT INT TERM

echo "[dev] 启动后端 http://localhost:3001"
(cd backend && .venv/bin/python -m uvicorn app.main:app --port 3001) &
BACK_PID=$!

echo "[dev] 启动前端 http://localhost:5173"
(cd frontend && npm run dev) &
FRONT_PID=$!

echo "[dev] 就绪后打开 http://localhost:5173"
wait
