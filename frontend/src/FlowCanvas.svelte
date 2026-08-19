<script lang="ts">
  import {
    Background,
    BackgroundVariant,
    SvelteFlow,
    useSvelteFlow,
    useUpdateNodeInternals,
  } from "@xyflow/svelte";
  import type { Connection } from "@xyflow/svelte";
  import "@xyflow/svelte/dist/style.css";
  import { onMount, tick } from "svelte";

  import { CTX_ITEMS, NODE_DEFS, portsOfNode } from "./flow/ports";
  import { flow } from "./flow/state";
  import { useFlowStore } from "./flow/store";
  import { setReactFlowInstance } from "./flow/graphdev";
  import { reachable } from "./flow/dataflow";
  import type { FlowEdge, FlowNode } from "./flow/types";

  import PromptNode from "./nodes/PromptNode.svelte";
  import ReferenceNode from "./nodes/ReferenceNode.svelte";
  import GeneratorNode from "./nodes/GeneratorNode.svelte";
  import EditNode from "./nodes/EditNode.svelte";
  import MixNode from "./nodes/MixNode.svelte";
  import PageNode from "./nodes/PageNode.svelte";
  import SourceImportNode from "./nodes/SourceImportNode.svelte";
  import StyleDnaNode from "./nodes/StyleDnaNode.svelte";
  import DeriveNode from "./nodes/DeriveNode.svelte";
  import ReskinNode from "./nodes/ReskinNode.svelte";
  import QualityPassNode from "./nodes/QualityPassNode.svelte";
  import RecorderNode from "./nodes/RecorderNode.svelte";
  import MotionNode from "./nodes/MotionNode.svelte";
  import PageBridgeNode from "./nodes/PageBridgeNode.svelte";

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
  };

  type CtxMenuState = { x: number; y: number; flowX: number; flowY: number };

  // сейвовый вьюпорт читаем один раз; дальше SF управляет пан/зумом сам
  const initialViewport = useFlowStore.getState().view;

  let nodes = $state.raw<FlowNode[]>(useFlowStore.getState().nodes);
  let edges = $state.raw<FlowEdge[]>(useFlowStore.getState().edges);
  let menu = $state<CtxMenuState | null>(null);
  let pendingConnection = $state<{ nodeId: string; handleId: string } | null>(null);
  let snapNodeId: string | null = null;
  let didConnect = false;
  // Svelte Flow already moves nodes locally at pointer frequency. Mirroring
  // every intermediate position into the global store wakes every $flow
  // subscriber and both autosave pipelines, which makes drag progressively
  // sluggish on larger graphs. Commit positions once in onnodedragstop.
  let nodeDragActive = $state(false);

  const rf = useSvelteFlow();
  const updateNodeInternals = useUpdateNodeInternals();
  let measuredNodeIds = "";

  onMount(() => {
    setReactFlowInstance(rf);
    return () => setReactFlowInstance(null);
  });

  // zustand → канвас (bind:nodes/edges зеркалят стор)
  $effect(() => {
    // During a drag the bound Svelte Flow array is the presentation state.
    // Pulling the older persisted array back here would pin the node in place.
    if (nodeDragActive) return;
    const s = $flow;
    if (nodes !== s.nodes) nodes = s.nodes;
    if (edges !== s.edges) edges = s.edges;
  });

  // канвас → zustand (drag/select/remove применены библиотекой к массивам)
  $effect(() => {
    if (nodeDragActive) return;
    const st = useFlowStore.getState();
    if (st.nodes !== nodes || st.edges !== edges) st.syncFromCanvas(nodes, edges);
  });

  // Custom Svelte Flow nodes need one explicit post-DOM measurement when the
  // controlled node set changes. The bootstrap dimensions keep them visible;
  // this pass replaces those values with their real, content-driven size and
  // initializes handle bounds for connections.
  $effect(() => {
    // Do not rescan the whole controlled array at pointer frequency. Node ids
    // cannot change during a drag; the final dragstop commit re-enables this
    // effect and performs any pending measurement once.
    if (nodeDragActive) return;
    const ids = nodes.map((node) => node.id);
    const signature = ids.join("|");
    if (signature === measuredNodeIds) return;
    measuredNodeIds = signature;
    void tick().then(() => {
      requestAnimationFrame(() => {
        const dimensions = new Map<string, { width: number; height: number }>();
        document.querySelectorAll<HTMLElement>(".svelte-flow__node[data-id]").forEach((wrapper) => {
          const id = wrapper.dataset.id;
          const content = wrapper.querySelector<HTMLElement>(".fnode");
          if (!id || !content) return;
          dimensions.set(id, {
            width: Math.max(1, content.scrollWidth || content.offsetWidth),
            height: Math.max(1, content.scrollHeight || content.offsetHeight),
          });
        });
        if (dimensions.size) {
          const measuredNodes = nodes.map((node) => {
            const measured = dimensions.get(node.id);
            if (!measured) return node;
            return {
              ...node,
              initialWidth: undefined,
              initialHeight: undefined,
              measured,
            } as FlowNode;
          });
          // Publish the same array to both sides of the controlled binding so
          // the canvas-to-store mirror cannot restore the bootstrap nodes.
          nodes = measuredNodes;
          useFlowStore.setState({ nodes: measuredNodes });
        }
        void tick().then(() => updateNodeInternals(ids));
      });
    });
  });

  // переключение страницы — восстановить её вьюпорт (только на смену id,
  // иначе setViewport → onmoveend → setView зациклит эффект)
  let lastPageId: string | null = null;
  $effect(() => {
    const pid = $flow.activePageId;
    if (pid === lastPageId) return;
    lastPageId = pid;
    void rf.setViewport(useFlowStore.getState().view);
  });

  const clearSnapTarget = () => {
    if (!snapNodeId) return;
    document.querySelector(`.fnode[data-id="${snapNodeId}"]`)?.classList.remove("snap-target");
    snapNodeId = null;
  };

  const onConnect = (c: Connection) => {
    if (!c.source || !c.target || !c.sourceHandle || !c.targetHandle) return;
    didConnect = true;
    useFlowStore.getState().connect(
      { node: Number(c.source), port: c.sourceHandle },
      { node: Number(c.target), port: c.targetHandle },
    );
    pendingConnection = null;
    clearSnapTarget();
  };

  const compatibleInput = (sourceId: string, sourceHandle: string, targetId: string) => {
    const st = useFlowStore.getState();
    if (sourceId === targetId) return null;
    const src = st.nodes.find((n) => n.id === sourceId);
    const dst = st.nodes.find((n) => n.id === targetId);
    if (!src || !dst || reachable(Number(targetId), Number(sourceId), st.edges)) return null;
    const outP = portsOfNode(src).out.find((p) => p.name === sourceHandle);
    if (!outP) return null;
    return portsOfNode(dst).in.find((p) => p.kind === outP.kind) || null;
  };

  const updateSnapTarget = (clientX: number, clientY: number) => {
    if (!pendingConnection) return;
    const el = document.elementFromPoint(clientX, clientY) as HTMLElement | null;
    const nodeEl = el?.closest(".fnode") as HTMLElement | null;
    const targetId = nodeEl?.dataset.id || null;
    const canSnap = targetId
      ? compatibleInput(pendingConnection.nodeId, pendingConnection.handleId, targetId)
      : null;
    const nextId = canSnap ? targetId : null;
    if (snapNodeId === nextId) return;
    clearSnapTarget();
    if (nextId) {
      nodeEl?.classList.add("snap-target");
      snapNodeId = nextId;
    }
  };

  /* Правила 1–4 из legacy connect() (nodes.js:1049-1062); правило 5 (замена ребра)
   * живёт в store.connect, т.к. isValidConnection может только разрешить/запретить */
  const isValidConnection = (c: FlowEdge | Connection) => {
    const st = useFlowStore.getState();
    if (!c.source || !c.target || c.source === c.target) return false;
    const src = st.nodes.find((n) => n.id === c.source);
    const dst = st.nodes.find((n) => n.id === c.target);
    if (!src || !dst) return false;
    const outP = portsOfNode(src).out.find((p) => p.name === c.sourceHandle);
    const inP = portsOfNode(dst).in.find((p) => p.name === c.targetHandle);
    if (!outP || !inP || outP.kind !== inP.kind) return false;
    return !reachable(Number(c.target), Number(c.source), st.edges);
  };

  const closeMenu = () => (menu = null);
</script>

<svelte:window
  onkeydown={(e) => {
    if (menu && e.key === "Escape") closeMenu();
  }}
/>

<div
  class="h-full w-full"
  class:flow-drag-active={nodeDragActive}
  role="presentation"
  onmousemove={(e) => updateSnapTarget(e.clientX, e.clientY)}
  onmouseleave={clearSnapTarget}
>
  <SvelteFlow
    bind:nodes
    bind:edges
    {nodeTypes}
    onlyRenderVisibleElements={true}
    onconnect={onConnect}
    {isValidConnection}
    minZoom={0.1}
    onconnectstart={(_event, params) => {
      if (params.handleType === "source" && params.nodeId && params.handleId) {
        didConnect = false;
        pendingConnection = { nodeId: params.nodeId, handleId: params.handleId };
      }
    }}
    onconnectend={(event) => {
      if (!pendingConnection) return;
      if (didConnect) {
        didConnect = false;
        pendingConnection = null;
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
      pendingConnection = null;
      clearSnapTarget();
    }}
    onnodedragstart={() => {
      nodeDragActive = true;
    }}
    onnodedragstop={({ nodes: dragged }) => {
      // конец drag: округляем позицию (legacy Math.round, nodes.js:336-337)
      useFlowStore.getState().moveNodes(
        dragged.map((node) => ({ id: Number(node.id), x: node.position.x, y: node.position.y })),
      );
      nodeDragActive = false;
    }}
    {initialViewport}
    onmoveend={(_event, vp) => useFlowStore.getState().setView(vp)}
    onpaneclick={closeMenu}
    onpanecontextmenu={({ event }) => {
      event.preventDefault();
      const pt = rf.screenToFlowPosition({ x: event.clientX, y: event.clientY });
      menu = { x: event.clientX, y: event.clientY, flowX: pt.x, flowY: pt.y };
    }}
    /* SF сам гасит клавиши в полях ввода (isInputDOMNode) — зеркало гарда nodes.js:1147-1151 */
    deleteKey={["Delete", "Backspace"]}
    /* Shift+drag оставляем свободным для внутренних/оверлейных редакторских жестов. */
    selectionKey={null}
    connectionLineStyle="stroke: #d4d4d8; stroke-width: 2; stroke-dasharray: 5 4;"
  >
    <Background variant={BackgroundVariant.Dots} gap={24} size={1.5} patternColor="#23232e" />
  </SvelteFlow>
  {#if menu}
    <!-- Контекстное меню создания ноды — зеркало showCtxMenu/CTX_ITEMS (nodes.js:1096-1122) -->
    <div
      id="ctx-menu"
      style="display: block; left: {Math.max(12, Math.min(menu.x, window.innerWidth - 312))}px; top: {Math.max(12, Math.min(menu.y, window.innerHeight - 480))}px;"
    >
      <div class="ctx-cap">Создать ноду</div>
      {#each CTX_ITEMS as it (it.type)}
        <div
          class="ctx-item"
          data-type={it.type}
          role="button"
          tabindex="0"
          onkeydown={(event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            $flow.addNode(it.type, menu!.flowX, menu!.flowY);
            closeMenu();
          }}
          onclick={() => {
            $flow.addNode(it.type, menu!.flowX, menu!.flowY);
            closeMenu();
          }}
        >
          <span class="ci">{NODE_DEFS[it.type].icon}</span>
          {NODE_DEFS[it.type].title}
          <small>{it.note}</small>
        </div>
      {/each}
    </div>
  {/if}
</div>
