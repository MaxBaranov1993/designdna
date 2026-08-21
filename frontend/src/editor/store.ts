/* UI-состояние React DNA-редактора: открытие/закрытие, активный инструмент.
 * Тяжёлая сессия (IR, geo-хендл, история, pan/zoom) живёт в controller.ts —
 * здесь только то, что рендерит React. */
import { createStore } from "zustand/vanilla";
import { useFlowStore } from "../flow/store";
import { toast } from "../flow/toast";
import type { IRObject } from "../flow/types";
import type { AssistPreview, AssistProgress } from "./aiTypes";
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
  aiBusy: boolean;
  aiError: string;
  aiPreview: AssistPreview | null;
  aiProgress: AssistProgress | null;
  /** Открыть React-редактор для ноды. false — движки недоступны, зовите legacy fallback. */
  openEditor: (nodeId: number) => boolean;
}

export const useEditorStore = createStore<EditorUIState>()((set) => ({
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
  aiBusy: false,
  aiError: "",
  aiPreview: null,
  aiProgress: null,

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

    const persistedDraft = (n!.data as Record<string, unknown>)._editorDraft as
      | { baseRevision?: number; draftRevision?: number; ir?: IRObject }
      | undefined;
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
      draft: persistedDraft?.ir
        ? {
            baseRevision: Number(persistedDraft.baseRevision) || 0,
            draftRevision: Number(persistedDraft.draftRevision) || 0,
            ir: persistedDraft.ir,
          }
        : null,
      currentRevision: () => useFlowStore.getState().getNodeIrRevision(nodeId),
      persistDraft: (draft) => useFlowStore.getState().persistEditorDraft(nodeId, draft),
      clearDraft: () => useFlowStore.getState().clearEditorDraft(nodeId),
      commitDraft: (expectedRevision, draftIr) =>
        useFlowStore.getState().commitEditorDraft(nodeId, expectedRevision, draftIr),
    } as ctl.NodeShim;

    const ok = ctl.open(
      nodeLike,
      (savedIr: IRObject, expectedRevision: number) => {
        const fst = useFlowStore.getState();
        if (!fst.commitEditorDraft(nodeId, expectedRevision, savedIr)) {
          toast("IR изменился во входном графе. Черновик сохранён; обновите или перенесите правки вручную.", "error");
          return false;
        }
        fst.propagate(nodeId);
        toast("IR сохранён из редактора", "ok");
        return true;
      },
      (saved) => {
        if (!saved) useFlowStore.getState().clearEditorDraft(nodeId);
      },
      { registry: sourceRegistry, nodeSources, layoutEvidence },
    );
    if (!ok) return false;
    set({ isOpen: true, nodeId, tool: "select", smartAxisProposal: null, qualityProposal: null, harmonizerProposal: null, responsiveProposal: null, intentLocksOpen: false, semanticSelectOpen: false, aiBusy: false, aiError: "", aiPreview: null, aiProgress: null });
    if (ctl.dom.overlay) ctl.dom.overlay.style.display = "flex";
    requestAnimationFrame(() => {
      if (ctl.dom.overlay && useEditorStore.getState().isOpen && ctl.isActive()) ctl.finishOpen();
    });
    return true;
  },
}));

/* Связываем контроллер со стором (без циклического импорта controller → store) */
ctl.bindUi({
  setTool: (t) => useEditorStore.setState({ tool: t }),
  setOpen: (v) => {
    if (ctl.dom.overlay) ctl.dom.overlay.style.display = v ? "flex" : "none";
    useEditorStore.setState({ isOpen: v, ...(v ? {} : { nodeId: null, smartAxisProposal: null, qualityProposal: null, harmonizerProposal: null, responsiveProposal: null, intentLocksOpen: false, semanticSelectOpen: false, aiBusy: false, aiError: "", aiPreview: null, aiProgress: null }) });
  },
  bumpInspector: () => useEditorStore.setState((s) => ({ inspectorTick: s.inspectorTick + 1 })),
  bumpSources: () => useEditorStore.setState((s) => ({ sourceTick: s.sourceTick + 1 })),
  setSmartAxisProposal: (smartAxisProposal) => useEditorStore.setState({ smartAxisProposal }),
  setQualityProposal: (qualityProposal) => useEditorStore.setState({ qualityProposal }),
  setHarmonizerProposal: (harmonizerProposal) => useEditorStore.setState({ harmonizerProposal }),
  setResponsiveProposal: (responsiveProposal) => useEditorStore.setState({ responsiveProposal }),
  setIntentLocksOpen: (intentLocksOpen) => useEditorStore.setState({ intentLocksOpen }),
  setSemanticSelectOpen: (semanticSelectOpen) => useEditorStore.setState({ semanticSelectOpen }),
  setAiBusy: (aiBusy) => useEditorStore.setState({ aiBusy }),
  setAiError: (aiError) => useEditorStore.setState({ aiError }),
  setAiPreview: (aiPreview) => useEditorStore.setState({ aiPreview }),
  setAiProgress: (aiProgress) => useEditorStore.setState({ aiProgress }),
});
