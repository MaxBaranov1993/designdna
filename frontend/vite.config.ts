import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Сборку раздаёт FastAPI: статика лежит в app/static/flow/, URL-префикс /static/flow/
export default defineConfig({
  plugins: [react()],
  base: "/static/flow/",
  build: {
    outDir: "../app/static/flow",
    emptyOutDir: true,
  },
});
