import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const here = path.dirname(fileURLToPath(import.meta.url))

const apiTarget = process.env.VITE_API_TARGET || 'http://localhost:8000'
const wsTarget = process.env.VITE_WS_TARGET || 'ws://localhost:8000'

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // Tests live in ../tests/frontend, outside the Vite root; only test mode may
  // serve files from the repo root.
  test: {
    environment: 'jsdom',
    include: ['../tests/frontend/**/*.test.{js,jsx}'],
    globals: false,
    // Test files sit outside frontend/, so bare imports they use must be
    // pointed back at this package's node_modules.
    alias: {
      react: path.resolve(here, 'node_modules/react'),
      'react-dom': path.resolve(here, 'node_modules/react-dom'),
      '@testing-library/react': path.resolve(here, 'node_modules/@testing-library/react'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    ...(mode === 'test' ? { fs: { allow: ['..'] } } : {}),
    proxy: {
      '/api': apiTarget,
      '/ws': { target: wsTarget, ws: true },
      '/mcp': { target: wsTarget, ws: true },
      '/a2a': apiTarget
    }
  }
}))
