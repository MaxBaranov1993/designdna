/* kind-классы хендлов: ir — акцентный, tokens — янтарный (решение владельца 9) */
export function kindClass(kind: string): string {
  if (kind === "ir") return "port-ir";
  if (kind === "tokens") return "port-tokens";
  if (kind === "interaction") return "port-interaction";
  if (kind === "motion") return "port-motion";
  return "";
}
