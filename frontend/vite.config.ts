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
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            { name: 'vendor-react', test: /node_modules[\\/](react|react-dom|react-router|scheduler)[\\/]/, priority: 30 },
            { name: 'vendor-antd-icons', test: /node_modules[\\/]@ant-design[\\/]icons/, priority: 25 },
            { name: 'vendor-rc', test: /node_modules[\\/](@rc-component|rc-|@ant-design[\\/]cssinjs)/, priority: 25 },
            { name: 'vendor-antd-data', test: /node_modules[\\/]antd[\\/]es[\\/](table|form|select|modal|drawer|descriptions|pagination|input|date-picker)/, priority: 22 },
            { name: 'vendor-antd-core', test: /node_modules[\\/]antd[\\/]/, priority: 20 },
            { name: 'vendor-aria', test: /node_modules[\\/](react-aria|react-aria-components|@react-aria|@react-stately|@internationalized)/, priority: 20 },
            { name: 'vendor-icons', test: /node_modules[\\/]@untitledui[\\/]icons/, priority: 20 },
          ],
        },
      },
    },
  },
})
