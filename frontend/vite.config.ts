import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs on :8000 (python -m bmw_feedback serve); in production
// FastAPI serves the built files from frontend/dist on the same origin.
// API_URL overrides the dev proxy target, e.g. API_URL=http://127.0.0.1:8010 npm run dev
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": process.env.API_URL ?? "http://127.0.0.1:8000" } },
});
