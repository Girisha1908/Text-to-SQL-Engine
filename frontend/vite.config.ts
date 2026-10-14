import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // Local dev: forward /api to the FastAPI server (uvicorn on 8001).
    proxy: { '/api': 'http://127.0.0.1:8001' },
  },
})
