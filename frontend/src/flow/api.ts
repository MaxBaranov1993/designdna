import type { IRObject, ParserSourceEnvelope, SourceArtifact, SourceViewport } from "./types";

export type ApiChatMessage = { role: "system" | "user" | "assistant" | "tool"; content: string };

/* Зеркало api() (nodes.js:61-71): JSON-вызов к бэкенду, Error с data.detail при !ok */
export async function api<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  let data: Record<string, unknown> = {};
  try {
    data = await resp.json();
  } catch {
    /* пустой/не-JSON ответ */
  }
  if (!resp.ok) throw new Error(String(data.detail || "HTTP " + resp.status));
  return data as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  const resp = await fetch(path, { method: "GET" });
  let data: Record<string, unknown> = {};
  try {
    data = await resp.json();
  } catch {
    /* empty/non-JSON response */
  }
  if (!resp.ok) throw new Error(String(data.detail || "HTTP " + resp.status));
  return data as T;
}

/* Формы ответов бэкенда — по server.py и контрактам docs/NODES.md */
export type GenerateResp = {
  variants?: IRObject[];
  errors?: string[];
  qa?: { index: number; fixed: number; violations: string[] }[];
  design?: { type: string; label: string };
  prompts?: Array<{ messages: ApiChatMessage[] }>;
  designSystem?: Record<string, unknown>;
};
export type MixResp = { ir?: IRObject | null };
export type ReproduceResp = {
  ir?: IRObject | null;
  html?: string;
  diff?: { overall_pct?: number; mean_rgb?: number[]; error?: string };
  colors?: { colors?: Record<string, { hex: string; pixels: number }> };
  repro_png?: string;
  icons_count?: number;
  cached?: boolean;
  provider_used?: string;
  parserContract?: ParserSourceEnvelope;
};
/* BlockParse/Reskin (решение владельца 11, server.py /api/block-parse, /api/reskin):
 * ошибка отдельного блока — в его записи (error), остальные работают */
export type BlockParseBlockResp = {
  name: string;
  label?: string;
  kind?: string;
  selector: string;
  ir?: IRObject;
  error?: string;
  cached?: boolean;
  source?: "dom" | "llm" | "vision";
  layers?: number;
  size?: { width?: number; height?: number };
  preview?: string;
  previews?: Partial<Record<SourceViewport, string>>;
  sizes?: Partial<Record<SourceViewport, { width?: number; height?: number }>>;
  layersByViewport?: Partial<Record<SourceViewport, number>>;
  editableLayersByViewport?: Partial<Record<SourceViewport, number>>;
  componentBoundariesByViewport?: Partial<Record<SourceViewport, number>>;
  paintCoverage?: Partial<Record<SourceViewport, number>>;
  p95LayoutError?: Partial<Record<SourceViewport, number | null>>;
  coverage?: Partial<Record<SourceViewport, number>>;
  fidelity?: Partial<Record<SourceViewport, number>>;
  warnings?: string[];
  repeat?: { count?: number; kind?: string } | null;
  parserContract?: ParserSourceEnvelope;
  /** Отчёт harness: по нему судится публикуемость и работает AI-починка. */
  fidelityReport?: {
    gate?: { passed?: boolean; reasons?: string[] };
    viewports?: Record<string, Record<string, unknown>>;
    components?: Record<string, Record<string, unknown>>;
  } | null;
  /** Ключ кэша с уликами захвата: нужен серверу для перезамера после починки. */
  evidenceKey?: string;
};
export type BlockParseResp = {
  url: string;
  blocks: BlockParseBlockResp[];
  tokens: Record<string, unknown> | null;
  cached?: boolean;
  authenticated?: boolean;
  sourceArtifact?: SourceArtifact;
  authWarning?: string;
  /** Чего не решил детерминированный разбор — вход опционального AI-уточнения. */
  ambiguities?: Array<{ type: string; block?: string; reason?: string; [key: string]: unknown }>;
  diagnostics?: {
    pipelineVersion?: string;
    timingsMs?: Record<string, number>;
  };
};
export type BlockParseJobResp = {
  jobId: string;
  status: "queued" | "running" | "complete" | "error";
  progress: number;
  stage: string;
  stageLabel: string;
  timingsMs?: Record<string, number>;
  result?: BlockParseResp;
  error?: string;
};
export type ReskinResp = { ir?: IRObject | null; log?: string[]; designSystem?: Record<string, unknown> };
export type QualityPassResp = {
  ir?: IRObject | null;
  passed?: boolean;
  min_score?: number;
  scorecard?: { score?: number; verdict?: string; summary?: string; issues?: Array<{ severity?: string; problem?: string }> };
  initial_scorecard?: { score?: number };
  deterministic?: { before?: unknown[]; after?: unknown[] };
  repair?: { attempted?: boolean; applied?: boolean; error?: string | null };
  pending?: {
    stage: "judge" | "repair" | "rejudge";
    profile: "quality_judge" | "quality_repair";
    messages: ApiChatMessage[];
  };
};
export type ProjectLoadResp = { project?: unknown | null; updated_at?: string | null; revision?: string | null };
export type ProjectSaveResp = { ok?: boolean; bytes?: number; updated_at?: string; revision?: string; taste?: Record<string, unknown> };
export type ConfigResp = {
  schemaVersion?: string;
  flags?: Record<string, boolean>;
  models?: {
    generator?: string;
    motionDirector?: string;
  };
};
export type StyleDnaExtractResp = { tokens?: IRObject };
export type StyleDnaApplyResp = { ir?: IRObject };
export type NormalizePreviewResp = {
  normalizedIr?: IRObject;
  patch?: Array<{ path: string; before: unknown; after: unknown; origin: string; token?: string }>;
  tokenChanges?: string[];
  visualDelta?: { changedProperties?: number; risk?: string; requiresVisualReview?: boolean };
};
export type TailwindProjectionResp = {
  version?: string;
  irHash?: string;
  mode?: "exact" | "normalized";
  breakpoints?: Record<string, number>;
  theme?: Record<string, unknown>;
  nodes?: Array<{ sourceKey: string; path: string; type: string; classes: Record<string, string[]> }>;
  diagnostics?: Array<{ level?: string; sourceKey?: string; message?: string }>;
};
export type InteractionBuildResp = { interaction?: IRObject };
export type InteractionValidateResp = { valid?: boolean; errors?: string[] };
export type InteractionReplayResp = { ir?: IRObject };
export type InteractionCaptureResp = { interaction?: IRObject };
export type MotionBuildResp = { motion?: IRObject; sceneIrs?: Array<{ sceneId: string; ir: IRObject }> };
export type MotionValidateResp = { valid?: boolean; errors?: string[] };
export type MotionRenderResp = import("./types").MotionRenderJob;

export async function getConfig(): Promise<ConfigResp> {
  return apiGet<ConfigResp>("/api/config");
}

export async function extractStyleDna(ir: IRObject): Promise<StyleDnaExtractResp> {
  return api<StyleDnaExtractResp>("/api/style-dna/extract", { ir });
}

export async function applyStyleDna(ir: IRObject, tokens: IRObject): Promise<StyleDnaApplyResp> {
  return api<StyleDnaApplyResp>("/api/style-dna/apply", { ir, tokens });
}

export async function previewStyleNormalization(ir: IRObject, tolerance = 0.12): Promise<NormalizePreviewResp> {
  return api<NormalizePreviewResp>("/api/style/normalize/preview", { ir, tolerance });
}

export async function exportTailwind(ir: IRObject, mode: "exact" | "normalized" = "exact"): Promise<TailwindProjectionResp> {
  return api<TailwindProjectionResp>("/api/export/tailwind", { ir, mode });
}

export async function buildInteraction(
  baseIr: IRObject,
  scenes: Array<Record<string, unknown>>,
  events: Array<Record<string, unknown>>,
  source: Record<string, unknown> = { kind: "design-ir", url: "" },
): Promise<InteractionBuildResp> {
  return api<InteractionBuildResp>("/api/interaction/build", { base_ir: baseIr, source, scenes, events, variables: {} });
}

export async function validateInteraction(interaction: IRObject): Promise<InteractionValidateResp> {
  return api<InteractionValidateResp>("/api/interaction/validate", { interaction });
}

export async function replayInteraction(baseIr: IRObject, interaction: IRObject, sceneId: string): Promise<InteractionReplayResp> {
  return api<InteractionReplayResp>("/api/interaction/replay", { base_ir: baseIr, interaction, scene_id: sceneId });
}
