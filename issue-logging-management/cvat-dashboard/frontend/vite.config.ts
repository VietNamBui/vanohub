/// <reference types="vitest" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// Mọi thư viện (node_modules) vào MỘT chunk `vendor`, tách khỏi code ứng dụng.
// CẤM chia vendor thành nhiều chunk (react / antd / @ant-design/icons…): helper CommonJS và
// @ant-design/colors dùng chung tạo phụ thuộc vòng giữa các chunk ⇒ bản build trang trắng
// ("reading 'primary'" / "reading 'version'"), bản dev không lộ. Kiểm bằng `vite preview`.

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target: env.VITE_API_ORIGIN || 'http://127.0.0.1:8010',
          changeOrigin: true,
        },
      },
    },
    test: { environment: 'node', include: ['src/**/*.test.ts'] },
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            return id.includes('node_modules') ? 'vendor' : undefined
          },
        },
      },
    },
  }
})
