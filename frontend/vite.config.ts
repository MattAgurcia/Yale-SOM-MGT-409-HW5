import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The desk calls the FastAPI backend directly at http://localhost:8000 (see
// src/api.ts); the backend's CORS settings allow this dev server's origin.
// `npm run dev` serves on http://localhost:5173 and opens it in the browser.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    open: true,
  },
})
