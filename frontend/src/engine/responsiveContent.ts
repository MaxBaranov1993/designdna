/** Keep measured viewport content local when editing a materialized copy. */
export function syncResponsiveContent(node: any, active: any, viewport: string) {
  for (const prop of ["text", "title", "placeholder", "value", "label", "src", "alt", "href"]) {
    if (!Object.prototype.hasOwnProperty.call(active, prop)) continue;
    const overrides = node.responsive || {};
    const measured = ["text", "src"].includes(prop) && Object.values<any>(overrides)
      .some(override => typeof override?.[prop] === "string");
    if (measured) {
      node.responsive = overrides;
      overrides[viewport] = { ...overrides[viewport], [prop]: active[prop] };
      if (viewport === "desktop") node[prop] = active[prop];
    } else {
      node[prop] = active[prop];
    }
  }
}
