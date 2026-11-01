import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// In dev, the Vite server proxies /api to the FastAPI backend. Ports are not the usual
// 5173/8000 so this runs alongside other projects; FT_API_PORT overrides the backend port.
const apiPort = process.env.FT_API_PORT || '8010';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: { __API_PORT__: JSON.stringify(apiPort) },
  server: {
    port: 5180,
    strictPort: true, // fail loudly rather than drift onto another app's port
    proxy: { '/api': `http://127.0.0.1:${apiPort}` },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test-setup.js',
  },
});
