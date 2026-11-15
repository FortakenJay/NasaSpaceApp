import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev: the FastAPI backend runs on :8000 (`python -m marswalk serve`); /api is proxied to it.
// MARSWALK_API and MARSWALK_WEB_PORT run a second copy side by side (e.g. API on :8001, app on :5174).
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
  build: { outDir: 'dist', sourcemap: true },
});
