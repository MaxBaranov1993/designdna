/* Токены v2: роли и модульная шкала — общий контракт инспектора и рендерера.
 * Шаги шкалы и порядок ролей должны совпадать с app/ir/migrate.py
 * (derive_tokens_v2), иначе правка base/ratio в инспекторе уводила бы кегли
 * от того, что посчитал сервер при миграции. */

export const TYPE_ROLE_ORDER = [
  "display", "h1", "h2", "h3", "lead", "body", "small", "eyebrow",
] as const;

export type TypeRoleName = (typeof TYPE_ROLE_ORDER)[number];

export const TYPE_ROLE_STEPS: Record<TypeRoleName, number> = {
  display: 4, h1: 3, h2: 2, h3: 1, lead: 0.5, body: 0, small: -1, eyebrow: -1.5,
};

export const TYPE_ROLE_LABELS: Record<TypeRoleName, string> = {
  display: "Display", h1: "H1", h2: "H2", h3: "H3",
  lead: "Lead", body: "Body", small: "Small", eyebrow: "Eyebrow",
};

export const COLOR_ROLE_ORDER = [
  "bg", "bg2", "surface", "surface2", "ink", "ink2", "inkMuted",
  "line", "accent", "accentInk", "accent2",
] as const;

export const COLOR_ROLE_LABELS: Record<string, string> = {
  bg: "Фон", bg2: "Фон 2", surface: "Поверхность", surface2: "Поверхность 2",
  ink: "Текст", ink2: "Текст 2", inkMuted: "Текст тихий", line: "Линии",
  accent: "Акцент", accentInk: "Текст на акценте", accent2: "Акцент 2",
};

/** Пересчёт кеглей ролей по base/ratio — на месте, как в миграции. */
export function applyTypeScale(type: any): void {
  if (!type || typeof type !== "object" || !type.roles) return;
  const base = Number(type.base);
  const ratio = Number(type.ratio);
  if (!Number.isFinite(base) || !Number.isFinite(ratio) || ratio <= 1) return;
  for (const role of TYPE_ROLE_ORDER) {
    const target = type.roles[role];
    if (!target || typeof target !== "object") continue;
    target.size = Math.max(11, Math.min(160, Math.round(base * ratio ** TYPE_ROLE_STEPS[role])));
  }
}

const SERIF_MARKERS = ["Playfair", "Prata", "Cormorant", "Newsreader", "Vollkorn",
  "Georgia", "Times", "Garamond", "Merriweather", "Lora", "PT Serif", "Source Serif",
  "Literata", "Fraunces"];
const MONO_MARKERS = ["Mono", "Code", "Courier", "Consolas"];

/** Полный CSS font-stack с generic-фолбэком — зеркало typography.font_stack. */
export function fontStack(family: string): string {
  const name = String(family || "").trim() || "Inter";
  const generic = MONO_MARKERS.some((m) => name.includes(m))
    ? "monospace"
    : SERIF_MARKERS.some((m) => name.includes(m)) ? "serif" : "sans-serif";
  return `"${name}", system-ui, ${generic}`;
}

/** Число из поля инспектора без округления до целого (ratio 1.45, base 16.5). */
export function readFloatInput(raw: string): number | null {
  const value = Number(String(raw).trim().replace(",", "."));
  return Number.isFinite(value) ? value : null;
}
