import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// API calls go to the FastAPI backend; override with VITE_API_TARGET.
const target = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": { target, changeOrigin: true } } },
  preview: { port: 4173, proxy: { "/api": { target, changeOrigin: true } } },
});
