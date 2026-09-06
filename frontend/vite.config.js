import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    proxy: {
      // During dev (including docker), forward API calls to backend.
      // This lets the frontend use relative URLs like "/api/simulate".
      '/api': {
        target: process.env.VITE_BACKEND_URL || 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      },
    },
    watch: {
      // Required for Docker volume-mounted files on Windows / WSL2 / macOS.
      // Chokidar polls instead of relying on inotify which doesn't fire across mounts.
      usePolling: true,
      interval: 300,
    },
    hmr: {
      // Make HMR websocket work when the browser accesses via host (localhost:8080).
      clientPort: 8080,
      overlay: true,
    },
  },
})

