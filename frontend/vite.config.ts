import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// 端口可通过环境变量覆盖（dev.sh 会同时传给前后端）
const BACKEND_PORT = process.env.BACKEND_PORT || '3001'
const FRONTEND_PORT = Number(process.env.FRONTEND_PORT || '5173')
const backend = `http://127.0.0.1:${BACKEND_PORT}`

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: FRONTEND_PORT,
    proxy: {
      '/api': backend,
      '/ws': { target: backend.replace('http://', 'ws://'), ws: true },
    },
  },
})
