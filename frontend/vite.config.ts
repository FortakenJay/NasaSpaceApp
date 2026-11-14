import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev: the FastAPI backend runs on :8000 (`python -m marswalk serve`); /api is proxied to it.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  build: { outDir: 'dist', sourcemap: true },
});
