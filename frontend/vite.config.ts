import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

// Сборку раздаёт FastAPI: статика лежит в app/static/flow/, URL-префикс /static/flow/
export default defineConfig({
  plugins: [react()],
  base: "/static/flow/",
  build: {
    outDir: "../app/static/flow",
    emptyOutDir: true,
    rollupOptions: {
      input: {
        app: resolve(__dirname, "index.html"),
        quality: resolve(__dirname, "quality-render.html"),
      },
    },
  },
});
