/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Backend base URL for the dev-server proxy only. The production build talks
// to whatever VITE_BACKEND_URL is baked in at build time (see src/api/client.ts) --
// this proxy exists purely so `npm run dev` never needs backend CORS headers
// added (backend/api/main.py is out of scope for F1). The browser only ever
// talks to the Vite origin; Vite forwards `/api/*` server-side.
const BACKEND_URL = process.env.VITE_BACKEND_URL ?? 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: BACKEND_URL,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setupTests.ts'],
    css: true,
  },
})
