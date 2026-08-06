import { useCallback, useEffect, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  useViewport,
} from "@xyflow/react";
import type { Connection, NodeTypes } from "@xyflow/react";
import type { FlowEdge } from "./flow/types";
import "@xyflow/react/dist/style.css";

import { Button } from "./components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import { CTX_ITEMS, NODE_DEFS, portsOfNode } from "./flow/ports";
import { buildExportPayload, downloadJson, parseLegacyPayload } from "./flow/serialize";
import { useFlowStore } from "./flow/store";
import { installGraphDev, setReactFlowInstance } from "./flow/graphdev";
import { toast, ToastViewport } from "./flow/toast";
import { reachable } from "./flow/dataflow";
import { CloneNode } from "./nodes/CloneNode";
import { EditNode } from "./nodes/EditNode";
import { GeneratorNode } from "./nodes/GeneratorNode";
import { MixNode } from "./nodes/MixNode";
import { PromptNode } from "./nodes/PromptNode";
import { ReferenceNode } from "./nodes/ReferenceNode";
import { ReproduceNode } from "./nodes/ReproduceNode";
import { BlockParseNode } from "./nodes/BlockParseNode";
import { ReskinNode } from "./nodes/ReskinNode";

/* Реестр кастомных нод — вне компонента, ключи = legacy type (конвертация данных не нужна) */
const nodeTypes = {
  prompt: PromptNode,
  reference: ReferenceNode,
  generator: GeneratorNode,
  edit: EditNode,
  mix: MixNode,
  clone: CloneNode,
  reproduce: ReproduceNode,
  blockparse: BlockParseNode,
  reskin: ReskinNode,
} satisfies NodeTypes;

type CtxMenuState = { x: number; y: number; flowX: number; flowY: number };

/* Контекстное меню создания ноды — зеркало showCtxMenu/CTX_ITEMS (nodes.js:1096-1122) */
function CtxMenu({ menu, onClose }: { menu: CtxMenuState; onClose: () => void }) {
  const addNode = useFlowStore((s) => s.addNode);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div
      id="ctx-menu"
      style={{
        display: "block",
        left: Math.min(menu.x, window.innerWidth - 210),
        top: Math.min(menu.y, window.innerHeight - 260),
      }}
    >
      <div className="ctx-cap">Создать ноду</div>
      {CTX_ITEMS.map((it) => (
        <div
          key={it.type}
          className="ctx-item"
          data-type={it.type}
          onClick={() => {
            addNode(it.type, menu.flowX, menu.flowY);
            onClose();
          }}
        >
          <span className="ci">{NODE_DEFS[it.type].icon}</span>
          {NODE_DEFS[it.type].title}
          <small>{it.note}</small>
        </div>
      ))}
    </div>
  );
}

function FlowCanvas() {
  const nodes = useFlowStore((s) => s.nodes);
  const edges = useFlowStore((s) => s.edges);
  const onNodesChange = useFlowStore((s) => s.onNodesChange);
  const onEdgesChange = useFlowStore((s) => s.onEdgesChange);
  const [menu, setMenu] = useState<CtxMenuState | null>(null);
  // сейвовый вьюпорт читаем один раз; дальше RF управляет пан/зумом сам
  const [initialViewport] = useState(() => useFlowStore.getState().view);
  const rf = useReactFlow();

  useEffect(() => {
    setReactFlowInstance(rf);
    return () => setReactFlowInstance(null);
  }, [rf]);

  const onConnect = useCallback((c: Connection) => {
    if (!c.source || !c.target || !c.sourceHandle || !c.targetHandle) return;
    useFlowStore.getState().connect(
      { node: Number(c.source), port: c.sourceHandle },
      { node: Number(c.target), port: c.targetHandle },
    );
  }, []);

  /* Правила 1–4 из legacy connect() (nodes.js:1049-1062); правило 5 (замена ребра)
   * живёт в store.connect, т.к. isValidConnection может только разрешить/запретить */
  const isValidConnection = useCallback((c: FlowEdge | Connection) => {
    const st = useFlowStore.getState();
    if (!c.source || !c.target || c.source === c.target) return false;
    const src = st.nodes.find((n) => n.id === c.source);
    const dst = st.nodes.find((n) => n.id === c.target);
    if (!src || !dst) return false;
    const outP = portsOfNode(src).out.find((p) => p.name === c.sourceHandle);
    const inP = portsOfNode(dst).in.find((p) => p.name === c.targetHandle);
    if (!outP || !inP || outP.kind !== inP.kind) return false;
    return !reachable(Number(c.target), Number(c.source), st.edges);
  }, []);

  return (
    <div className="h-full w-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        isValidConnection={isValidConnection}
        nodeTypes={nodeTypes}
        defaultViewport={initialViewport}
        onMoveEnd={(_, vp) => useFlowStore.getState().setView(vp)}
        onPaneClick={() => setMenu(null)}
        onPaneContextMenu={(e) => {
          e.preventDefault();
          const pt = rf.screenToFlowPosition({ x: e.clientX, y: e.clientY });
          setMenu({ x: e.clientX, y: e.clientY, flowX: pt.x, flowY: pt.y });
        }}
        /* RF сам гасит клавиши в полях ввода (isInputDOMNode) — зеркало гарда nodes.js:1147-1151 */
        deleteKeyCode={["Delete", "Backspace"]}
        /* Shift+drag внутри edit-ноды — это marquee GeoEdit, а не рамка выделения RF.
         * RF по умолчанию слушает Shift для своей рамки и перехватывает жест даже
         * внутри ноды (d3-zoom висит на обёртке), поэтому selectionKeyCode гасим —
         * в legacy рамочного выделения нод графа не было. */
        selectionKeyCode={null}
        connectionLineStyle={{ stroke: "#9d9de8", strokeWidth: 2, strokeDasharray: "5 4" }}
      >
        <Background variant={BackgroundVariant.Dots} gap={24} size={1.5} color="#23232e" />
      </ReactFlow>
      {menu ? <CtxMenu menu={menu} onClose={() => setMenu(null)} /> : null}
    </div>
  );
}

/* Топбар — зеркало header.topbar (nodes.html): Fit, Экспорт JSON, Импорт, Очистить,
 * счётчик кэша, zoom-label */
function TopBar() {
  const { fitView, setViewport } = useReactFlow();
  const { zoom } = useViewport();
  const [cacheStat, setCacheStat] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    fetch("/api/cache/stats")
      .then((r) => r.json())
      .then((s) => {
        setCacheStat(s.hits_total > 0 ? `💾 кэш сэкономил ${s.hits_total} вызов(ов)` : "");
      })
      .catch(() => {});
  }, []);

  const onFit = () => {
    if (!useFlowStore.getState().nodes.length) {
      setViewport({ x: 80, y: 40, zoom: 1 });
      return;
    }
    void fitView();
  };

  const onExport = () => {
    downloadJson("designai-graph.json", buildExportPayload(useFlowStore.getState()));
  };

  const onImportFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    const rd = new FileReader();
    rd.onload = () => {
      try {
        useFlowStore.getState().loadGraph(parseLegacyPayload(JSON.parse(String(rd.result))));
        toast("Граф загружен", "ok");
      } catch (err) {
        toast("Не удалось прочитать JSON: " + (err instanceof Error ? err.message : String(err)), "error");
      }
    };
    rd.readAsText(f);
    e.target.value = "";
  };

  const onClear = () => {
    const st = useFlowStore.getState();
    if (!st.nodes.length) return;
    if (!window.confirm("Удалить все ноды графа?")) return;
    st.clearGraph();
  };

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b bg-background px-4">
      <span className="text-sm font-extrabold tracking-tight">
        DNA<span className="text-[#5b5bd6]">·</span>Web
      </span>
      <span className="hidden text-xs text-muted-foreground lg:inline">
        ПКМ — создать ноду · колесо — зум · drag фона — панорама
      </span>
      <div className="flex-1" />
      <span
        id="cache-stat"
        className="max-w-64 truncate text-xs text-muted-foreground"
        title="Повторные запросы reproduce/clone отданы из кэша — токены не тратились"
      >
        {cacheStat}
      </span>
      <span className="w-11 text-center text-xs tabular-nums text-muted-foreground">
        {Math.round(zoom * 100)}%
      </span>
      <Button variant="outline" size="sm" id="btn-fit" onClick={onFit}>
        ⤢ Всё
      </Button>
      <Button variant="outline" size="sm" id="btn-export" onClick={onExport}>
        Экспорт JSON
      </Button>
      <Button variant="outline" size="sm" id="btn-import" onClick={() => fileRef.current?.click()}>
        Импорт
      </Button>
      <Button variant="outline" size="sm" id="btn-clear" onClick={onClear}>
        Очистить
      </Button>
      <input ref={fileRef} type="file" accept="application/json" className="hidden" onChange={onImportFile} />
    </header>
  );
}

export default function App() {
  useEffect(() => {
    installGraphDev();
  }, []);
  return (
    <div className="flex h-full flex-col">
      <ReactFlowProvider>
        <TopBar />
        <div className="flex min-h-0 flex-1">
          <main className="min-w-0 flex-1">
            <FlowCanvas />
          </main>
          <aside className="w-72 shrink-0 overflow-y-auto border-l p-4">
            <Card>
              <CardHeader>
                <CardTitle>Инспектор</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs leading-relaxed text-muted-foreground">
                  Фаза B1: ядро графа — ноды, провода по правилам legacy, автосейв в
                  designai-flow-v1. Инспектор выбранной ноды появится в следующих фазах.
                </p>
              </CardContent>
            </Card>
          </aside>
        </div>
      </ReactFlowProvider>
      <ToastViewport />
    </div>
  );
}
