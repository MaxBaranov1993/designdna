import type { IRObject } from "./types";

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

/* Формы ответов бэкенда — по server.py и вызовам legacy (FLOW-MIGRATION.md §4) */
export type GenerateResp = { variants?: IRObject[]; errors?: string[] };
export type MixResp = { ir?: IRObject | null };
export type CloneResp = { ir?: IRObject | null; cached?: boolean };
export type ReproduceResp = {
  ir?: IRObject | null;
  html?: string;
  diff?: { overall_pct?: number; mean_rgb?: number[]; error?: string };
  colors?: { colors?: Record<string, { hex: string; pixels: number }> };
  repro_png?: string;
  icons_count?: number;
  cached?: boolean;
  provider_used?: string;
};
/* BlockParse/Reskin (решение владельца 11, server.py /api/block-parse, /api/reskin):
 * ошибка отдельного блока — в его записи (error), остальные работают */
export type BlockParseBlockResp = {
  name: string;
  selector: string;
  ir?: IRObject;
  error?: string;
  cached?: boolean;
};
export type BlockParseResp = {
  url: string;
  blocks: BlockParseBlockResp[];
  tokens: Record<string, unknown> | null;
  cached?: boolean;
};
export type ReskinResp = { ir?: IRObject | null; log?: string[] };
