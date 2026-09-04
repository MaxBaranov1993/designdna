<script lang="ts">
  import {
    Background,
    BackgroundVariant,
    MiniMap,
    SvelteFlow,
    useSvelteFlow,
    useUpdateNodeInternals,
  } from "@xyflow/svelte";
  import type { Connection } from "@xyflow/svelte";
  import "@xyflow/svelte/dist/style.css";
  import { onMount, tick, untrack } from "svelte";

  import { CTX_GROUPS, NODE_DEFS, portsOfNode } from "./flow/ports";
  import { flow, flowActivePageId, flowEdges, flowNodes } from "./flow/state";
  import { useFlowStore } from "./flow/store";
  import { setReactFlowInstance } from "./flow/graphdev";
  import { reachable, WIRE_COLORS } from "./flow/dataflow";
  import type { FlowEdge, FlowNode, NodeType } from "./flow/types";
  import { OPEN_NODE_MENU_EVENT } from "./flow/ui";
  import { selectReadable } from "./lib/zustand";
  import EmptyState from "./flow/EmptyState.svelte";

  import PromptNode from "./nodes/PromptNode.svelte";
  import ReferenceNode from "./nodes/ReferenceNode.svelte";
  import GeneratorNode from "./nodes/GeneratorNode.svelte";
  import EditNode from "./nodes/EditNode.svelte";
  import MixNode from "./nodes/MixNode.svelte";
  import PageNode from "./nodes/PageNode.svelte";
  import SourceImportNode from "./nodes/SourceImportNode.svelte";
  import DesignUiNode from "./nodes/DesignUiNode.svelte";
  import DesignSystemNode from "./nodes/DesignSystemNode.svelte";
  import DeriveNode from "./nodes/DeriveNode.svelte";
  import ReskinNode from "./nodes/ReskinNode.svelte";
  import QualityPassNode from "./nodes/QualityPassNode.svelte";
  import RecorderNode from "./nodes/RecorderNode.svelte";
  import MotionNode from "./nodes/MotionNode.svelte";
  import MotionDesignNode from "./nodes/MotionDesignNode.svelte";
  import TimelineNode from "./nodes/TimelineNode.svelte";
  import PageBridgeNode from "./nodes/PageBridgeNode.svelte";
  import DnaEdge from "./flow/DnaEdge.svelte";

  /* Реестр кастомных нод — вне компонента, ключи = legacy type (конвертация данных не нужна) */
  const nodeTypes = {
    prompt: PromptNode,
    reference: ReferenceNode,
    generator: GeneratorNode,
    edit: EditNode,
    mix: MixNode,
    page: PageNode,
    sourceimport: SourceImportNode,
    designui: DesignUiNode,
    designsystem: DesignSystemNode,
    derive: DeriveNode,
    reskin: ReskinNode,
    qualitypass: QualityPassNode,
    recorder: RecorderNode,
    motion: MotionNode,
    motiondesign: MotionDesignNode,
    timeline: TimelineNode,
    pagebridge: PageBridgeNode,
  };
  const edgeTypes = { default: DnaEdge };

  type CtxMenuState = { x: number; y: number; flowX: number; flowY: number };
  type NodeMenuState = { x: number; y: number; nodeId: string };

  // сейвовый вьюпорт читаем один раз; дальше SF управляет пан/зумом сам
  const initialViewport = useFlowStore.getState().view;

  let nodes = $state.raw<FlowNode[]>(useFlowStore.getState().nodes);
  let edges = $state.raw<FlowEdge[]>(useFlowStore.getState().edges);
  let menu = $state<CtxMenuState | null>(null);
  let nodeMenu = $state<NodeMenuState | null>(null);
  let pendingConnection = $state<{ nodeId: string; handleId: string } | null>(null);
  let menuSearch = $state("");
  let canvasHost: HTMLDivElement | null = null;
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

  // Пустое состояние: страница без нод, и проект уже гидратирован (иначе на
  // desktop-профиле подсказка мигнёт, пока SQLite-снимок едет по IPC).
  const flowHydrated = selectReadable(useFlowStore, (s) => s.projectHydrated);
  let showEmptyState = $derived($flowHydrated && $flowNodes.length === 0);

  // Автофокус поиска в меню «Создать ноду»: действие вместо атрибута
  // autofocus (a11y-предупреждение svelte-check). Кадр спустя — меню уже
  // спозиционировано, фокус не дёргает скролл.
  const focusOnMount = (node: HTMLInputElement) => {
    const frame = requestAnimationFrame(() => node.focus());
    return {
      destroy() {
        cancelAnimationFrame(frame);
      },
    };
  };

  onMount(() => {
    setReactFlowInstance(rf);
    const openNodeMenu = () => {
      if (!canvasHost) return;
      const rect = canvasHost.getBoundingClientRect();
      const x = rect.left + Math.min(rect.width * 0.56, rect.width - 190);
      const y = rect.top + Math.min(rect.height * 0.34, rect.height - 260);
      const point = rf.screenToFlowPosition({ x, y });
      menuSearch = "";
      nodeMenu = null;
      menu = { x, y, flowX: point.x, flowY: point.y };
    };
    window.addEventListener(OPEN_NODE_MENU_EVENT, openNodeMenu);
    return () => {
      window.removeEventListener(OPEN_NODE_MENU_EVENT, openNodeMenu);
      setReactFlowInstance(null);
    };
  });

  // zustand → канвас (bind:nodes/edges зеркалят стор). Подписка срезами:
  // runtime-обновления busy/statuses чужих нод не будят этот эффект.
  $effect(() => {
    // During a drag the bound Svelte Flow array is the presentation state.
    // Pulling the older persisted array back here would pin the node in place.
    if (nodeDragActive) return;
    const nextNodes = $flowNodes;
    const nextEdges = $flowEdges;
    // bind-массивы читаем без подписки: иначе любое изменение из Svelte Flow
    // (клик → selected) будило этот эффект первым, и он откатывал канвас к
    // массиву стора раньше, чем эффект ниже успевал донести выделение до стора.
    // Симптом: ноды никогда не выделялись, Delete и инспектор были мертвы.
    const currentNodes = untrack(() => nodes);
    const currentEdges = untrack(() => edges);
    if (currentNodes !== nextNodes) nodes = nextNodes;
    if (currentEdges !== nextEdges) edges = nextEdges;
  });

  // канвас → zustand (drag/select/remove применены библиотекой к массивам)
  $effect(() => {
    if (nodeDragActive) return;
    // Зависимости читаем ДО ранних выходов: выход по «не гидратирован» раньше
    // чтения nodes/edges оставлял эффект без подписок до первого drag.
    const currentNodes = nodes;
    const currentEdges = edges;
    // A clean desktop profile starts with an empty presentation while the
    // canonical SQLite snapshot loads over IPC.
    if (!$flowHydrated) return;
    const st = useFlowStore.getState();
    if (st.nodes !== currentNodes || st.edges !== currentEdges) st.syncFromCanvas(currentNodes, currentEdges);
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
    // Сигнатура включает и количество портов: динамические порты Source Import
    // (блоки) появляются ПОСЛЕ монтирования ноды — без пересчёта
    // updateNodeInternals библиотека не узнаёт о новых handle и молча
    // игнорирует pointerdown (провода из блочных портов не тянутся)
    const portsSig = nodes
      .map((node) => {
        const ports = portsOfNode({ type: node.type, data: node.data });
        return `${node.id}:${ports.in.length}/${ports.out.length}`;
      })
      .join("|");
    const signature = ids.join("|") + "#" + portsSig;
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
        // Публикуем новый массив только если размеры реально изменились:
        // setState будит подписчиков стора и оба конвейера автосейва, а на
        // больших графах пересборка массива без изменений — чистые потери.
        let changed = false;
        const measuredNodes = nodes.map((node) => {
          const measured = dimensions.get(node.id);
          if (!measured) return node;
          if (node.measured?.width === measured.width
            && node.measured?.height === measured.height
            && node.initialWidth === undefined
            && node.initialHeight === undefined) return node;
          changed = true;
          return {
            ...node,
            initialWidth: undefined,
            initialHeight: undefined,
            measured,
          } as FlowNode;
        });
        if (changed) {
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
    const pid = $flowActivePageId;
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
    return portsOfNode(dst).in.find((p) => (p.kinds || [p.kind]).includes(outP.kind)) || null;
  };

  const clearPortHighlights = () => {
    document.querySelectorAll<HTMLElement>(".dna-port.in.port-can-drop, .dna-port.in.port-cannot-drop").forEach((row) => {
      row.classList.remove("port-can-drop", "port-cannot-drop");
      row.style.removeProperty("--drop-color");
    });
  };

  // Вычисляется один раз на старте провода, а не на каждом mousemove.
  const markCompatiblePorts = (sourceId: string, sourceHandle: string) => {
    clearPortHighlights();
    const st = useFlowStore.getState();
    const src = st.nodes.find((node) => node.id === sourceId);
    const out = src && portsOfNode(src).out.find((port) => port.name === sourceHandle);
    if (!out) return;
    document.querySelectorAll<HTMLElement>(".dna-port.in").forEach((row) => {
      const targetId = row.closest<HTMLElement>(".fnode")?.dataset.id || "";
      const kinds = (row.dataset.kinds || row.dataset.kind || "").split(",");
      const allowed = targetId !== sourceId && kinds.includes(out.kind)
        && !reachable(Number(targetId), Number(sourceId), st.edges);
      row.classList.add(allowed ? "port-can-drop" : "port-cannot-drop");
      if (allowed) row.style.setProperty("--drop-color", WIRE_COLORS[out.kind]);
    });
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
    if (!outP || !inP || !(inP.kinds || [inP.kind]).includes(outP.kind)) return false;
    return !reachable(Number(c.target), Number(c.source), st.edges);
  };

  const closeMenu = () => {
    menu = null;
    nodeMenu = null;
    menuSearch = "";
  };

  const connectionCount = (nodeId: string) =>
    edges.filter((edge) => edge.source === nodeId || edge.target === nodeId).length;

  let visibleGroups = $derived.by(() => {
    const query = menuSearch.trim().toLocaleLowerCase("ru");
    if (!query) return CTX_GROUPS;
    return CTX_GROUPS.map((group) => ({
      ...group,
      items: group.items.filter((item) => {
        const def = NODE_DEFS[item.type];
        return `${def.title} ${def.sub} ${item.note}`.toLocaleLowerCase("ru").includes(query);
      }),
    })).filter((group) => group.items.length);
  });
</script>

<svelte:window
  onkeydown={(e) => {
    if ((menu || nodeMenu) && e.key === "Escape") closeMenu();
    // Undo/redo структуры графа. Не перехватываем в полях ввода (у них свой
    // undo) и когда сверху открыт модальный оверлей (DNA-редактор, DS-панель,
    // таймлайн) — у них собственные стеки истории.
    if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
    const key = e.key.toLowerCase();
    const isUndo = (key === "z" || key === "я") && !e.shiftKey;
    const isRedo = key === "y" || key === "н" || ((key === "z" || key === "я") && e.shiftKey);
    if (!isUndo && !isRedo) return;
    const target = e.target as HTMLElement | null;
    if (target && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))) return;
    if (document.querySelector('[role="dialog"][aria-modal="true"], .dna-editor[data-editor-open="true"]')) return;
    e.preventDefault();
    const st = useFlowStore.getState();
    if (isUndo) st.undoGraph();
    else st.redoGraph();
  }}
/>

<div
  bind:this={canvasHost}
  class="relative h-full w-full"
  class:flow-drag-active={nodeDragActive}
  role="presentation"
  onmousemove={(e) => updateSnapTarget(e.clientX, e.clientY)}
  onmouseleave={clearSnapTarget}
>
  <SvelteFlow
    bind:nodes
    bind:edges
    {nodeTypes}
    {edgeTypes}
    onlyRenderVisibleElements={true}
    onconnect={onConnect}
    {isValidConnection}
    minZoom={0.3}
    maxZoom={2}
    panOnDrag={[0, 1]}
    onconnectstart={(_event, params) => {
      if (params.handleType === "source" && params.nodeId && params.handleId) {
        didConnect = false;
        pendingConnection = { nodeId: params.nodeId, handleId: params.handleId };
        markCompatiblePorts(params.nodeId, params.handleId);
      }
    }}
    onconnectend={(event) => {
      if (!pendingConnection) return;
      if (didConnect) {
        didConnect = false;
        pendingConnection = null;
        clearSnapTarget();
        clearPortHighlights();
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
        const exactInput = (el?.closest(".dna-port.in") as HTMLElement | null)?.dataset.port;
        const input = targetId
          ? compatibleInput(pendingConnection.nodeId, pendingConnection.handleId, targetId)
          : null;
        if (targetId && exactInput) {
          useFlowStore.getState().connect(
            { node: Number(pendingConnection.nodeId), port: pendingConnection.handleId },
            { node: Number(targetId), port: exactInput },
          );
        } else if (targetId && input) {
          useFlowStore.getState().connect(
            { node: Number(pendingConnection.nodeId), port: pendingConnection.handleId },
            { node: Number(targetId), port: input.name },
          );
        }
      }
      pendingConnection = null;
      clearSnapTarget();
      clearPortHighlights();
    }}
    onnodedragstart={() => {
      nodeDragActive = true;
    }}
    onnodedragstop={({ targetNode, nodes: dragged }) => {
      // конец drag: округляем позицию (legacy Math.round, nodes.js:336-337)
      useFlowStore.getState().moveNodes(
        dragged.map((node) => ({ id: Number(node.id), x: node.position.x, y: node.position.y })),
      );
      nodeDragActive = false;
      // Выделение, которое Svelte Flow сделал на старте drag, живёт только в
      // bind-массиве (эффект «канвас → стор» на время drag выключен). Переносим
      // его в стор сами, иначе «стор → канвас» вернёт старый массив и снимет
      // выделение с только что перетащенной ноды. Позиции — из стора (округлены).
      const st = useFlowStore.getState();
      const byId = new Map(st.nodes.map((node) => [node.id, node.position]));
      // The drag event is sourced from Svelte Flow's internal lookup and is
      // therefore authoritative for selection even when the controlled
      // `nodes` binding has not published its pointer-down update yet.
      const selectedIds = new Set(
        dragged.filter((node) => node.selected).map((node) => node.id),
      );
      // Defensive fallback for library versions that omit `selected` from the
      // drag payload: a single-node drag still selects its target.
      if (!selectedIds.size && targetNode) selectedIds.add(targetNode.id);
      const merged = nodes.map((node) => {
        const position = byId.get(node.id);
        const selected = selectedIds.has(node.id);
        if ((position && position !== node.position) || node.selected !== selected) {
          return { ...node, ...(position ? { position } : {}), selected };
        }
        return node;
      });
      if (st.nodes !== nodes || st.edges !== edges) st.syncFromCanvas(merged, edges);
    }}
    {initialViewport}
    onmoveend={(_event, vp) => useFlowStore.getState().setView(vp)}
    onpaneclick={closeMenu}
    onnodecontextmenu={({ event, node }) => {
      event.preventDefault();
      event.stopPropagation();
      menu = null;
      menuSearch = "";
      nodeMenu = { x: event.clientX, y: event.clientY, nodeId: node.id };
    }}
    onpanecontextmenu={({ event }) => {
      event.preventDefault();
      const pt = rf.screenToFlowPosition({ x: event.clientX, y: event.clientY });
      nodeMenu = null;
      menu = { x: event.clientX, y: event.clientY, flowX: pt.x, flowY: pt.y };
    }}
    /* SF сам гасит клавиши в полях ввода (isInputDOMNode) — зеркало гарда nodes.js:1147-1151 */
    deleteKey={["Delete", "Backspace"]}
    /* Shift+drag оставляем свободным для внутренних/оверлейных редакторских жестов. */
    selectionKey={[]}
    connectionLineStyle="stroke: #d4d4d8; stroke-width: 2; stroke-dasharray: 5 4;"
  >
    <Background variant={BackgroundVariant.Dots} gap={26} size={1} patternColor="#1B1B22" />
    <MiniMap
      pannable
      zoomable
      maskColor="rgba(10,10,12,.72)"
      bgColor="#101013"
      nodeColor={(node) => node.type ? NODE_DEFS[node.type as NodeType].accent : "#9B5CFF"}
    />
    <div class="dna-minimap-label"></div>
  </SvelteFlow>
  {#if showEmptyState}
    <EmptyState onfit={() => void rf.fitView({ padding: 0.12, duration: 250 })} />
  {/if}
  {#if menu}
    <!-- Контекстное меню создания ноды — зеркало showCtxMenu/CTX_ITEMS (nodes.js:1096-1122) -->
    <div
      id="ctx-menu"
      style="display: block; left: {Math.max(12, Math.min(menu.x, window.innerWidth - 312))}px; top: {Math.max(12, Math.min(menu.y, window.innerHeight - 480))}px;"
    >
      <div class="ctx-head"><div class="ctx-cap">СОЗДАТЬ НОДУ</div><span class="ctx-esc">ESC</span></div>
      <div class="ctx-search-wrap">
        <input
          class="ctx-search"
          bind:value={menuSearch}
          use:focusOnMount
          placeholder="Найти тип ноды…"
          aria-label="Найти тип ноды"
        />
      </div>
      <div class="ctx-list">
        {#each visibleGroups as group (group.label)}
          <div class="ctx-group-cap" style="color: {group.color}">{group.label}</div>
          {#each group.items as item (item.type)}
            <div
              class="ctx-item"
              data-type={item.type}
              role="button"
              tabindex="0"
              onkeydown={(event) => {
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
                $flow.addNode(item.type, menu!.flowX, menu!.flowY);
                closeMenu();
              }}
              onclick={() => {
                $flow.addNode(item.type, menu!.flowX, menu!.flowY);
                closeMenu();
              }}
            >
              <span class:wide={NODE_DEFS[item.type].icon.length > 2} class="ci" style="background: color-mix(in srgb, {NODE_DEFS[item.type].accent}, transparent 86%); color: {NODE_DEFS[item.type].accent}">
                {NODE_DEFS[item.type].icon}
              </span>
              <span class="ctx-title">{NODE_DEFS[item.type].title}</span>
              <small>{item.note}</small>
            </div>
          {/each}
        {/each}
        {#if !visibleGroups.length}<div class="ctx-none">Ничего не найдено</div>{/if}
      </div>
    </div>
  {/if}
  {#if nodeMenu}
    {@const selectedNode = nodes.find((node) => node.id === nodeMenu!.nodeId)}
    {@const links = connectionCount(nodeMenu.nodeId)}
    <div
      id="node-ctx-menu"
      style="left: {Math.max(12, Math.min(nodeMenu.x, window.innerWidth - 252))}px; top: {Math.max(12, Math.min(nodeMenu.y, window.innerHeight - 132))}px;"
    >
      <div class="node-ctx-head">
        <span>{selectedNode?.type ? NODE_DEFS[selectedNode.type as NodeType].title : "Нода"}</span>
        <small>{links} {links === 1 ? "связь" : "связей"}</small>
      </div>
      <button
        type="button"
        data-act="disconnect-node"
        disabled={!links}
        onclick={() => {
          $flow.disconnectNode(Number(nodeMenu!.nodeId));
          closeMenu();
        }}
      >
        <span aria-hidden="true">⌁</span>
        <span><strong>Разорвать связи</strong><small>Нода и её данные сохранятся</small></span>
      </button>
    </div>
  {/if}
</div>
