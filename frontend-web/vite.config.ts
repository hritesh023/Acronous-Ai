import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '', '')
  const apiUrl = env.VITE_API_URL || ''

  return {
    plugins: [react()],
    base: '',
    server: {
      port: 5173,
      host: true,
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        }
      }
    },
    build: {
      target: 'ES2020',
      outDir: 'dist',
      minify: 'esbuild',
    },
    esbuild: {
      logOverride: { 'this-is-undefined-in-esm': 'silent' }
    }
  }
})
