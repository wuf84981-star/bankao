import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // 开发期临时传达室：/api 开头的请求转给本机 8000 后端
  // （与生产 Nginx 大门同一职责，只是临时工）
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
