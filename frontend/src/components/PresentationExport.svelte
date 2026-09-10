<script lang="ts">
  import { api } from "../flow/api";
  import { toast } from "../flow/toast";
  import type { IRObject } from "../flow/types";
  let { snapshot, compact = false }: { snapshot: () => { ir: IRObject | null; width?: number; viewport?: string }; compact?: boolean } = $props();
  type Report = { text: number; shapes: number; images: number; fonts: string[]; width: number; height: number; rasterFallbacks: {path: string; reason: string; text?: string}[] };
  let busy = $state(false), report = $state<Report | null>(null), error = $state("");
  let trigger: HTMLButtonElement | null = $state(null);
  let reportTop = $state(50), reportLeft = $state(12);
  async function run() {
    if (busy) return;
    busy = true; error = ""; report = null;
    try {
      const input = JSON.parse(JSON.stringify(snapshot()));
      if (!input.ir) throw new Error("Нет макета для экспорта");
      const clean = (value: any) => { if (value && typeof value === "object") { delete value.__path; Object.values(value).forEach(clean); } };
      clean(input.ir);
      const result = await api<{filename: string; base64: string; report: Report}>("/api/export/pptx", structuredClone(input));
      if (window.designDNA?.files) {
        const saved = await window.designDNA.files.save(result.filename, result.base64);
        if (!saved.saved) { toast("Сохранение PPTX отменено", "info"); return; }
      } else {
        const bytes = Uint8Array.from(atob(result.base64), c => c.charCodeAt(0));
        const url = URL.createObjectURL(new Blob([bytes], {type: "application/vnd.openxmlformats-officedocument.presentationml.presentation"}));
        const link = document.createElement("a"); link.href = url; link.download = result.filename; link.click();
        setTimeout(() => URL.revokeObjectURL(url), 30000);
      }
      report = result.report;
      if (compact && trigger) {
        const rect = trigger.getBoundingClientRect();
        reportTop = Math.min(rect.bottom + 8, window.innerHeight - 80);
        reportLeft = Math.max(12, Math.min(rect.right - 340, window.innerWidth - 352));
      }
      toast(`PPTX: ${report.text} текстовых блоков, ${report.shapes} фигур, ${report.images} изображений`, "ok");
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      toast("PPTX не сохранён: " + error, "error");
    } finally { busy = false; }
  }
</script>

<div class:compact class="pptx-export nodrag nowheel">
  <button bind:this={trigger} class={compact ? "fe-btn" : "btn-node small"} data-act="export-pptx" disabled={busy} onclick={() => void run()}>{busy ? "Собираю PPTX…" : "PowerPoint (.pptx)"}</button>
  {#if report}
    <details class="pptx-report" style:top={compact ? reportTop + "px" : undefined} style:left={compact ? reportLeft + "px" : undefined}><summary>Последний PPTX: текст {report.text} · фигуры {report.shapes} · изображения {report.images}</summary>
      <p>Один слайд {Math.round(report.width)} × {Math.round(report.height)} px. Исходный IR и ресурсы включены в файл.</p>
      <p>Шрифты: {report.fonts.join(", ") || "нет текста"}. Они должны быть установлены на компьютере получателя.</p>
      {#if report.rasterFallbacks.length}<p>Сложные элементы сохранены растром:</p><ul>{#each report.rasterFallbacks as item}<li>{item.path}: {item.reason}{item.text ? " (включая текст)" : ""}</li>{/each}</ul>{/if}
      <button class={compact ? "fe-btn" : "btn-node small"} data-act="close-pptx-report" onclick={() => report = null}>Скрыть отчёт</button>
    </details>
  {/if}
  {#if error}<p role="alert">{error}</p>{/if}
</div>

<style>
  .pptx-export { padding: 8px 12px; font-size: 11px; }
  .compact { position: relative; padding: 0; }
  .pptx-report { margin-top: 6px; max-width: 360px; }
  .compact .pptx-report { position: fixed; width: min(340px, calc(100vw - 24px)); max-height: 70vh; overflow: auto; z-index: 40; background: hsl(var(--secondary)); color: hsl(var(--foreground)); padding: 12px; border: 1px solid hsl(var(--border)); border-radius: 8px; box-shadow: 0 8px 30px #0005; }
  summary { cursor: pointer; }
  p { margin: 6px 0; } ul { max-height: 160px; overflow: auto; padding-left: 16px; }
</style>
