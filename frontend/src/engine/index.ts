/* Engine bundle entry: движки Design IR как ES-модули. В app-сборке импортируются
 * напрямую; для headless-рендера на стороне Python (scraper, motion_render,
 * pixel-тесты) vite.engine.config.ts собирает из этого entry IIFE-бандл
 * app/static/flow/engine.js, который восстанавливает window-глобалы. */
import { IRRenderer } from "./renderer";
import { GeoEdit } from "./geoedit";
import { IRHistory } from "./irhistory";
import { DesignAIFontCatalog } from "./fontCatalog";
import { TimelineEngine, Timeline } from "./timeline";

declare global {
  interface Window {
    IRRenderer: typeof IRRenderer;
    GeoEdit: typeof GeoEdit;
    IRHistory: typeof IRHistory;
    DesignAIFontCatalog: typeof DesignAIFontCatalog;
    TimelineEngine: typeof TimelineEngine;
    Timeline: typeof Timeline;
  }
}

if (typeof window !== "undefined") {
  window.IRRenderer = IRRenderer;
  window.GeoEdit = GeoEdit;
  window.IRHistory = IRHistory;
  window.DesignAIFontCatalog = DesignAIFontCatalog;
  window.TimelineEngine = TimelineEngine;
  window.Timeline = Timeline;
}

export { IRRenderer, GeoEdit, IRHistory, DesignAIFontCatalog, TimelineEngine, Timeline };
