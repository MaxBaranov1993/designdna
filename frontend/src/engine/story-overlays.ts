export type StoryOverlay = { id: string; anchorTarget: string; title?: string; width?: number; radius?: number;
  background?: string; color?: string; accent?: string; items: Array<{id: string; text: string; selected?: boolean}> };

export function overlayTargets(overlays: StoryOverlay[] = []) {
  return overlays.flatMap(panel => [{id: `overlay.${panel.id}`, label: panel.title || "Меню", kind: "card"},
    ...panel.items.map(item => ({id: `overlay.${panel.id}.${item.id}`, label: item.text, kind: "button"}))]);
}

/** Text-only DOM, anchored to the actual source element. Shared by preview and MP4. */
export function renderStoryOverlays(root: HTMLElement, ir: any, overlays: StoryOverlay[], find: (root: HTMLElement, id: string) => HTMLElement | null) {
  root.style.position = "relative";
  const panels: HTMLElement[] = [];
  for (const overlay of overlays) {
    const anchor = find(root, overlay.anchorTarget);
    if (!anchor) throw new Error(`Не найден элемент для окна: ${overlay.anchorTarget}`);
    const style = getComputedStyle(anchor), color = ir.tokens?.color || {};
    const panel = document.createElement("div");
    panel.dataset.storyTarget = `overlay.${overlay.id}`;
    panel.dataset.storyOverlay = overlay.id;
    Object.assign(panel.style, {position: "absolute", zIndex: "100", boxSizing: "border-box",
      width: `${overlay.width || 240}px`, padding: "8px", borderRadius: `${overlay.radius ?? 12}px`,
      background: overlay.background || color.surface || "#ffffff", color: overlay.color || color.text || "#171717",
      boxShadow: "0 12px 36px #00000024, 0 2px 8px #00000012", border: `1px solid ${color.border || "#dddddd"}`,
      fontFamily: style.fontFamily, fontSize: `${Math.max(13, Math.min(18, parseFloat(style.fontSize) || 14))}px`,
      fontWeight: "400", lineHeight: "1.5", transformOrigin: "top right"});
    if (overlay.title) {
      const title = document.createElement("div"); title.textContent = overlay.title;
      Object.assign(title.style, {padding: "8px 12px", fontWeight: "600", opacity: ".65", fontSize: "12px"});
      panel.append(title);
    }
    for (const item of overlay.items) {
      const button = document.createElement("div");
      button.dataset.storyTarget = `overlay.${overlay.id}.${item.id}`;
      button.textContent = item.text;
      Object.assign(button.style, {padding: "10px 12px", borderRadius: "7px", margin: "2px 0", whiteSpace: "pre-wrap",
        background: item.selected ? overlay.accent || color.primary || "#7018e6" : "transparent",
        color: item.selected ? "#ffffff" : "inherit"});
      panel.append(button);
    }
    root.append(panel);
    const artWidth = root.offsetWidth, ratio = root.getBoundingClientRect().width / artWidth || 1;
    const a = anchor.getBoundingClientRect(), origin = root.getBoundingClientRect();
    const panelWidth = Math.min(overlay.width || 240, artWidth - 24);
    panel.style.width = panelWidth + "px";
    panel.style.left = Math.max(12, Math.min(artWidth - panelWidth - 12, (a.right - origin.left) / ratio - panelWidth)) + "px";
    panel.style.top = (a.bottom - origin.top) / ratio + 10 + "px";
    panels.push(panel);
  }
  return panels;
}
