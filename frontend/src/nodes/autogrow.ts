/* Автовысота textarea в теле ноды: поле растёт с текстом до max, дальше скролл. */
export function autogrow(node: HTMLTextAreaElement, max = 240) {
  const fit = () => {
    node.style.height = "auto";
    node.style.height = `${Math.min(max, Math.max(node.scrollHeight, 40))}px`;
  };
  const frame = requestAnimationFrame(fit);
  node.addEventListener("input", fit);
  return {
    update: () => requestAnimationFrame(fit),
    destroy: () => {
      cancelAnimationFrame(frame);
      node.removeEventListener("input", fit);
    },
  };
}
