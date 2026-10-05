import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        // Keep the browser's Host header so the backend's Origin check matches
        changeOrigin: false
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: false
      }
    }
  }
});
