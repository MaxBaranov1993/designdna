/* Портал в document.body — аналог React createPortal(..., document.body):
 * выносит оверлеи (Motion Workspace) из трансформированного viewport канваса. */
export function bodyPortal(node: HTMLElement) {
  document.body.appendChild(node);
  return {
    destroy() {
      node.remove();
    },
  };
}
