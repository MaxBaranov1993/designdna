import { asReadable } from "../lib/zustand";
import { useEditorStore } from "./store";

/* Реактивный снимок zustand-стора DNA-редактора для Svelte-компонентов ($editorUi).
 * Поведение store.ts не менялось: Svelte только подписывается, действия — через
 * useEditorStore.getState() / controller.ts. */
export const editorUi = asReadable(useEditorStore);
