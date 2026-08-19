import adapter from "@sveltejs/adapter-static";
import { vitePreprocess } from "@sveltejs/vite-plugin-svelte";

// SPA-режим: FastAPI отдаёт /flow из app/static/flow, Electron грузит тот же
// билд с file:// — поэтому assets только относительные (paths.relative).
// engine.js (IIFE) собирается ПОСЛЕ этой сборки (vite.engine.config.ts),
// т.к. adapter-static чистит каталог pages перед записью.
export default {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({
      pages: "../app/static/flow",
      assets: "../app/static/flow",
      fallback: "200.html",
      precompress: false,
    }),
    paths: { relative: true },
  },
};
