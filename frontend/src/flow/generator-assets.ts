import { api } from "./api";
import { imageDataUrl } from "./image-assets";
import type { IRObject } from "./types";

export type AssetResult = { src: string; sha256: string; width: number; height: number; format: string; transparent: boolean };
export type AssetSlot = {
  id: string; variant: number; path: (string | number)[]; targetHash: string; subject: string; prompt: string;
  width: number; height: number; requiresAlpha: boolean; sourceKey?: string;
  referenceAssetId?: string; forbiddenImageHashes?: string[];
  operation?: 'fill' | 'replace';
  status: "planned" | "running" | "complete" | "failed"; attempts: number; error?: string; result?: AssetResult;
};
export type AssetPlan = { schemaVersion: "design-assets/1.0"; inputHash: string; context: Record<string, unknown>; slots: AssetSlot[] };
export type AssetRun = {
  id: string; inputKey: string; pageId: string; startedAt: number; finishedAt?: number;
  generationStartedAt?: number;
  provider: "codex" | "off"; model?: string; status: "running" | "complete" | "partial" | "cancelled";
  plan: AssetPlan; events: { at: number; slotId: string; status: AssetSlot["status"]; error?: string }[];
  quality?: (import("./api").QualityPassResp["resourceEvidence"] | null)[];
};
type Scope = { check(): void };

export function hasImagePrompts(value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  if (!Array.isArray(value)) {
    const node = value as Record<string, unknown>;
    if (typeof node.imagePrompt === "string" && node.imagePrompt.trim() && !node.src) return true;
  }
  return Object.values(value).some(hasImagePrompts);
}

export function effectiveAssetProvider(mode: string | undefined, provider: string): "codex" | "off" {
  if (mode === "off") return "off";
  if (mode === "codex") return "codex";
  return provider === "claude" ? "off" : "codex";
}

export function assetRunPatch(history: AssetRun[] | undefined, run: AssetRun): AssetRun[] {
  const entries = [...(history || [])];
  const index = entries.findIndex(item => item.id === run.id);
  const snapshot = structuredClone(run);
  if (index < 0) entries.push(snapshot); else entries[index] = snapshot;
  return entries.slice(-8);
}

export function settleInterruptedAssets(history: AssetRun[] | undefined): AssetRun[] | undefined {
  const last = history?.at(-1);
  if (!last || last.status !== "running") return history;
  const run = structuredClone(last);
  run.status = "cancelled"; run.finishedAt = Date.now();
  for (const slot of run.plan.slots) if (slot.status === "running") {
    slot.status = "failed"; slot.error = "Создание остановлено; готовые изображения сохранены";
  }
  return assetRunPatch(history, run);
}

export async function reconcileAssets(variants: IRObject[], run: AssetRun, signal: AbortSignal, scope: Scope) {
  const output = [...variants];
  for (let index = 0; index < output.length; index++) {
    const slots = run.plan.slots.filter(slot => slot.variant === index && slot.status === "complete");
    if (!slots.length) continue;
    const result = await api<{ ir: IRObject; missing: string[] }>("/api/generate/assets/reconcile", { ir: output[index], slots }, { signal });
    scope.check();
    if (signal.aborted) throw new DOMException("Отменено", "AbortError");
    output[index] = result.ir;
    for (const id of result.missing) {
      const slot = run.plan.slots.find(slot => slot.id === id)!;
      slot.status = "failed";
      slot.error = "Изображение отсутствует или изменилось после проверки";
    }
  }
  return output;
}

/** Each committed slot is immediately saved with the node. Failed slots never discard successful peers. */
export async function executeAssetPlan(variants: IRObject[], run: AssetRun, options: {
  signal: AbortSignal; scope: Scope; onChange(variants: IRObject[], run: AssetRun): void;
  onStage(label: string): void; onlySlot?: string;
}): Promise<{ variants: IRObject[]; run: AssetRun }> {
  const { signal, scope, onChange, onStage } = options;
  let output = structuredClone(variants);
  const current = structuredClone(run);
  const check = () => { scope.check(); if (signal.aborted) throw new DOMException("Отменено", "AbortError"); };
  const publish = () => { check(); onChange(structuredClone(output), structuredClone(current)); };
  current.status = "running";
  delete current.finishedAt;
  const targets = current.plan.slots.filter(slot => slot.status !== "complete" && (!options.onlySlot || slot.id === options.onlySlot));
  try {
    for (let index = 0; index < targets.length; index++) {
      check();
      const slot = targets[index];
      slot.status = "running"; slot.attempts++; delete slot.error;
      current.events.push({ at: Date.now(), slotId: slot.id, status: "running" });
      onStage(`Изображение ${index + 1}/${targets.length}: ${slot.subject.slice(0, 80)}`);
      publish();
      const requestId = `asset-${Date.now()}-${Math.random().toString(36).slice(2, 12)}`;
      const cancel = () => { void window.designDNA?.providers.cancel(requestId).catch(() => {}); };
      signal.addEventListener("abort", cancel, { once: true });
      try {
        if (current.provider !== "codex") throw new Error("Выберите GPT Image через Codex в параметрах изображений ноды");
        const provider = window.designDNA?.providers;
        if (!provider?.imageRequest) throw new Error("Для изображений подключите Codex в десктопном приложении");
        check();
        const anchor = current.plan.context.coherentSeries === true
          ? current.plan.slots.find(item => item.variant === slot.variant && item.id !== slot.id && item.status === "complete" && item.result)
          : undefined;
        const referenceImage = anchor?.result ? await imageDataUrl(anchor.result.src)
          : typeof current.plan.context.referenceImage === 'string' ? await imageDataUrl(current.plan.context.referenceImage) : undefined;
        check();
        if (anchor) slot.referenceAssetId = anchor.id; else delete slot.referenceAssetId;
        const generated = await provider.imageRequest({ id: requestId, prompt: slot.prompt,
          ...(current.model ? { model: current.model } : {}), ...(referenceImage ? { referenceImage } : {}) });
        check();
        const applied = await api<{ ir: IRObject; result: AssetResult }>("/api/generate/assets/apply", {
          ir: output[slot.variant], slot, image: generated.image,
        }, { signal });
        check();
        output[slot.variant] = applied.ir;
        slot.result = applied.result;
        slot.status = "complete";
        output = await reconcileAssets(output, current, signal, scope);
        check();
      } catch (error) {
        check();
        slot.status = "failed";
        slot.error = error instanceof Error ? error.message : String(error);
      } finally {
        signal.removeEventListener("abort", cancel);
      }
      current.events.push({ at: Date.now(), slotId: slot.id, status: slot.status, ...(slot.error ? { error: slot.error } : {}) });
      publish();
    }
    current.status = current.plan.slots.every(slot => slot.status === "complete") ? "complete" : "partial";
    current.finishedAt = Date.now();
    publish();
    return { variants: output, run: current };
  } catch (error) {
    // The caller owns stale-page protection. A cancelled run keeps its last committed snapshot.
    current.status = "cancelled";
    current.finishedAt = Date.now();
    throw error;
  }
}
