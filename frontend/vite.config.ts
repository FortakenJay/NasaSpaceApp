import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev: proxy /api at the API service. `vercel dev` injects MARSWALK_API. A second local copy can
// set MARSWALK_API and MARSWALK_WEB_PORT (e.g. API on :8001, app on :5174). Otherwise this is
// `marswalk serve` on :8000. The built site does not use the proxy: the browser calls /api on the
// same host, and vercel.json sends that path to the API service.
const api = process.env.MARSWALK_API ?? 'http://127.0.0.1:8000';
const port = Number(process.env.MARSWALK_WEB_PORT ?? 5173);

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port,
    strictPort: true,
    proxy: { '/api': api },
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    proxy: { '/api': api },
  },
  build: { outDir: 'dist', sourcemap: true },
});
