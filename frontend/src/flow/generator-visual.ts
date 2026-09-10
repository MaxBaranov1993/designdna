import { api } from "./api";
import { pullInput } from "./dataflow";
import { imageDataUrl, isImageSource } from "./image-assets";
import type { AssetResult } from "./generator-assets";
import type { FlowNode, FlowEdge, GeneratorNodeData, ReferenceNodeData } from "./types";

export type ReferenceRole = "style" | "composition" | "reproduce";
export type VisualReference = { image: string; role: ReferenceRole; origin: string; conceptOnly?: boolean; notes?: string };
export type ConceptRun = {
  id: string; inputKey: string; startedAt: number; finishedAt?: number; conceptOnly: true;
  status: "running" | "complete" | "failed" | "cancelled"; provider: "codex" | "off";
  prompt?: string; result?: AssetResult; error?: string;
};

export function generatorVisualReference(nodes: FlowNode[], edges: FlowEdge[], node: FlowNode): VisualReference | undefined {
  const value = pullInput(nodes, edges, node, "reference");
  if (!isImageSource(value)) return undefined;
  const edge = edges.find(edge => edge.target === node.id && edge.targetHandle === "reference");
  const source = nodes.find(node => node.id === edge?.source);
  const reference = source?.type === "reference" ? source.data as ReferenceNodeData : undefined;
  const role = (node.data as GeneratorNodeData).referenceRole || reference?.role || "style";
  return { image: value, role, origin: reference?.fileName || String((source?.data as Record<string, unknown> | undefined)?.label || source?.type || "Референс"), notes: (reference?.brief || "").slice(0, 2000) };
}

export function conceptRunPatch(history: ConceptRun[] | undefined, run: ConceptRun): ConceptRun[] {
  const entries = [...(history || [])], index = entries.findIndex(item => item.id === run.id);
  if (index < 0) entries.push(structuredClone(run)); else entries[index] = structuredClone(run);
  return entries.slice(-8);
}

export function settleInterruptedConcepts(history: ConceptRun[] | undefined): ConceptRun[] | undefined {
  return history?.map(run => run.status !== "running" ? run : { ...run, status: "cancelled", finishedAt: Date.now(), error: "Эскиз был прерван" });
}

export async function createVisualConcept(run: ConceptRun, request: {
  brief: string; tokens?: Record<string, unknown>; designSystem?: Record<string, unknown> | null;
}, options: { signal: AbortSignal; check(): void; onChange(run: ConceptRun): void; model?: string; reference?: VisualReference }) {
  const current = structuredClone(run), { signal } = options;
  const check = () => { options.check(); if (signal.aborted) throw new DOMException("Отменено", "AbortError"); };
  const publish = () => { check(); options.onChange(structuredClone(current)); };
  publish();
  const requestId = `concept-${run.id}`;
  const cancel = () => { void window.designDNA?.providers.cancel(requestId).catch(() => {}); };
  signal.addEventListener("abort", cancel, { once: true });
  try {
    if (run.provider !== "codex" || !window.designDNA?.providers.imageRequest) throw new Error("Для эскиза выберите изображения через аккаунт Codex");
    const prepared = await api<{ prompt: string }>("/api/generate/concept/prepare", { ...request,
      referenceNotes: options.reference?.notes || "", referenceRole: options.reference?.role || "style" }, { signal });
    check(); current.prompt = prepared.prompt; publish();
    const referenceImage = options.reference ? await imageDataUrl(options.reference.image) : undefined;
    check();
    const generated = await window.designDNA.providers.imageRequest({ id: requestId, prompt: prepared.prompt,
      ...(options.model ? { model: options.model } : {}), ...(referenceImage ? { referenceImage } : {}) });
    check();
    const stored = await api<{ result: AssetResult }>("/api/generate/concept/store", { image: generated.image }, { signal });
    check(); current.result = stored.result; current.status = "complete";
  } catch (error) {
    check(); current.status = "failed"; current.error = error instanceof Error ? error.message : String(error);
  } finally { signal.removeEventListener("abort", cancel); }
  current.finishedAt = Date.now(); publish();
  return current;
}
