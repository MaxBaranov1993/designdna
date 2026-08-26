import { asReadable, selectReadable, shallowRecordEquals } from "../lib/zustand";
import { useFlowStore } from "./store";

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
export const flowStatuses = selectReadable(useFlowStore, (s) => s.statuses, shallowRecordEquals);
export const flowBusy = selectReadable(useFlowStore, (s) => s.busy, shallowRecordEquals);
