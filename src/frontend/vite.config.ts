import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The dev server runs on port 5173. It sends each /api request to the backend on port 8000.
// The build goes to dist/. The backend command "main.py serve" serves dist/.
export default defineConfig({
  plugins: [react()],
  server: {
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
