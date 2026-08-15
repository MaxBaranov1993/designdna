/* UI-состояние React DNA-редактора: открытие/закрытие, активный инструмент.
 * Тяжёлая сессия (IR, geo-хендл, история, pan/zoom) живёт в controller.ts —
 * здесь только то, что рендерит React. */
import { create } from "zustand";
import { deepClone } from "../flow/dataflow";
import { useFlowStore } from "../flow/store";
import { toast } from "../flow/toast";
import type { IRObject } from "../flow/types";
import * as ctl from "./controller";

interface EditorUIState {
  isOpen: boolean;
  nodeId: number | null;
  tool: string;
  /* Тик инспектора: контроллер бампит при смене выделения/мутациях,
   * InspectorPanel перемонтирует дерево по key={tick} (аналог innerHTML-перестройки). */
  inspectorTick: number;
  sourceTick: number;
  smartAxisProposal: ctl.SmartAxisProposal | null;
  qualityProposal: ctl.EditorQualityProposal | null;
  harmonizerProposal: ctl.HarmonizerProposal | null;
  responsiveProposal: ctl.ResponsiveAutopilotProposal | null;
  intentLocksOpen: boolean;
  semanticSelectOpen: boolean;
  /** Открыть React-редактор для ноды. false — движки недоступны, зовите legacy fallback. */
  openEditor: (nodeId: number) => boolean;
}

export const useEditorStore = create<EditorUIState>()((set) => ({
  isOpen: false,
  nodeId: null,
  tool: "select",
  inspectorTick: 0,
  sourceTick: 0,
  smartAxisProposal: null,
  qualityProposal: null,
  harmonizerProposal: null,
  responsiveProposal: null,
  intentLocksOpen: false,
  semanticSelectOpen: false,

  openEditor: (nodeId) => {
    const st = useFlowStore.getState();
    const n = st.nodes.find((x) => Number(x.id) === nodeId);
    const ir = n ? ((n.data as { ir?: IRObject | null }).ir ?? null) : null;
    const sourceRegistry = n ? ((n.data as { sourceRegistry?: Record<string, unknown> }).sourceRegistry || {}) : {};
    const nodeSources = n ? ((n.data as { nodeSources?: Record<string, string> }).nodeSources || {}) : {};
    const layoutEvidence = n ? ((n.data as { layoutEvidence?: unknown[] }).layoutEvidence || []) : [];
    if (!ir) {
      toast("Сначала подключите IR к входу ноды", "error");
      return true; // ошибка показана
    }

    // DNA Editor мутирует IR in-place. Write-through shim держит граф и редактор
    // на одном объекте, чтобы undo/redo и инспектор сразу отражались в ноде.
    // Для «Закрыть без сохранения» делаем снапшот до открытия и восстанавливаем.
    const snapshot = deepClone(ir);
    let saved = false;
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
        saved = true;
        const fst = useFlowStore.getState();
        fst.setNodeData(nodeId, { ir: savedIr });
        fst.propagate(nodeId);
        toast("IR сохранён из редактора", "ok");
      },
      () => {
        if (!saved && snapshot) {
          const fst = useFlowStore.getState();
          fst.setNodeData(nodeId, { ir: snapshot });
          fst.propagate(nodeId);
        }
      },
      { registry: sourceRegistry, nodeSources, layoutEvidence },
    );
    if (!ok) return false;
    set({ isOpen: true, nodeId, tool: "select", smartAxisProposal: null, qualityProposal: null, harmonizerProposal: null, responsiveProposal: null, intentLocksOpen: false, semanticSelectOpen: false });
    return true;
  },
}));

/* Связываем контроллер со стором (без циклического импорта controller → store) */
ctl.bindUi({
  setTool: (t) => useEditorStore.setState({ tool: t }),
  setOpen: (v) => useEditorStore.setState({ isOpen: v, ...(v ? {} : { nodeId: null, smartAxisProposal: null, qualityProposal: null, harmonizerProposal: null, responsiveProposal: null, intentLocksOpen: false, semanticSelectOpen: false }) }),
  bumpInspector: () => useEditorStore.setState((s) => ({ inspectorTick: s.inspectorTick + 1 })),
  bumpSources: () => useEditorStore.setState((s) => ({ sourceTick: s.sourceTick + 1 })),
  setSmartAxisProposal: (smartAxisProposal) => useEditorStore.setState({ smartAxisProposal }),
  setQualityProposal: (qualityProposal) => useEditorStore.setState({ qualityProposal }),
  setHarmonizerProposal: (harmonizerProposal) => useEditorStore.setState({ harmonizerProposal }),
  setResponsiveProposal: (responsiveProposal) => useEditorStore.setState({ responsiveProposal }),
  setIntentLocksOpen: (intentLocksOpen) => useEditorStore.setState({ intentLocksOpen }),
  setSemanticSelectOpen: (semanticSelectOpen) => useEditorStore.setState({ semanticSelectOpen }),
});
