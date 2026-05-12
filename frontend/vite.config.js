import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': 'http://backend:8000',
      '/ws': { target: 'ws://backend:8000', ws: true },
      '/mcp': { target: 'ws://backend:8000', ws: true },
      '/a2a': 'http://backend:8000'
    }
  }
})
