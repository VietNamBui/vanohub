import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // "@/components/..." → src/components/... (component Untitled UI import theo kiểu này)
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
})
