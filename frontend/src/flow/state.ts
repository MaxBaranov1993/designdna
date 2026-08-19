import { asReadable } from "../lib/zustand";
import { useFlowStore } from "./store";

/* Реактивный снимок zustand-стора графа для Svelte-компонентов ($flow).
 * Действия вызываются через тот же объект: $flow.addNode(...) и т.д. */
export const flow = asReadable(useFlowStore);
