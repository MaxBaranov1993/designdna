import { sveltekit } from "@sveltejs/kit/vite";
import { defineConfig } from "vite";

// FastAPI uses /static/flow/. Electron loads the same build from file:// —
// относительные пути assets обеспечивает kit.paths.relative (svelte.config.js).
export default defineConfig({
  plugins: [sveltekit()],
});
