import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The dev server runs on port 5173. It sends each /api request to the backend on port 8000.
// The build goes to dist/. The backend command "main.py serve" serves dist/.
// The host is 127.0.0.1, as for the backend. With "localhost", macOS gives the IPv6 address ::1 only,
// and http://127.0.0.1:5173 does not connect. A browser also opens http://localhost:5173 on 127.0.0.1.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: false,
  },
});
