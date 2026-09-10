import type { FlowStoreState } from './store';

export type FlowSet = (patch: Partial<FlowStoreState> | ((state: FlowStoreState) => Partial<FlowStoreState>)) => void;
export type PageRuntime = Pick<FlowStoreState, 'statuses' | 'statusLog' | 'busy' | 'progresses' | 'graphHistory'>;
const graphKeys = ['nodes', 'edges', 'view', 'nextId'] as const;
const runtimeKeys = ['statuses', 'statusLog', 'busy', 'progresses', 'graphHistory'] as const;
const localKeys = new Set<string>([...graphKeys, ...runtimeKeys]);
const projectActions = new Set([
  'createPage', 'addVideoChainPage', 'switchPage', 'renamePage', 'deletePage',
  'loadPersistedProject', 'replaceProjectFromDb', 'refreshDesignSystems', 'setDesignSystemPicker',
]);

export function emptyPageRuntime(): PageRuntime {
  return { statuses: {}, statusLog: {}, busy: {}, progresses: {}, graphHistory: { past: [], future: [] } };
}

export function pageRuntime(state: PageRuntime): PageRuntime {
  return Object.fromEntries(runtimeKeys.map(key => [key, state[key]])) as PageRuntime;
}

/** Bind every node action (including its nested actions after await) to its sheet.
 * The visible graph is never swapped to apply a background result. Runtime-only
 * updates have their own map, so polling a hidden sheet does not serialize a project.
 */
export function createPageAccess(
  rootGet: () => FlowStoreState, rootSet: FlowSet,
  factory: (set: FlowSet, get: () => FlowStoreState) => FlowStoreState,
) {
  const wrappers: Record<string, Function> = {};
  const pages = new Map<string, () => FlowStoreState>();
  const bind = (pageId: string): (() => FlowStoreState) => {
    const cached = pages.get(pageId);
    if (cached) return cached;
    let actions: Record<string, Function>;
    const get = (): FlowStoreState => {
      const root = rootGet();
      const page = root.pages.find(page => page.id === pageId);
      const graph = root.activePageId === pageId ? root : page;
      const runtime = root.activePageId === pageId ? root : root.pageRuntimes[pageId] || emptyPageRuntime();
      const bound = Object.fromEntries(Object.entries(actions).map(([key, action]) => [key,
        // Preserve explicit action replacements (e.g. host integrations and tests).
        (root as unknown as Record<string, unknown>)[key] === wrappers[key]
          ? action : (root as unknown as Record<string, unknown>)[key],
      ]));
      return { ...root, ...bound, ...pageRuntime(runtime), activePageId: pageId,
        nodes: graph?.nodes || [], edges: graph?.edges || [],
        view: graph?.view || { x: 0, y: 0, zoom: 1 }, nextId: graph?.nextId || 1,
        pages: root.pages.map(page => page.id === root.activePageId
          ? { ...page, nodes: root.nodes, edges: root.edges, view: root.view, nextId: root.nextId } : page),
      };
    };
    const set: FlowSet = update => {
      const root = rootGet();
      if (!root.pages.some(page => page.id === pageId)) return;
      const patch = typeof update === 'function' ? update(get()) : update;
      if (root.activePageId === pageId) { rootSet(patch); return; }
      const global = Object.fromEntries(Object.entries(patch).filter(([key]) => !localKeys.has(key))) as Partial<FlowStoreState>;
      const graph = Object.fromEntries(Object.entries(patch).filter(([key]) => (graphKeys as readonly string[]).includes(key)));
      const runtime = Object.fromEntries(Object.entries(patch).filter(([key]) => (runtimeKeys as readonly string[]).includes(key)));
      if (Object.keys(graph).length) global.pages = (global.pages || root.pages).map(page =>
        page.id === pageId ? { ...page, ...graph } : page);
      if (Object.keys(runtime).length) global.pageRuntimes = { ...root.pageRuntimes,
        [pageId]: { ...(root.pageRuntimes[pageId] || emptyPageRuntime()), ...runtime } };
      rootSet(global);
    };
    actions = Object.fromEntries(Object.entries(factory(set, get))
      .filter(([key, value]) => typeof value === 'function' && !projectActions.has(key)));
    pages.set(pageId, get);
    return get;
  };
  const wrap = (state: FlowStoreState): FlowStoreState => {
    for (const [key, value] of Object.entries(state)) {
      if (typeof value !== 'function' || projectActions.has(key)) continue;
      wrappers[key] = (...args: unknown[]) => {
        const state = bind(rootGet().activePageId)();
        return (state as unknown as Record<string, Function>)[key](...args);
      };
    }
    return { ...state, ...wrappers };
  };
  return { bind, wrap };
}
