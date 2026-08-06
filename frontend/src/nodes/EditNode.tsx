import { useEffect, useRef } from "react";
import type { NodeProps } from "@xyflow/react";
import { deepClone } from "../flow/dataflow";
import { useFlowStore } from "../flow/store";
import { toast } from "../flow/toast";
import type { EditFlowNode, IRObject } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { InPorts, OutPorts } from "./PortHandles";
import {
  editHistory,
  installEditKeys,
  registerGeo,
  unregisterGeo,
} from "./editRuntime";
import type { GeoEditHandle, GeoEditSelection } from "./editRuntime";

/* «Редактор (DNA)» — Figma-правка внутри ноды: legacy-ядро GeoEdit + Inspector +
 * IRHistory + Editor.open монтируется БЕЗ переписывания (решение владельца №6).
 * Модель — setupEditNode/renderEditPreview/refreshEdit (nodes.js:663-780):
 * превью слева, инспектор справа, оверлей GeoEdit внутри .edit-inner —
 * трансформированного контейнера, поэтому рамки совпадают с элементами при любом зуме.
 * lifecycle: refresh() — единственная точка (пересоздание превью + GeoEdit + инспектор). */

const PLACEHOLDER = '<div class="placeholder">Подключите IR к входу (или через GraphDev.setIR)</div>';

export function EditNode({ id, data, selected }: NodeProps<EditFlowNode>) {
  const nodeId = Number(id);
  const prevRef = useRef<HTMLDivElement>(null); // .edit-preview — скролл-контейнер
  const innerRef = useRef<HTMLDivElement>(null); // .edit-inner — previewEl для GeoEdit
  const inspRef = useRef<HTMLDivElement>(null);
  const selLabelRef = useRef<HTMLSpanElement>(null);
  const zoomLabelRef = useRef<HTMLSpanElement>(null);

  /* runtime-поля ноды (в сейв не попадают, зеркало n.geo/n.editZoom из legacy) */
  const geoRef = useRef<GeoEditHandle | null>(null);
  const editZoomRef = useRef<number | null>(null); // null = fit по ширине, как в legacy
  const selKeyRef = useRef(""); // ключ коалесценции истории: выделение к моменту onCommit
  const irRef = useRef<IRObject | null>(data.ir);
  const refreshRef = useRef<() => void>(() => {});

  /* ---------- зум (зеркало currentZoom/applyZoom/zoomBy из setupEditNode) ---------- */

  function currentZoom(): number {
    const prev = prevRef.current;
    const inner = innerRef.current;
    if (!prev || !inner) return 1;
    const irEl = inner.querySelector('[class^="ir-"]') as HTMLElement | null;
    if (!irEl) return 1;
    const dw = Number(irEl.dataset.designWidth) || window.IRRenderer?.DESIGN_WIDTH || 960;
    const fit = Math.min(1, (prev.clientWidth || 300) / dw);
    return editZoomRef.current == null ? fit : editZoomRef.current;
  }

  function applyZoom() {
    const inner = innerRef.current;
    if (!inner) return;
    const irEl = inner.querySelector('[class^="ir-"]') as HTMLElement | null;
    if (!irEl) {
      if (zoomLabelRef.current) zoomLabelRef.current.textContent = "—";
      return;
    }
    const z = currentZoom();
    irEl.style.transform = `scale(${z})`;
    inner.style.height = irEl.offsetHeight * z + "px";
    if (zoomLabelRef.current) zoomLabelRef.current.textContent = Math.round(z * 100) + "%";
    if (geoRef.current) geoRef.current.syncZoom();
  }

  function zoomBy(factor: number) {
    editZoomRef.current = Math.min(2, Math.max(0.05, currentZoom() * factor));
    applyZoom();
  }

  /* ---------- инспектор (зеркало renderInsp) ---------- */

  function renderInsp() {
    const insp = inspRef.current;
    if (!insp || !window.Inspector) return;
    window.Inspector.render(insp, {
      ir: irRef.current,
      selections: geoRef.current ? geoRef.current.selections : [],
      geo: geoRef.current,
    });
  }

  /* ---------- refresh: единственная точка lifecycle (зеркало refreshEdit) ---------- */

  refreshRef.current = () => {
    const inner = innerRef.current;
    if (!inner) return;
    const prevRefs = geoRef.current ? geoRef.current.selections.map((s) => s.ref) : [];
    if (geoRef.current) {
      unregisterGeo(nodeId);
      geoRef.current.destroy();
      geoRef.current = null;
    }

    // превью: renderIR мутирует ir.tokens — рендерим глубокую копию (FLOW-MIGRATION.md §6.2A)
    const ir = irRef.current;
    if (!ir || !window.IRRenderer) {
      inner.innerHTML = PLACEHOLDER;
    } else {
      window.IRRenderer.renderIR(inner, deepClone(ir));
    }

    if (ir && window.GeoEdit) {
      geoRef.current = window.GeoEdit.attach({
        previewEl: inner,
        getIR: () => irRef.current,
        getScale: () => {
          const irEl = inner.querySelector('[class^="ir-"]') as HTMLElement | null;
          if (!irEl) return 1;
          const dw = Number(irEl.dataset.designWidth) || window.IRRenderer?.DESIGN_WIDTH || 960;
          const w = irEl.getBoundingClientRect().width;
          return w > 0 ? w / dw : 1;
        },
        onCommit: () => {
          // снапшот ДО мутации; быстрые серии с одним выделением IRHistory сольёт сам
          const h = editHistory(nodeId);
          if (h && irRef.current) h.push(() => irRef.current, selKeyRef.current);
        },
        onMutated: () => {
          refreshRef.current();
          // GeoEdit мутирует объект in-place: поднимаем ссылку в сторе, чтобы
          // сработали автосейв-подписка и propagate вниз по графу
          const st = useFlowStore.getState();
          st.setNodeData(nodeId, { ir: irRef.current });
          st.propagate(nodeId);
        },
        onSelect: (sels: GeoEditSelection[]) => {
          selKeyRef.current = (sels || []).map((s) => s.ref.secIdx + ":" + (s.ref.path || "")).join(",");
          if (selLabelRef.current) {
            selLabelRef.current.textContent =
              sels && sels.length ? sels[0].label : irRef.current ? "—" : "нет IR на входе";
          }
          renderInsp();
        },
      });
      registerGeo(nodeId, geoRef.current);
    }

    // после rAF fitPreview применяем свой зум и синхронизируем оверлей
    requestAnimationFrame(applyZoom);
    if (prevRefs.length && geoRef.current) geoRef.current.selectMulti(prevRefs);
    renderInsp();
  };

  /* ---------- монтаж: кнопки/колесо один раз, refresh — на каждую замену IR ---------- */

  useEffect(() => {
    installEditKeys();
    const prev = prevRef.current;
    // скролл превью не должен зумить граф (зеркало setupEditNode)
    const onWheel = (e: WheelEvent) => e.stopPropagation();
    if (prev) prev.addEventListener("wheel", onWheel, { passive: true });
    return () => {
      if (prev) prev.removeEventListener("wheel", onWheel);
      if (geoRef.current) {
        unregisterGeo(nodeId);
        geoRef.current.destroy();
        geoRef.current = null;
      }
    };
  }, []);

  /* замена IR (провод/propagate, GraphDev.setIR, undo/redo, Editor) — полный refresh */
  useEffect(() => {
    irRef.current = data.ir;
    refreshRef.current();
  }, [data.ir]);

  /* «✦ Открыть DNA-редактор»: Editor.open(nodeLike, cb) — editor.js мутирует
   * node.data.ir in-place (свой undo), поэтому передаём shim и переносим результат
   * в стор колбэком (зеркало nodes.js:688-697). */
  const openEditor = () => {
    const ir = irRef.current;
    if (!ir) {
      toast("Сначала подключите IR к входу ноды", "error");
      return;
    }
    if (!window.Editor) return;
    // editor.js не только мутирует node.data.ir in-place, но и ЗАМЕНЯЕТ его
    // снапшотом при undo/redo (state.node.data.ir = snap). В legacy node.data.ir
    // был живым объектом ноды — делаем write-through в стор, иначе после undo
    // state.ir расходится с data.ir ноды и правки перестают быть видны снаружи.
    const nodeLike: { data: { ir: IRObject | null } } = {
      data: {
        get ir(): IRObject | null {
          const n = useFlowStore.getState().nodes.find((x) => Number(x.id) === nodeId);
          return n ? (n.data as { ir?: IRObject | null }).ir ?? null : null;
        },
        set ir(v: IRObject | null) {
          useFlowStore.getState().setNodeData(nodeId, { ir: v });
        },
      },
    };
    window.Editor.open(nodeLike, (savedIr: IRObject) => {
      const sameRef = irRef.current === savedIr;
      irRef.current = savedIr;
      const st = useFlowStore.getState();
      st.setNodeData(nodeId, { ir: savedIr });
      // та же ссылка — эффект по data.ir не сработает, перерисовываем вручную
      if (sameRef) refreshRef.current();
      st.propagate(nodeId);
      toast("IR сохранён из редактора", "ok");
    });
  };

  return (
    <NodeShell id={id} type="edit" selected={selected}>
      <InPorts type="edit" />
      <div className="edit-wrap nodrag">
        <div className="edit-left">
          {/* классы f-preview/ir-preview-inner — совместимость с селекторами тестов Фазы B2 */}
          <div ref={prevRef} className="edit-preview f-preview nowheel">
            <div ref={innerRef} className="edit-inner ir-preview-inner">
              <div className="placeholder">Подключите IR к входу (или через GraphDev.setIR)</div>
            </div>
          </div>
          <div className="geo-tools">
            <span ref={selLabelRef} className="sel-label">—</span>
            <button className="btn-node small f-zoom-out nodrag" title="Уменьшить" onClick={() => zoomBy(1 / 1.25)}>
              −
            </button>
            <span ref={zoomLabelRef} className="zoom-label">—</span>
            <button className="btn-node small f-zoom-in nodrag" title="Увеличить" onClick={() => zoomBy(1.25)}>
              +
            </button>
            <button
              className="btn-node small f-frame-reset nodrag"
              style={{ marginLeft: "auto" }}
              onClick={() => {
                if (geoRef.current) geoRef.current.resetFrame();
              }}
            >
              Сбросить frame
            </button>
          </div>
        </div>
        <div ref={inspRef} className="edit-inspector nodrag nowheel" />
      </div>
      <button className="btn-node primary small f-open-editor nodrag" style={{ width: "100%" }} onClick={openEditor}>
        ✦ Открыть DNA-редактор
      </button>
      <NodeStatus id={id} />
      <OutPorts type="edit" />
    </NodeShell>
  );
}
