import { IRRenderer } from "./renderer";
import { TimelineEngine } from "./timeline";
import { motionEase, type StoryEasing } from "./story-motion";
import { overlayTargets, renderStoryOverlays, type StoryOverlay } from "./story-overlays";

export type StoryPage = { id: string; name: string; ir: Record<string, any>; generatedFrom?: string; overlays?: StoryOverlay[] };
export type StoryAction = {
  id: string; type: "move" | "click" | "type" | "wait" | "scroll" | "navigate";
  pageId: string; duration: number; target?: string; text?: string; y?: number;
  toPageId?: string; transition?: "cut" | "fade" | "motion" | "state"; easing?: StoryEasing;
};
export type VideoStory = { pages: StoryPage[]; initialPageId: string; actions: StoryAction[] };
export const actionLabel: Record<StoryAction["type"], string> = {
  move: "Навести курсор", click: "Нажать", type: "Ввести текст", wait: "Пауза", scroll: "Прокрутить", navigate: "Перейти",
};
export function storySchedule(story: VideoStory) {
  let time = 0;
  return story.actions.map((action) => { const start = time; time += action.duration; return { ...action, start, end: time }; });
}
export function storyTargets(ir: Record<string, any>, overlays: StoryOverlay[] = []) {
  const result: Array<{ id: string; label: string; kind: string }> = [];
  const add = (section: number, path: string, node: any, kind?: string) => {
    const label = [node.label, node.text, node.placeholder, node.name, node.title].find((v) => typeof v === "string" && v);
    result.push({ id: `s${section}${path ? "." + path : ""}`, label: String(label || node.type || path).slice(0, 160), kind: kind || node.type || "element" });
  };
  const walk = (s: number, nodes: any[], prefix: string) => (nodes || []).forEach((node, i) => {
    const path = `${prefix}.${i}`; add(s, path, node); walk(s, node.children, path + ".children");
  });
  (ir.tree || []).forEach((section: any, i: number) => {
    add(i, "", section); walk(i, section.children, "children");
    const props = section.props || {};
    for (const key of ["heading", "subheading", "text"]) if (typeof props[key] === "string" && props[key]) add(i, `props.${key}`, { text: props[key] }, "text");
    (props.fields || []).forEach((field: any, j: number) => add(i, `props.fields.${j}`, field, "input"));
    if (props.cta && typeof props.cta === "object") add(i, "props.cta", props.cta, "button");
  });
  return [...result.slice(0, 512), ...overlayTargets(overlays)];
}

export function storyTarget(root: HTMLElement, target: string): HTMLElement | null {
  if (target.startsWith("overlay.")) return Array.from(root.querySelectorAll<HTMLElement>("[data-story-target]")).find(el => el.dataset.storyTarget === target) || null;
  const match = /^s(\d+)(?:\.(.+))?$/.exec(target);
  if (!match) return null;
  const section = root.querySelector<HTMLElement>(`[data-ir-sec="${Number(match[1])}"]`);
  if (!section || !match[2]) return section;
  return Array.from(section.querySelectorAll<HTMLElement>("[data-ir-path]"))
    .find((el) => el.dataset.irPath === match[2]) || null;
}

/** Prefer the control itself over a larger layout wrapper for cursor placement. */
function actionTarget(root: HTMLElement, id: string): HTMLElement {
  const target = storyTarget(root, id)!;
  if (!target.dataset.irPath || target.matches("input,textarea,button,a,[role=button]")) return target;
  return Array.from(target.querySelectorAll<HTMLElement>("input,textarea,button,a,[role=button]"))
    .find((el) => el.dataset.irPath === target.dataset.irPath || el.closest("[data-ir-path]") === target) || target;
}

/** One deterministic DOM player for editor and frame export. Never dispatches events. */
export class VideoStoryPlayer {
  private roots = new Map<string, { outer: HTMLElement; inner: HTMLElement; scale: number; panels: HTMLElement[] }>();
  private fields = new Map<string, { el: HTMLElement; initial: string; overlay?: HTMLElement }>();
  private mapped: Array<{el: HTMLElement; id: string; transform: string; opacity: number; visibility: string}> = [];
  private cursor: HTMLElement;
  private pulse: HTMLElement;
  private engine: TimelineEngine;
  readonly story: VideoStory;

  constructor(private host: HTMLElement, private document: any, offline = false) {
    this.story = document.story;
    this.engine = new TimelineEngine(document);
    host.replaceChildren();
    Object.assign(host.style, { width: `${document.composition.width}px`, height: `${document.composition.height}px`, position: "relative", overflow: "hidden", pointerEvents: "none", background: document.composition.background });
    for (const page of this.story.pages) {
      const outer = window.document.createElement("div");
      outer.dataset.storyPage = page.id;
      Object.assign(outer.style, { position: "absolute", inset: "0", overflow: "hidden", background: document.composition.background });
      const inner = window.document.createElement("div");
      outer.append(inner); host.append(outer);
      IRRenderer.renderIR(inner, page.ir as any, { viewport: "desktop", fit: false, offline });
      const artWidth = Number(inner.querySelector<HTMLElement>("[data-design-width]")?.dataset.designWidth) || Number(page.ir.frame?.width) || 1440;
      const scale = document.composition.width / artWidth;
      Object.assign(inner.style, { width: artWidth + "px", transformOrigin: "top left" });
      const panels = renderStoryOverlays(inner, page.ir, page.overlays || [], storyTarget);
      this.roots.set(page.id, { outer, inner, scale, panels });
      for (const layer of document.layers || []) {
        if (layer.type !== "component" || (layer.pageId || this.story.pages[0].id) !== page.id) continue;
        let target = layer.storyTarget;
        if (!target) {
          const visit = (node: any, path: string) => {
            if ((node.sourceKey || node.id) === layer.ref) target = path;
            (node.children || []).forEach((child: any, i: number) => visit(child, `${path}.children.${i}`));
          };
          (page.ir.tree || []).forEach((section: any, i: number) => visit(section, `s${i}`));
        }
        const el = target ? storyTarget(inner, target) : null;
        if (el) {
          el.dataset.timelineLayer = layer.id;
          const base = getComputedStyle(el);
          this.mapped.push({ el, id: layer.id, transform: base.transform === "none" ? "" : base.transform, opacity: Number(base.opacity), visibility: base.visibility });
        }
      }
    }
    for (const action of this.story.actions.filter((a) => a.type === "type")) {
      const key = `${action.pageId}/${action.target}`;
      if (this.fields.has(key)) continue;
      const root = this.roots.get(action.pageId)?.inner;
      const target = root && storyTarget(root, action.target || "");
      if (!target) throw new Error(`Не найдено поле ${action.target} на странице ${action.pageId}`);
      const input = target.matches("input,textarea") ? target : target.querySelector<HTMLElement>("input,textarea");
      if (input) {
        this.fields.set(key, { el: input, initial: (input as HTMLInputElement).value });
      } else {
        const overlay = window.document.createElement("span");
        overlay.dataset.storyTyped = "true";
        Object.assign(overlay.style, { position: "absolute", inset: "0", padding: "8px 12px", display: "none", alignItems: "center", whiteSpace: "pre-wrap", font: "inherit", color: "inherit", overflow: "hidden" });
        if (getComputedStyle(target).position === "static") target.style.position = "relative";
        target.append(overlay);
        this.fields.set(key, { el: target, initial: "", overlay });
      }
    }
    // Also refuse unresolved clicks/moves before rendering a misleading clip.
    for (const action of this.story.actions.filter((a) => a.target)) {
      const root = this.roots.get(action.pageId)?.inner;
      if (!root || !storyTarget(root, action.target!)) throw new Error(`Не найден элемент ${action.target} на странице ${action.pageId}`);
    }
    this.cursor = window.document.createElement("div");
    this.cursor.dataset.storyCursor = "true";
    this.cursor.innerHTML = '<svg width="30" height="38" viewBox="0 0 30 38"><path d="M3 2L25 23L15 24L11 34L3 2Z" fill="white" stroke="#101218" stroke-width="2" stroke-linejoin="round"/></svg>';
    Object.assign(this.cursor.style, { position: "absolute", left: "0", top: "0", zIndex: "9999", filter: "drop-shadow(0 2px 3px #0005)" });
    this.pulse = window.document.createElement("div");
    this.pulse.dataset.storyClick = "true";
    Object.assign(this.pulse.style, { position: "absolute", width: "48px", height: "48px", left: "0", top: "0", margin: "-24px", border: "3px solid #ff691d", borderRadius: "50%", zIndex: "9998" });
    host.append(this.pulse, this.cursor);
    this.seek(0);
  }

  private writeField(key: string, text: string | null) {
    const field = this.fields.get(key);
    if (!field) return;
    if (!field.overlay) (field.el as HTMLInputElement).value = text ?? field.initial;
    else {
      for (const child of Array.from(field.el.children) as HTMLElement[]) if (child !== field.overlay) child.style.visibility = text === null ? "" : "hidden";
      field.overlay.style.display = text === null ? "none" : "flex";
      field.overlay.textContent = text || "";
    }
  }

  seek(time: number) {
    const t = Math.max(0, Math.min(this.document.composition.duration, time));
    const solved = this.engine.seek(t);
    for (const base of this.mapped) {
      const state = solved[base.id];
      base.el.style.visibility = state.visible ? base.visibility : "hidden";
      base.el.style.opacity = String(state.visible ? state.opacity * base.opacity : 0);
      base.el.style.transform = `translate3d(${state.x}px,${state.y}px,0) rotate(${state.rotation}deg) scale(${state.scale}) ${base.transform}`;
    }
    for (const key of this.fields.keys()) this.writeField(key, null);
    const scrolls: Record<string, number> = {};
    const typed: Record<string, string> = {};
    let pageId = this.story.initialPageId;
    let x = this.document.composition.width / 2, y = this.document.composition.height / 2, visible = false, pulse = 0, cursorOpacity = 0, cursorScale = 1;
    let fade: { from: string; to: string; progress: number; motion: boolean; state: boolean } | null = null;
    const applyScroll = () => {
      for (const [id, root] of this.roots) root.inner.style.transform = `scale(${root.scale}) translateY(${- (scrolls[id] || 0)}px)`;
    };
    for (const root of this.roots.values()) { root.outer.style.transform = "none"; for (const panel of root.panels) panel.style.translate = "0px 0px"; }
    applyScroll();
    for (const action of storySchedule(this.story)) {
      if (t < action.start) break;
      const p = Math.min(1, (t - action.start) / action.duration);
      const ease = (v: number) => motionEase(v, action.easing);
      if (action.type === "navigate") {
        const to = action.toPageId!;
        const samePageState = action.transition === "state";
        fade = action.transition !== "cut" && p < 1 ? { from: pageId, to, progress: ease(p), motion: action.transition === "motion", state: samePageState } : null;
        if (samePageState) { scrolls[to] = scrolls[pageId] || 0; applyScroll(); }
        else cursorOpacity *= fade ? 1 - motionEase(Math.min(1, p * 2)) : 0;
        pageId = to; visible = visible && cursorOpacity > 0;
      } else if (action.type === "scroll") {
        const root = this.roots.get(pageId)!;
        const max = Math.max(0, root.inner.scrollHeight - this.document.composition.height / root.scale);
        let destination = action.y || 0;
        if (action.target) {
          const target = actionTarget(root.inner, action.target);
          const box = target.getBoundingClientRect(), origin = root.inner.getBoundingClientRect();
          const viewScale = this.host.getBoundingClientRect().width / this.document.composition.width || 1;
          destination = (box.top + box.height / 2 - origin.top) / (root.scale * viewScale) - this.document.composition.height / (2 * root.scale);
        }
        const end = Math.min(max, Math.max(0, destination));
        scrolls[pageId] = (scrolls[pageId] || 0) + (end - (scrolls[pageId] || 0)) * ease(p);
        applyScroll();
      } else if (action.target) {
        const root = this.roots.get(pageId)!;
        const target = actionTarget(root.inner, action.target);
        const box = target.getBoundingClientRect(), hostBox = this.host.getBoundingClientRect();
        const viewScale = hostBox.width / this.document.composition.width || 1;
        const endX = (box.left + box.width / 2 - hostBox.left) / viewScale;
        const endY = (box.top + box.height / 2 - hostBox.top) / viewScale;
        const movement = action.type === "move" ? p : Math.min(1, p / (action.type === "type" ? .35 : .5));
        const q = ease(movement), dx = endX - x, dy = endY - y, distance = Math.hypot(dx, dy);
        const arc = action.easing === "linear" ? 0 : Math.min(24, distance * .07) * Math.sin(Math.PI * q);
        x += dx * q - (distance ? dy / distance : 0) * arc;
        y += dy * q + (distance ? dx / distance : 0) * arc;
        if (!visible) cursorOpacity = motionEase((t - action.start) / 240);
        visible = true;
        if (action.type === "click" && p > .6 && p < 1) {
          pulse = (p - .6) / .4;
          cursorScale = 1 - .12 * Math.sin(Math.PI * pulse) ** 2;
        }
        if (action.type === "type") {
          const progress = Math.max(0, (p - .35) / .65);
          const value = Array.from(action.text || "").slice(0, Math.floor(Array.from(action.text || "").length * progress)).join("");
          typed[`${pageId}/${action.target}`] = value;
          this.writeField(`${pageId}/${action.target}`, value);
        }
      }
      if (p < 1) break;
    }
    for (const [id, root] of this.roots) {
      const opacity = fade ? id === fade.from ? 1 : id === fade.to ? fade.progress : 0 : id === pageId ? 1 : 0;
      if (fade?.motion) {
        const q = fade.progress;
        root.outer.style.transformOrigin = "center center";
        root.outer.style.transform = id === fade.to ? `translateY(${Math.min(10, this.document.composition.height * .012) * (1 - q)}px) scale(${1 + .035 * (1 - q)})` : "none";
      }
      // A full-opacity outgoing page under the incoming page prevents a dark flash.
      root.outer.style.zIndex = fade ? id === fade.to ? "2" : id === fade.from ? "1" : "0" : "0";
      root.outer.style.opacity = String(opacity);
      root.outer.style.visibility = opacity > 0 ? "visible" : "hidden";
      if (fade?.state && id === fade.to) for (const panel of root.panels) panel.style.translate = `0px ${-8 * (1 - fade.progress)}px`;
    }
    this.cursor.style.visibility = visible ? "visible" : "hidden";
    this.cursor.style.opacity = String(cursorOpacity);
    this.cursor.style.transformOrigin = "3px 2px";
    this.cursor.style.transform = `translate(${x}px,${y}px) scale(${cursorScale})`;
    this.pulse.style.opacity = pulse ? String(.75 * Math.sin(Math.PI * pulse) ** 2) : "0";
    this.pulse.style.transform = `translate(${x}px,${y}px) scale(${.35 + .9 * motionEase(pulse, "ease-out")})`;
    return { pageId, cursor: { x, y, visible, opacity: cursorOpacity, scale: cursorScale }, typed, scrolls, time: t };
  }

  destroy() { this.host.replaceChildren(); }
}
