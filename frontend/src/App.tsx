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
import { getConfig } from "./flow/api";
import { EditNode } from "./nodes/EditNode";
import { GeneratorNode } from "./nodes/GeneratorNode";
import { MixNode } from "./nodes/MixNode";
import { PageNode } from "./nodes/PageNode";
import { PromptNode } from "./nodes/PromptNode";
import { ReferenceNode } from "./nodes/ReferenceNode";
import { ReskinNode } from "./nodes/ReskinNode";
import { QualityPassNode } from "./nodes/QualityPassNode";
import { SourceImportNode } from "./nodes/SourceImportNode";
import { StyleDnaNode } from "./nodes/StyleDnaNode";
import { DeriveNode } from "./nodes/DeriveNode";
import { PageBridgeNode } from "./nodes/PageBridgeNode";
import { RecorderNode } from "./nodes/RecorderNode";
import { MotionNode } from "./nodes/MotionNode";
import { EditorApp } from "./editor/EditorApp";
import { ProjectMapPanel } from "./desktop/ProjectMapPanel";
import { AgentWorkspace } from "./desktop/AgentWorkspace";

/* Реестр кастомных нод — вне компонента, ключи = legacy type (конвертация данных не нужна) */
const nodeTypes = {
  prompt: PromptNode,
  reference: ReferenceNode,
  generator: GeneratorNode,
  edit: EditNode,
  mix: MixNode,
  page: PageNode,
  sourceimport: SourceImportNode,
  styledna: StyleDnaNode,
  derive: DeriveNode,
  reskin: ReskinNode,
  qualitypass: QualityPassNode,
  recorder: RecorderNode,
  motion: MotionNode,
  pagebridge: PageBridgeNode,
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
  const activePageId = useFlowStore((s) => s.activePageId);
  const [menu, setMenu] = useState<CtxMenuState | null>(null);
  const [pendingConnection, setPendingConnection] = useState<{ nodeId: string; handleId: string } | null>(null);
  // сейвовый вьюпорт читаем один раз; дальше RF управляет пан/зумом сам
  const [initialViewport] = useState(() => useFlowStore.getState().view);
  const rf = useReactFlow();
  const snapNodeRef = useRef<string | null>(null);
  const didConnectRef = useRef(false);

  useEffect(() => {
    setReactFlowInstance(rf);
    return () => setReactFlowInstance(null);
  }, [rf]);

  useEffect(() => {
    const view = useFlowStore.getState().view;
    void rf.setViewport(view);
  }, [activePageId, rf]);

  const clearSnapTarget = useCallback(() => {
    if (!snapNodeRef.current) return;
    document
      .querySelector(`.fnode[data-id="${snapNodeRef.current}"]`)
      ?.classList.remove("snap-target");
    snapNodeRef.current = null;
  }, []);

  const onConnect = useCallback((c: Connection) => {
    if (!c.source || !c.target || !c.sourceHandle || !c.targetHandle) return;
    didConnectRef.current = true;
    useFlowStore.getState().connect(
      { node: Number(c.source), port: c.sourceHandle },
      { node: Number(c.target), port: c.targetHandle },
    );
    setPendingConnection(null);
    clearSnapTarget();
  }, [clearSnapTarget]);

  const compatibleInput = useCallback((sourceId: string, sourceHandle: string, targetId: string) => {
    const st = useFlowStore.getState();
    if (sourceId === targetId) return null;
    const src = st.nodes.find((n) => n.id === sourceId);
    const dst = st.nodes.find((n) => n.id === targetId);
    if (!src || !dst || reachable(Number(targetId), Number(sourceId), st.edges)) return null;
    const outP = portsOfNode(src).out.find((p) => p.name === sourceHandle);
    if (!outP) return null;
    return portsOfNode(dst).in.find((p) => p.kind === outP.kind) || null;
  }, []);

  const updateSnapTarget = useCallback(
    (clientX: number, clientY: number) => {
      if (!pendingConnection) return;
      const el = document.elementFromPoint(clientX, clientY) as HTMLElement | null;
      const nodeEl = el?.closest(".fnode") as HTMLElement | null;
      const targetId = nodeEl?.dataset.id || null;
      const canSnap = targetId
        ? compatibleInput(pendingConnection.nodeId, pendingConnection.handleId, targetId)
        : null;
      const nextId = canSnap ? targetId : null;
      if (snapNodeRef.current === nextId) return;
      clearSnapTarget();
      if (nextId) {
        nodeEl?.classList.add("snap-target");
        snapNodeRef.current = nextId;
      }
    },
    [clearSnapTarget, compatibleInput, pendingConnection],
  );

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
    <div
      className="h-full w-full"
      onMouseMove={(e) => updateSnapTarget(e.clientX, e.clientY)}
      onMouseLeave={clearSnapTarget}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        isValidConnection={isValidConnection}
        nodeTypes={nodeTypes}
        onConnectStart={(_, params) => {
          if (params.handleType === "source" && params.nodeId && params.handleId) {
            didConnectRef.current = false;
            setPendingConnection({ nodeId: params.nodeId, handleId: params.handleId });
          }
        }}
        onConnectEnd={(event) => {
          if (!pendingConnection) return;
          if (didConnectRef.current) {
            didConnectRef.current = false;
            setPendingConnection(null);
            clearSnapTarget();
            return;
          }
          const point =
            "changedTouches" in event && event.changedTouches.length
              ? event.changedTouches[0]
              : event instanceof MouseEvent
                ? event
                : null;
          if (point) {
            const el = document.elementFromPoint(point.clientX, point.clientY) as HTMLElement | null;
            const targetId = (el?.closest(".fnode") as HTMLElement | null)?.dataset.id;
            const input = targetId
              ? compatibleInput(pendingConnection.nodeId, pendingConnection.handleId, targetId)
              : null;
            if (targetId && input) {
              useFlowStore.getState().connect(
                { node: Number(pendingConnection.nodeId), port: pendingConnection.handleId },
                { node: Number(targetId), port: input.name },
              );
            }
          }
          setPendingConnection(null);
          clearSnapTarget();
        }}
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
        /* Shift+drag оставляем свободным для внутренних/оверлейных редакторских жестов.
         * RF по умолчанию слушает Shift для своей рамки и может перехватывать drag
         * поверх кастомных поверхностей, поэтому selectionKeyCode гасим. */
        selectionKeyCode={null}
        connectionLineStyle={{ stroke: "#d4d4d8", strokeWidth: 2, strokeDasharray: "5 4" }}
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
        DNA<span className="text-muted-foreground">·</span>Web
      </span>
      <span className="hidden text-xs text-muted-foreground lg:inline">
        ПКМ — создать ноду · колесо — зум · drag фона — панорама
      </span>
      <div className="flex-1" />
      <span
        id="cache-stat"
        className="max-w-64 truncate text-xs text-muted-foreground"
        title="Повторные запросы Source Import отданы из кэша — токены не тратились"
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

function PagesPanel() {
  const pages = useFlowStore((s) => s.pages);
  const activePageId = useFlowStore((s) => s.activePageId);
  const nodes = useFlowStore((s) => s.nodes);
  const channels = useFlowStore((s) => s.channels);
  const createPage = useFlowStore((s) => s.createPage);
  const switchPage = useFlowStore((s) => s.switchPage);
  const renamePage = useFlowStore((s) => s.renamePage);
  const deletePage = useFlowStore((s) => s.deletePage);

  const countNodes = (pageId: string) => {
    if (pageId === activePageId) return nodes.length;
    return pages.find((page) => page.id === pageId)?.nodes.length || 0;
  };
  const channelNames = Object.keys(channels).filter((key) => channels[key]);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <CardTitle>Страницы</CardTitle>
          <Button variant="outline" size="sm" onClick={() => createPage()}>
            + Page
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="page-list">
          {pages.map((page) => (
            <div key={page.id} className={page.id === activePageId ? "page-row active" : "page-row"}>
              <button className="page-switch" onClick={() => switchPage(page.id)}>
                <span>{page.name}</span>
                <small>{countNodes(page.id)} nodes</small>
              </button>
              <input
                className="page-name"
                value={page.name}
                onChange={(e) => renamePage(page.id, e.target.value)}
                aria-label="Page name"
              />
              <button
                className="page-delete"
                disabled={pages.length <= 1}
                onClick={() => {
                  if (window.confirm(`Удалить страницу "${page.name}"?`)) deletePage(page.id);
                }}
                title="Удалить страницу"
              >
                ×
              </button>
            </div>
          ))}
        </div>
        <div className="page-channels">
          <div className="panel-label">Bridge channels</div>
          {channelNames.length ? (
            channelNames.map((name) => (
              <div key={name} className="channel-row">
                <span>{name}</span>
                <small>IR</small>
              </div>
            ))
          ) : (
            <p className="text-xs leading-relaxed text-muted-foreground">
              Создайте Page Bridge: Send на одной странице и Receive на другой с тем же channel.
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

type WorkspaceSurface = "design" | "map" | "agents";

export default function App() {
  const [surface, setSurface] = useState<WorkspaceSurface>("design");

  useEffect(() => {
    installGraphDev();
    void useFlowStore.getState().loadPersistedProject();
    // Load runtime config/feature flags once on boot. Failures are non-fatal.
    void getConfig().catch(() => ({ flags: {} }));
  }, []);

  return (
    <div className="flex h-full flex-col">
      <nav className="flex h-11 shrink-0 items-center justify-between border-b bg-background px-3">
        <strong className="text-sm tracking-tight">DesignDNA</strong>
        <div className="flex rounded-lg border bg-muted/50 p-0.5" aria-label="Workspace surface">
          <Button variant={surface === "design" ? "default" : "ghost"} size="sm" onClick={() => setSurface("design")}>
            Design
          </Button>
          <Button variant={surface === "map" ? "default" : "ghost"} size="sm" onClick={() => setSurface("map")}>
            Project Map
          </Button>
          <Button variant={surface === "agents" ? "default" : "ghost"} size="sm" onClick={() => setSurface("agents")}>
            Agents
          </Button>
        </div>
        <span className="text-[11px] text-muted-foreground">{window.designDNA ? "Desktop · local" : "Browser mode"}</span>
      </nav>
      <div className="min-h-0 flex-1">
        {surface === "design" ? (
          <div className="flex h-full flex-col">
            <ReactFlowProvider>
              <TopBar />
              <div className="flex min-h-0 flex-1">
                <aside className="w-72 shrink-0 space-y-4 overflow-y-auto border-r p-4">
                  <PagesPanel />
                  <Card>
                    <CardHeader>
                      <CardTitle>Инспектор</CardTitle>
                    </CardHeader>
                    <CardContent>
                      <p className="text-xs leading-relaxed text-muted-foreground">
                        Design IR — единый источник истины для графа, редактора DNA и генерации.
                      </p>
                    </CardContent>
                  </Card>
                </aside>
                <main className="min-w-0 flex-1">
                  <FlowCanvas />
                </main>
              </div>
            </ReactFlowProvider>
            <ToastViewport />
            <EditorApp />
          </div>
        ) : surface === "map" ? (
          <ProjectMapPanel />
        ) : (
          <AgentWorkspace />
        )}
      </div>
    </div>
  );
}
