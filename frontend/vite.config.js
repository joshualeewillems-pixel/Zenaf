import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5173,
        strictPort: true,
        // Proxy Vision Execution API so the browser uses same origin (no CORS). Backend must run on 8010.
        proxy: {
            // Long runs (local Ollama / multi-seat council). http-proxy default proxyTimeout is ~120s.
            '/run': {
                target: 'http://127.0.0.1:8010',
                changeOrigin: true,
                timeout: 1800000,
                proxyTimeout: 1800000,
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
        },
    },
});
