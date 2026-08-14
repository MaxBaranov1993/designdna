import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// FastAPI uses /static/flow/. Electron loads the same bundle from file:// with relative assets.
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  base: mode === "desktop" ? "./" : "/static/flow/",
  build: {
    outDir: "../app/static/flow",
    emptyOutDir: true,
  },
}));
