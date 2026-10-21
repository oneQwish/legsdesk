import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// В разработке API проксируется на uvicorn (порт 8000), cookie-сессия работает как в бою (один origin)
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
});
