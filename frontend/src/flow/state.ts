import { asReadable, selectReadable, shallowRecordEquals } from "../lib/zustand";
import { useFlowStore, bindPageState } from "./store";
import { readable } from 'svelte/store';

/** A workspace keeps its original sheet when callbacks outlive the component. */
export function pageFlow(pageId = useFlowStore.getState().activePageId) {
  const get = bindPageState(pageId);
  return readable(get(), set => {
    set(get());
    return useFlowStore.subscribe(() => set(get()));
  });
}

/* Реактивный снимок zustand-стора графа для Svelte-компонентов ($flow).
 * Действия вызываются через тот же объект: $flow.addNode(...) и т.д.
 *
 * Для реактивных чтений экспортированы срезы: подписка через $flow будит
 * компонент на КАЖДОМ set стора (включая чужие busy/statuses во время
 * длинных операций), срез эмитит только при изменении своих данных.
 * Сравнение записей — поверхностное: setBusy(id, то же значение) не эмитит. */
export const flow = asReadable(useFlowStore);
export const flowNodes = selectReadable(useFlowStore, (s) => s.nodes);
export const flowEdges = selectReadable(useFlowStore, (s) => s.edges);
export const flowPages = selectReadable(useFlowStore, (s) => s.pages);
export const flowActivePageId = selectReadable(useFlowStore, (s) => s.activePageId);
export const flowChannels = selectReadable(useFlowStore, (s) => s.channels, shallowRecordEquals);
export const flowDesignSystems = selectReadable(useFlowStore, (s) => s.designSystems);
export const flowDesignSystemPicker = selectReadable(useFlowStore, (s) => s.designSystemPicker);
export const flowStatuses = selectReadable(useFlowStore, (s) => s.statuses, shallowRecordEquals);
export const flowBusy = selectReadable(useFlowStore, (s) => s.busy, shallowRecordEquals);
export const flowProgresses = selectReadable(useFlowStore, (s) => s.progresses, shallowRecordEquals);
export const flowGraphHistory = selectReadable(useFlowStore, (s) => s.graphHistory);
export const flowStatusLog = selectReadable(useFlowStore, (s) => s.statusLog, shallowRecordEquals);
