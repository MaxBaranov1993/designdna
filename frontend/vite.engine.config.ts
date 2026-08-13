import { defineConfig } from "vite";

// IIFE-бандл TS-движков (frontend/src/engine) для headless-рендера на стороне
// Python: scraper (preview-скриншоты), motion_render (кадры видео), pixel-тесты.
// Бандл восстанавливает window.IRRenderer/GeoEdit/IRHistory/DesignAIFontCatalog.
// Собирается ПОСЛЕ основной сборки (emptyOutDir:false — не тереть app/static/flow).
export default defineConfig({
  build: {
    outDir: "../app/static/flow",
    emptyOutDir: false,
    lib: {
      entry: "src/engine/index.ts",
      name: "DesignAIEngine",
      formats: ["iife"],
      fileName: () => "engine.js",
    },
    minify: false,
  },
});
