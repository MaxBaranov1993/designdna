/* UI-состояние React DNA-редактора: открытие/закрытие, активный инструмент.
 * Тяжёлая сессия (IR, geo-хендл, история, pan/zoom) живёт в controller.ts —
 * здесь только то, что рендерит React. */
import { create } from "zustand";
import { deepClone } from "../flow/dataflow";
import { useFlowStore } from "../flow/store";
import { toast } from "../flow/toast";
import type { IRObject } from "../flow/types";
import type { AssistPreview } from "./aiTypes";
import * as ctl from "./controller";

interface EditorUIState {
  isOpen: boolean;
  nodeId: number | null;
  tool: string;
  dirty: boolean;
  aiOpen: boolean;
  aiBusy: boolean;
  aiError: string;
  aiPreview: AssistPreview | null;
  previewing: boolean;
  closeConfirm: boolean;
  /* Тик инспектора: контроллер бампит при смене выделения/мутациях,
   * InspectorPanel перемонтирует дерево по key={tick} (аналог innerHTML-перестройки). */
  inspectorTick: number;
  /** Открыть React-редактор для ноды. false — движки недоступны, зовите legacy fallback. */
  openEditor: (nodeId: number, options?: { ai?: boolean }) => boolean;
}

export const useEditorStore = create<EditorUIState>()((set) => ({
  isOpen: false,
  nodeId: null,
  tool: "select",
  dirty: false,
  aiOpen: false,
  aiBusy: false,
  aiError: "",
  aiPreview: null,
  previewing: false,
  closeConfirm: false,
  inspectorTick: 0,

  openEditor: (nodeId, options) => {
    const st = useFlowStore.getState();
    const n = st.nodes.find((x) => Number(x.id) === nodeId);
    const ir = n ? ((n.data as { ir?: IRObject | null }).ir ?? null) : null;
    if (!ir) {
      toast("Сначала подключите макет к входу ноды", "error");
      return true; // ошибка показана
    }

    // DNA Editor мутирует IR in-place. Write-through shim держит граф и редактор
    // на одном объекте, чтобы undo/redo и инспектор сразу отражались в ноде.
    // Для «Закрыть без сохранения» делаем снапшот до открытия и восстанавливаем.
    let snapshot = deepClone(ir);
    const nodeLike: ctl.NodeShim = {
      data: {
        get ir(): IRObject | null {
          const cur = useFlowStore.getState().nodes.find((x) => Number(x.id) === nodeId);
          return cur ? (cur.data as { ir?: IRObject | null }).ir ?? null : null;
        },
        set ir(v: IRObject | null) {
          useFlowStore.getState().setNodeData(nodeId, { ir: v });
        },
      },
    } as ctl.NodeShim;

    const ok = ctl.open(
      nodeLike,
      (savedIr: IRObject) => {
        snapshot = deepClone(savedIr);
        const fst = useFlowStore.getState();
        fst.setNodeData(nodeId, { ir: savedIr });
        fst.propagate(nodeId);
        toast("Сохранено", "ok");
      },
      (saved) => {
        if (!saved && snapshot) {
          const fst = useFlowStore.getState();
          fst.setNodeData(nodeId, { ir: snapshot });
          fst.propagate(nodeId);
        }
      },
    );
    if (!ok) return false;
    set({
      isOpen: true,
      nodeId,
      tool: "select",
      dirty: false,
      aiOpen: !!options?.ai,
      aiBusy: false,
      aiError: "",
      aiPreview: null,
      previewing: false,
      closeConfirm: false,
    });
    return true;
  },
}));

/* Связываем контроллер со стором (без циклического импорта controller → store) */
ctl.bindUi({
  setTool: (t) => useEditorStore.setState({ tool: t }),
  setOpen: (v) => useEditorStore.setState({
    isOpen: v,
    ...(v ? {} : {
      nodeId: null,
      dirty: false,
      aiOpen: false,
      aiBusy: false,
      aiError: "",
      aiPreview: null,
      previewing: false,
      closeConfirm: false,
    }),
  }),
  bumpInspector: () => useEditorStore.setState((s) => ({ inspectorTick: s.inspectorTick + 1 })),
  setDirty: (dirty) => useEditorStore.setState({ dirty }),
  setCloseConfirm: (closeConfirm) => useEditorStore.setState({ closeConfirm }),
  setAiOpen: (aiOpen) => useEditorStore.setState({ aiOpen }),
  setAiBusy: (aiBusy) => useEditorStore.setState({ aiBusy }),
  setAiError: (aiError) => useEditorStore.setState({ aiError }),
  setAiPreview: (aiPreview) => useEditorStore.setState({ aiPreview }),
  setPreviewing: (previewing) => useEditorStore.setState({ previewing }),
});
