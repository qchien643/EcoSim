import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:5000',
        changeOrigin: true,
        timeout: 600000,      // 10 min — connection timeout
        proxyTimeout: 600000, // 10 min — wait for backend response (LLM calls take minutes)
      },
    },
  },
})
