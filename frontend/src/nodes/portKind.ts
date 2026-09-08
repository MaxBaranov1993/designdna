/* kind-классы хендлов: ir — акцентный, tokens — янтарный (решение владельца 9) */
export function kindClass(kind: string): string {
  if (kind === "ir") return "port-ir";
  if (kind === "tokens") return "port-tokens";
  if (kind === "artifact") return "port-artifact";
  if (kind === "interaction") return "port-interaction";
  if (kind === "motion") return "port-motion";
  if (kind === "timeline") return "port-timeline";
  if (kind === "video") return "port-video";
  if (kind === "ds") return "port-ds";
  if (kind === "image") return "port-image";
  if (kind === "text") return "port-text";
  return "";
}

/* Цвет провода = kind порта (дизайн-хендофф design_handoff_node_editor). */
export const KIND_COLORS: Record<string, string> = {
  ir: "#9B5CFF",
  tokens: "#FF691D",
  artifact: "#35B8A0",
  interaction: "#2FBF9F",
  motion: "#E05FB0",
  timeline: "#FF5F56",
  video: "#4F7CFF",
  ds: "#8B7CF6",
  text: "#8A8A93",
  image: "#3FB950",
};

export function kindColor(kind: string | null | undefined): string {
  return (kind && KIND_COLORS[kind]) || KIND_COLORS.text;
}
