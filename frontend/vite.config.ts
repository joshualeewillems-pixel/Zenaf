import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import svgr from 'vite-plugin-svgr'

export default defineConfig({
  plugins: [react(), svgr()],
  server: {
    // Match API_BASE (127.0.0.1:8010) so session cookies work for cross-port fetches.
    // localhost:5173 is a different host than 127.0.0.1 → cookies would not attach to API_BASE.
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    // Proxy Vision Execution API so the browser uses same origin (no CORS). Backend must run on 8010.
    proxy: {
      // Long runs (local Ollama / multi-seat council). http-proxy default proxyTimeout is ~120s.
      '/run': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
        timeout: 1_800_000,
        proxyTimeout: 1_800_000,
      },
      '/auth': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
      },
      '/vision-execution': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
      },
      '/settings': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
      },
      '/studio/': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
      },
      // Transcript sorter (Content tab footer); backend prefix /transcripts (see transcript_routes).
      '/transcripts': {
        target: 'http://127.0.0.1:8010',
        changeOrigin: true,
      },
    },
  },
})
