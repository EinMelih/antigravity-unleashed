import path from "node:path";
import { fileURLToPath } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const frontendDirectory = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig(({ command }) => ({
  base: command === "build" ? "/dashboard/react/" : "/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(frontendDirectory, "src"),
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/docs": "http://127.0.0.1:8000",
      "/health": "http://127.0.0.1:8000",
    },
  },
  build: {
    outDir: path.resolve(frontendDirectory, "../dashboard/react"),
    emptyOutDir: true,
    sourcemap: false,
  },
}));
