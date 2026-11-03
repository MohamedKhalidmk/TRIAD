import react from '@vitejs/plugin-react';
import { defineConfig, loadEnv } from 'vite';

// The dev server runs on port 5173. It sends each /api request to the backend at TRIAD_API_URL
// (src/frontend/.env or the shell; default http://127.0.0.1:8000). dev.sh sets it from PORT.
// The build goes to dist/. The backend command "main.py serve" serves dist/.
// The host is 127.0.0.1, as for the backend. With "localhost", macOS gives the IPv6 address ::1 only,
// and http://127.0.0.1:5173 does not connect. A browser also opens http://localhost:5173 on 127.0.0.1.
const FRONTEND_DIR = import.meta.dirname;
const DEFAULT_API_URL = 'http://127.0.0.1:8000';

export default defineConfig(({ mode }) => {
  // The prefix '' gives this file all the values of .env and of the shell. A shell value wins.
  // Only the VITE_ values go into the bundle, so TRIAD_API_URL stays on the dev server.
  const env = loadEnv(mode, FRONTEND_DIR, '');
  const apiUrl = env.TRIAD_API_URL || DEFAULT_API_URL;

  return {
    plugins: [react()],
    envDir: FRONTEND_DIR,
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': {
          target: apiUrl,
          changeOrigin: false,
        },
      },
    },
    preview: {
      host: '127.0.0.1',
      port: 4173,
      strictPort: true,
      proxy: {
        '/api': apiUrl,
      },
    },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
      sourcemap: false,
    },
  };
});
