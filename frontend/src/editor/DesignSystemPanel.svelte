<script lang="ts">
  /* Design System Editor (ТЗ §12): библиотека foundations/компонентов/states/mock,
   * канвас мастер-компонента с viewport-переключением, инспектор, validation,
   * publish. Переиспользует IrPreview (тот же рендерер, что DNA Editor). */

  import { flow, flowBusy, flowNodes } from "../flow/state";
  import type { DesignSystemNodeData, IRObject } from "../flow/types";
  import SourceArtifactPanel from "./SourceArtifactPanel.svelte";
  import { useEditorStore } from "./store";

  let { nodeId, onClose }: { nodeId: number; onClose: () => void } = $props();

  const data = $derived.by(() => {
    const node = $flowNodes.find((n) => Number(n.id) === Number(nodeId));
    return ((node?.data || {}) as unknown) as DesignSystemNodeData;
  });

  let activeTab = $state<"source" | "styleguide" | "foundations" | "components" | "suggestions" | "mock" | "identity" | "archetypes" | "tests" | "proof" | "validation">("source");
  type CatalogPool = "components" | "review" | "suggestions";
  type CatalogEntry = { key: string; pool: CatalogPool; component: Record<string, any> };
  let selectedKey = $state<string>("");
  let selectedPool = $state<CatalogPool>("components");
  let selectedVariant = $state("default");
  let componentSearch = $state("");
  let viewport = $state<"desktop" | "tablet" | "mobile">("desktop");
  let fixtureProfile = $state("source");
  let previewMode = $state<"reference" | "master" | "compare">("compare");
  let publishing = $state(false);
  let validating = $state(false);
  let applying = $state(false);
  let saving = $state(false);
  let organizing = $state(false);
  let organizerEffort = $state<"medium" | "high" | "max">("high");
  /* AI-ревью стиля: провайдер выбирается пользователем (Sol/Codex/Claude);
   * в desktop промпт готовит сервер, отвечает выбранный аккаунт, применяет
   * и валидирует снова сервер — креденшелы не покидают main-процесс. */
  let reviewing = $state(false);
  let reviewProvider = $state<"openai" | "codex" | "claude">("openai");
  let reviewEffort = $state<"medium" | "high" | "max">("high");
  let actionError = $state("");
  let validationResult = $state<{ errors: Array<{ message: string }> } | null>(null);
  let identityResult = $state<any>(null);
  let proofRunning = $state(false);

  const doc = $derived((data.document || {}) as Record<string, any>);
  const sourceArtifact = $derived.by(() => {
    const source = $flowNodes.find((node) => Number(node.id) === Number(data.sourceNodeId));
    if (source?.type === "sourceimport") return source.data.sourceArtifact || null;
    return doc.sourceArtifact || null;
  });
  const components = $derived(Object.entries(doc.components || {}) as Array<[string, any]>);
  const reviewComponents = $derived(Object.entries(doc.reviewComponents || {}) as Array<[string, any]>);
  const suggestions = $derived(Object.entries(doc.suggestions || {}) as Array<[string, any]>);
  const catalogEntries = $derived.by((): CatalogEntry[] => {
    const entries: CatalogEntry[] = components.map(([key, component]) => ({ key, pool: "components", component }));
    const known = new Set(entries.map((entry) => entry.key));
    for (const [key, component] of reviewComponents) {
      if (!known.has(key)) entries.push({ key, pool: "review", component });
      known.add(key);
    }
    // Older drafts stored exact fidelity-review masters in suggestions. Keep
    // them visible until Source Sync migrates them to reviewComponents.
    for (const [key, component] of suggestions) {
      if (component?.origin === "observed" && !known.has(key)) {
        entries.push({ key, pool: "suggestions", component });
        known.add(key);
      }
    }
    return entries;
  });
  const semanticSuggestions = $derived(suggestions.filter(([, component]) => component?.origin !== "observed"));
  const foundations = $derived(doc.foundations || {});
  const styleGuide = $derived((doc.styleGuide || {}) as Record<string, any>);
  const styleTokens = $derived(Object.entries(styleGuide.tokens || {}) as Array<[string, unknown]>);
  const styleReview = $derived((styleGuide.review || null) as Record<string, any> | null);
  const identity = $derived(doc.identity || {});
  const identityTests = $derived((doc.identityTests || []) as any[]);
  const archetypes = $derived((identity.archetypes || []) as any[]);
  const reconstruction = $derived(doc.reconstruction || {});
  const catalog = $derived((doc.catalog || {}) as Record<string, any>);
  const mockSchemas = $derived(Object.entries(doc.mockData?.schemas || {}) as Array<[string, any]>);
  const selectedComp = $derived(selectedKey ? (
    selectedPool === "review" ? (doc.reviewComponents || {})[selectedKey]
      : selectedPool === "suggestions" ? (doc.suggestions || {})[selectedKey]
        : (doc.components || {})[selectedKey]
  ) : null);
  const selectedVariantData = $derived((selectedComp?.variants || {})[selectedVariant] || (selectedComp?.variants || {}).default || null);
  const selectedObservedStyle = $derived((selectedVariantData?.observedStyle || {}) as Record<string, any>);
  const componentGroups = $derived.by(() => {
    const query = componentSearch.trim().toLowerCase();
    const byKey = new Map(catalogEntries.map((entry) => [entry.key, entry]));
    const groups: Array<[string, CatalogEntry[]]> = [];
    const seen = new Set<string>();
    const accept = (entry: CatalogEntry) => {
      const { key, component } = entry;
      const semantic = catalog.componentMeta?.[key] || {};
      const haystack = `${key} ${component.name || ""} ${component.category || ""} ${semantic.label || ""} ${semantic.role || ""}`.toLowerCase();
      return !query || haystack.includes(query);
    };
    for (const section of catalog.sections || []) {
      const items = (section.componentKeys || [])
        .map((key: string) => byKey.get(key))
        .filter((entry: CatalogEntry | undefined): entry is CatalogEntry => !!entry && accept(entry));
      for (const entry of items) seen.add(entry.key);
      if (items.length) groups.push([String(section.label || section.key), items]);
    }
    const fallback = new Map<string, CatalogEntry[]>();
    for (const entry of catalogEntries) {
      if (seen.has(entry.key) || !accept(entry)) continue;
      const { component } = entry;
      const category = String(component.category || "Other");
      fallback.set(category, [...(fallback.get(category) || []), entry]);
    }
    return [...groups, ...Array.from(fallback.entries())];
  });
  const selectedIsSuggestion = $derived(selectedPool === "suggestions" && !!selectedComp);
  const selectedIsReview = $derived(
    !!selectedComp && (selectedPool === "review" || (selectedPool === "suggestions" && selectedComp?.origin === "observed"))
  );
  const selectedCanPromote = $derived(
    selectedIsSuggestion && selectedComp?.origin !== "observed" && !!selectedComp?.templateIr
  );
  const hasSelection = $derived(!!selectedComp);

  function displayStyleValue(value: unknown): string {
    if (Array.isArray(value)) return value.join(" / ");
    if (value && typeof value === "object") return JSON.stringify(value);
    return String(value ?? "—");
  }

  let previewHost = $state<HTMLElement | null>(null);
  let snapshot = $state("");
  let snapshotRef: Record<string, unknown> | null = null;
  let undoStack = $state<string[]>([]);
  let appliedEdit = $state<{ editNodeId: number; previousIr: IRObject | null } | null>(null);
  let previewIr = $state<IRObject | null>(null);
  let previewMeta = $state<{
    usageMode?: string;
    fixture?: string;
    sourceRef?: Record<string, any>;
    fidelity?: Record<string, any>;
  } | null>(null);
  const selectedSourceRef = $derived((previewMeta?.sourceRef || selectedVariantData?.sourceRef || selectedComp?.sourceRef || {}) as Record<string, any>);
  const fidelityMetrics = $derived((previewMeta?.fidelity?.viewports?.[viewport]
    || selectedVariantData?.fidelity?.viewports?.[viewport]
    || selectedComp?.fidelity?.viewports?.[viewport] || {}) as Record<string, any>);
  let previewRequest = 0;
  let rendererReady = false;

  /* JSON документа нужен только для сравнения dirty: мемоизация по ссылке
   * объекта — ссылка data.document меняется только при реальном изменении
   * ноды, иначе любой set стора пересериализовывал бы весь документ. */
  const jsonMemo = new WeakMap<object, string>();
  function memoJson(value: Record<string, unknown> | null | undefined): string {
    if (!value || typeof value !== "object") return "{}";
    const hit = jsonMemo.get(value);
    if (hit !== undefined) return hit;
    const text = JSON.stringify(value);
    jsonMemo.set(value, text);
    return text;
  }

  /* Документ в ноде — кэш редактирования: после publish/restore нода хранит
   * только systemId@revision, полную копию подтягиваем по ссылке. */
  let refLoading = false;
  $effect(() => {
    const current = data;
    if (!current.document && current.systemId && !refLoading) {
      refLoading = true;
      void (async () => {
        try {
          const resp = await fetch("/api/design-system/get", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ systemId: current.systemId, revision: Number(current.revision) || 0 }),
          });
          const got = await resp.json();
          if (got.document) $flow.setNodeData(Number(nodeId), { document: got.document });
        } catch {
          /* документ недоступен — панель останется пустой, правка создаст новый */
        } finally {
          refLoading = false;
        }
      })();
    }
  });

  $effect(() => {
    const document = data.document;
    if (document && document !== snapshotRef) {
      snapshotRef = document;
      snapshot = memoJson(document);
    }
  });

  const dirty = $derived(!!snapshot && memoJson(data.document) !== snapshot);
  const busy = $derived(publishing || validating || applying || saving || organizing || reviewing || !!$flowBusy[Number(nodeId)]);

  $effect(() => {
    if (activeTab === "components" && catalogEntries.length && !selectedComp) {
      selectedPool = catalogEntries[0].pool;
      selectedKey = catalogEntries[0].key;
      selectedVariant = "default";
    }
  });

  $effect(() => {
    if (selectedComp && !(selectedComp.variants || {})[selectedVariant]) selectedVariant = "default";
  });

  async function loadRenderer() {
    if (rendererReady) return;
    const existing = document.querySelector('script[data-engine]');
    if (!existing) {
      const script = document.createElement("script");
      script.src = "/static/flow/engine.js";
      script.dataset.engine = "1";
      document.head.appendChild(script);
      await new Promise((resolve) => { script.onload = resolve; script.onerror = resolve; });
    }
    rendererReady = !!(window as any).IRRenderer;
  }

  function renderSelected() {
    if (!previewHost) return;
    previewHost.innerHTML = "";
    const variantMaster = selectedVariantData?.masterRef === "self"
      ? selectedComp?.masterIr
      : selectedVariantData?.masterIr;
    const ir = previewIr || variantMaster || selectedComp?.templateIr || selectedComp?.masterIr;
    if (!ir) return;
    const reference = String(previewMeta?.sourceRef?.referencePreviews?.[viewport] || "");
    const stage = document.createElement("div");
    stage.className = `ds-preview-stage ds-preview-${previewMode}`;
    previewHost.appendChild(stage);
    let masterContainer: HTMLDivElement | null = null;

    if (reference && previewMode !== "master") {
      const referencePane = document.createElement("figure");
      referencePane.className = "ds-preview-pane ds-reference-pane";
      const label = document.createElement("figcaption");
      const sourceRef = previewMeta?.sourceRef || {};
      const bounds = sourceRef.boundsByViewport?.[viewport] || sourceRef.bounds || {};
      const blockSize = sourceRef.blockSizes?.[viewport] || {};
      const canCrop = [bounds.x || 0, bounds.y || 0, bounds.width, bounds.height,
        blockSize.width, blockSize.height].every((value) => Number.isFinite(Number(value)))
        && Number(bounds.width) > 0 && Number(bounds.height) > 0
        && Number(blockSize.width) > 0 && Number(blockSize.height) > 0;
      label.textContent = canCrop ? "Source crop" : "Source reference";
      const image = document.createElement("img");
      image.alt = `${selectedComp?.name || "Component"} · Source ${viewport}`;
      referencePane.append(label, image);
      stage.appendChild(referencePane);
      if (canCrop) {
        const renderCrop = () => {
          const scaleX = image.naturalWidth / Number(blockSize.width);
          const scaleY = image.naturalHeight / Number(blockSize.height);
          const sx = Math.max(0, Number(bounds.x || 0) * scaleX);
          const sy = Math.max(0, Number(bounds.y || 0) * scaleY);
          const sw = Math.min(image.naturalWidth - sx, Number(bounds.width) * scaleX);
          const sh = Math.min(image.naturalHeight - sy, Number(bounds.height) * scaleY);
          if (sw <= 0 || sh <= 0) return;
          const canvas = document.createElement("canvas");
          canvas.width = Math.max(1, Math.round(sw));
          canvas.height = Math.max(1, Math.round(sh));
          const context = canvas.getContext("2d");
          if (!context) return;
          context.drawImage(image, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
          image.replaceWith(canvas);
          if (masterContainer && previewMode === "compare") {
            masterContainer.style.width = `${Number(bounds.width)}px`;
            requestAnimationFrame(() => {
              if (!masterContainer) return;
              const paneWidth = masterContainer.parentElement?.clientWidth || Number(bounds.width);
              const displayScale = Math.min(1, paneWidth / Number(bounds.width));
              masterContainer.style.zoom = String(displayScale);
            });
          }
        };
        image.onload = renderCrop;
      }
      image.src = reference;
      if (canCrop && image.complete && image.naturalWidth > 0) image.onload?.(new Event("load"));
    }
    if (previewMode === "reference" && reference) return;

    const renderPane = document.createElement("figure");
    renderPane.className = "ds-preview-pane ds-master-pane";
    const renderLabel = document.createElement("figcaption");
    renderLabel.textContent = fixtureProfile === "source" ? "Exact master IR" : `Master · mock ${fixtureProfile}`;
    const container = document.createElement("div");
    masterContainer = container;
    container.className = "ir-preview";
    container.setAttribute("data-ds-preview", viewport);
    container.style.cssText = "width:100%;min-height:0;overflow:hidden;";
    renderPane.append(renderLabel, container);
    stage.appendChild(renderPane);
    try {
      const renderer = (window as any).IRRenderer;
      if (renderer) renderer.renderIR(container, JSON.parse(JSON.stringify(ir)), { viewport });
      else container.textContent = "IRRenderer не загружен";
    } catch (e) {
      container.textContent = "Ошибка рендера: " + String(e).slice(0, 100);
    }
  }

  async function refreshPreviewMeta() {
    if (!selectedKey || !data.document) return;
    const requestId = ++previewRequest;
    try {
      const resp = await fetch("/api/design-system/preview", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          document: data.document, componentKey: selectedKey,
          variantKey: selectedVariant, fixtureProfile, usageMode: "strict",
        }),
      });
      const result = await resp.json();
      if (requestId !== previewRequest) return;
      if (!resp.ok || result.error) throw new Error(result.error || `HTTP ${resp.status}`);
      previewIr = result.templateIr || null;
      previewMeta = {
        usageMode: result.usageMode,
        fixture: result.fixture?.profile || fixtureProfile,
        sourceRef: result.sourceRef || selectedVariantData?.sourceRef || selectedComp?.sourceRef || {},
        fidelity: result.fidelity || selectedVariantData?.fidelity || selectedComp?.fidelity || {},
      };
    } catch {
      if (requestId !== previewRequest) return;
      previewIr = (selectedVariantData?.masterIr || selectedComp?.templateIr || selectedComp?.masterIr || null) as IRObject | null;
      previewMeta = {
        usageMode: "strict", fixture: fixtureProfile,
        sourceRef: selectedVariantData?.sourceRef || selectedComp?.sourceRef || {},
        fidelity: selectedVariantData?.fidelity || selectedComp?.fidelity || {},
      };
    }
  }

  $effect(() => {
    selectedKey;
    selectedPool;
    selectedVariant;
    data.document;
    fixtureProfile;
    previewIr = null;
    if (selectedComp) void refreshPreviewMeta();
  });

  $effect(() => {
    selectedComp;
    viewport;
    previewMode;
    previewIr;
    previewMeta;
    previewHost;
    if (selectedComp && previewHost) {
      void loadRenderer().then(renderSelected);
    }
  });

  function pushUndo() {
    undoStack = [...undoStack, memoJson(data.document)].slice(-30);
  }

  async function persist(next: Record<string, unknown>) {
    saving = true;
    actionError = "";
    try {
      const ok = await $flow.saveDesignSystemDocument(Number(nodeId), next);
      if (!ok) actionError = String(data.lastError || "Не удалось сохранить черновик");
      return ok;
    } finally {
      saving = false;
    }
  }

  async function restoreDocument(next: Record<string, unknown>) {
    const published = next.status === "published" && Number(next.revision || 0) > 0 && next.id;
    if (published) {
      saving = true;
      actionError = "";
      try {
        const ok = await $flow.restorePublishedDesignSystem(Number(nodeId), {
          systemId: String(next.id),
          revision: Number(next.revision),
        });
        if (!ok) actionError = String(data.lastError || "Не удалось восстановить опубликованную ревизию");
        return ok;
      } finally {
        saving = false;
      }
    }
    return persist(next);
  }

  const originIcon = (origin: string) => origin === "observed" ? "⬤" : origin === "suggested" || origin === "inferred" ? "◐" : origin === "user" ? "◆" : "◇";

  function selectCatalogComponent(key: string, pool: CatalogPool) {
    selectedKey = key;
    selectedPool = pool;
    selectedVariant = "default";
    activeTab = "components";
  }

  function selectSuggestion(key: string) {
    selectedKey = key;
    selectedPool = "suggestions";
    selectedVariant = "default";
    activeTab = "suggestions";
  }

  async function promoteSuggestion() {
    if (!selectedCanPromote || !selectedKey) return;
    const next = JSON.parse(JSON.stringify(doc));
    const suggestion = next.suggestions?.[selectedKey];
    if (!suggestion?.templateIr) return;
    pushUndo();
    let key = selectedKey;
    let suffix = 2;
    while (next.components?.[key]) key = `${selectedKey}-${suffix++}`;
    const master = JSON.parse(JSON.stringify(suggestion.templateIr));
    next.components ||= {};
    next.components[key] = {
      ...suggestion,
      componentKey: key,
      origin: "user",
      status: "verified",
      confidence: 1,
      confirmed: true,
      masterIr: master,
      variants: {
        default: { label: "Promoted", origin: "user", confirmed: true,
          masterRef: "self", diff: {} },
      },
      provenance: { ...(suggestion.provenance || {}), promotion: "explicit-user-action" },
    };
    delete next.suggestions[selectedKey];
    if (next.extraction) next.extraction.suggestionCount = Object.keys(next.suggestions || {}).length;
    if (next.provenance) next.provenance.suggestedCount = Object.keys(next.suggestions || {}).length;
    next.status = "draft";
    const ok = await persist(next);
    if (ok) {
      selectedKey = key;
      selectedPool = "components";
      activeTab = "components";
    }
  }

  async function validate() {
    validating = true;
    actionError = "";
    $flow.setNodeData(Number(nodeId), { busyAction: "validate", lastError: "" });
    try {
      const resp = await fetch("/api/design-system/validate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document: doc }),
      });
      validationResult = await resp.json();
      activeTab = "validation";
      if (validationResult?.errors?.length) {
        actionError = validationResult.errors[0].message;
      }
    } catch (e) {
      actionError = e instanceof Error ? e.message : String(e);
    } finally {
      validating = false;
      $flow.setNodeData(Number(nodeId), { busyAction: "" });
    }
  }

  async function organizeCatalog() {
    if (!doc.id || !catalogEntries.length) return;
    organizing = true;
    actionError = "";
    $flow.setNodeData(Number(nodeId), { busyAction: "organize", lastError: "" });
    try {
      const resp = await fetch("/api/design-system/organize", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document: doc, reasoningEffort: organizerEffort }),
      });
      const result = await resp.json();
      if (!resp.ok || result.error) throw new Error(result.error || `HTTP ${resp.status}`);
      pushUndo();
      $flow.setNodeData(Number(nodeId), {
        document: result.document,
        summary: result.summary,
        status: "draft",
      });
      activeTab = "components";
    } catch (e) {
      actionError = e instanceof Error ? e.message : String(e);
    } finally {
      organizing = false;
      $flow.setNodeData(Number(nodeId), { busyAction: "" });
    }
  }

  async function runStyleReview() {
    if (!doc.id) return;
    reviewing = true;
    actionError = "";
    $flow.setNodeData(Number(nodeId), { busyAction: "style-review", lastError: "" });
    try {
      const desktop = window.designDNA;
      let payload: Record<string, unknown>;
      if (desktop && reviewProvider !== "openai") {
        // Desktop: сервер готовит промпт, выбранный аккаунт (Codex/Claude)
        // отвечает, сервер валидирует и применяет ответ.
        const prepResp = await fetch("/api/design-system/style-review", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ document: doc, prepareOnly: true }),
        });
        const prep = await prepResp.json();
        if (!prepResp.ok || prep.error) throw new Error(prep.error || `HTTP ${prepResp.status}`);
        const messages = prep.prompts?.[0]?.messages;
        if (!messages?.length) throw new Error("Не удалось подготовить промпт ревью");
        const route = reviewProvider === "codex"
          ? { provider: "codex" as const, model: null }
          : { provider: "claude" as const, model: "opus", reasoning: { effort: reviewEffort } };
        const answer = await desktop.providers.chatRequest({ ...route, messages });
        payload = { document: doc, rawOutput: answer.content, provider: reviewProvider };
      } else {
        payload = { document: doc, reasoningEffort: reviewEffort };
      }
      const resp = await fetch("/api/design-system/style-review", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const result = await resp.json();
      if (!resp.ok || result.error) throw new Error(result.error || `HTTP ${resp.status}`);
      pushUndo();
      $flow.setNodeData(Number(nodeId), {
        document: result.document,
        summary: result.summary,
        status: "draft",
      });
      activeTab = "styleguide";
    } catch (e) {
      actionError = e instanceof Error ? e.message : String(e);
    } finally {
      reviewing = false;
      $flow.setNodeData(Number(nodeId), { busyAction: "" });
    }
  }

  async function publish() {
    publishing = true;
    actionError = "";
    try {
      const ok = await $flow.publishDesignSystem(Number(nodeId));
      if (!ok) {
        actionError = String(($flow.nodes.find((n) => Number(n.id) === Number(nodeId))?.data as unknown as DesignSystemNodeData)?.lastError || "Публикация не удалась");
        await validate();
        return;
      }
      // документ в ноде сбрасывается публикацией в ссылку; ref-load эффект
      // подтянет опубликованную ревизию и переустановит snapshot
    } finally {
      publishing = false;
    }
  }

  async function setDefault() {
    actionError = "";
    const ok = await $flow.setDefaultDesignSystem(Number(nodeId));
    if (!ok) actionError = String(data.lastError || "Не удалось назначить по умолчанию");
  }

  async function confirmState(name: string) {
    if (!selectedKey || selectedPool !== "components") return;
    pushUndo();
    const next = JSON.parse(JSON.stringify(doc));
    const state = next.components?.[selectedKey]?.states?.[name];
    if (!state) return;
    state.confirmed = true;
    next.status = "draft";
    await persist(next);
  }

  async function updateSoul(value: string) {
    const text = value.trim();
    if (!text || text === identity.soul?.oneLine?.value) return;
    pushUndo();
    const next = JSON.parse(JSON.stringify(doc));
    next.identity ||= {};
    next.identity.soul ||= {};
    next.identity.soul.oneLine = { value: text, provenance: "user", confidence: 1, confirmed: true, method: "user-edit" };
    next.status = "draft";
    await persist(next);
  }

  async function confirmIdentityItem(collection: "signatures" | "bans" | "archetypes", itemId: string) {
    pushUndo();
    const next = JSON.parse(JSON.stringify(doc));
    const item = (next.identity?.[collection] || []).find((entry: any) => entry.id === itemId);
    if (!item) return;
    item.confirmed = true;
    item.confirmedBy = "user";
    next.status = "draft";
    await persist(next);
  }

  function proofCandidate(): any {
    if (selectedComp?.masterIr) return selectedComp.masterIr;
    return components[0]?.[1]?.templateIr || null;
  }

  async function runIdentityTests() {
    const candidate = proofCandidate();
    if (!candidate) return;
    validating = true;
    actionError = "";
    try {
      const resp = await fetch("/api/design-system/identity/validate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document: doc, ir: candidate }),
      });
      identityResult = await resp.json();
      activeTab = "tests";
    } catch (e) {
      actionError = e instanceof Error ? e.message : String(e);
    } finally {
      validating = false;
    }
  }

  async function runProof(proof: "source" | "transfer") {
    const candidate = proofCandidate();
    if (!candidate) return;
    proofRunning = true;
    actionError = "";
    try {
      const resp = await fetch("/api/design-system/reconstruction/proof", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document: doc, candidateIr: candidate, proof }),
      });
      const result = await resp.json();
      if (!resp.ok || result.error) throw new Error(result.error || `HTTP ${resp.status}`);
      $flow.setNodeData(Number(nodeId), { document: result.document, summary: result.summary, status: "draft" });
      identityResult = result.report;
      activeTab = "proof";
    } catch (e) {
      actionError = e instanceof Error ? e.message : String(e);
    } finally {
      proofRunning = false;
    }
  }

  async function applyToEditor() {
    if (!selectedKey || selectedPool !== "components") return;
    applying = true;
    actionError = "";
    $flow.setNodeData(Number(nodeId), { busyAction: "apply" });
    try {
      const result = $flow.applyDesignSystemToEditor(Number(nodeId), selectedKey);
      if (!result) {
        actionError = "Не удалось применить мастер в DNA Editor";
        return;
      }
      pushUndo();
      appliedEdit = result;
      window.dispatchEvent(new Event("designdna:ensure-editor"));
      for (let i = 0; i < 40; i++) {
        const opened = useEditorStore.getState().openEditor(result.editNodeId);
        if (opened || useEditorStore.getState().isOpen) break;
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
    } finally {
      applying = false;
      $flow.setNodeData(Number(nodeId), { busyAction: "" });
    }
  }

  async function undo() {
    const prev = undoStack[undoStack.length - 1];
    if (!prev) return;
    undoStack = undoStack.slice(0, -1);
    await restoreDocument(JSON.parse(prev));
    if (appliedEdit) {
      $flow.restoreDesignSystemEditorApply(appliedEdit.editNodeId, appliedEdit.previousIr);
      appliedEdit = null;
    }
  }

  async function cancel() {
    // Published snapshot: reload immutable revision instead of save-draft,
    // which would demote the node to draft and leave a dirty working copy.
    if (dirty && snapshot) {
      const ok = await restoreDocument(JSON.parse(snapshot));
      if (!ok) return;
    }
    if (appliedEdit) {
      $flow.restoreDesignSystemEditorApply(appliedEdit.editNodeId, appliedEdit.previousIr);
      appliedEdit = null;
    }
    undoStack = [];
    onClose();
  }

  function onKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      void cancel();
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
      event.preventDefault();
      void undo();
    }
  }
</script>

<svelte:window onkeydown={onKeydown} />

<div class="ds-editor-overlay" role="dialog" aria-modal="true" aria-label="Design System Editor" data-ds-editor>
  <header class="ds-editor-top">
    <div>
      <strong>◈ {data.name}</strong>
      <span class="ds-editor-meta">
        {data.status === "published" ? `Published · v${data.revision}` : "Draft"}
        {data.defaultSet ? " · проект по умолчанию" : ""}
        · {catalogEntries.length} source masters · {components.length} accepted · {semanticSuggestions.length} suggestions
        {dirty ? " · несохранённые правки" : ""}
      </span>
    </div>
    <div class="ds-editor-actions">
      <button type="button" data-ds-action="validate" aria-label="Проверить документ" aria-busy={validating} onclick={validate} disabled={busy || !components.length}>
        {validating ? "Проверка…" : "Validate"}
      </button>
      <button type="button" data-ds-action="publish" aria-label="Опубликовать immutable-ревизию" aria-busy={publishing} onclick={publish} disabled={busy || !components.length}>
        {publishing ? "Публикация…" : "Опубликовать ревизию"}
      </button>
      <button type="button" data-ds-action="default" aria-label="Назначить системой проекта" onclick={setDefault} disabled={busy || data.status !== "published" || data.defaultSet}>
        По умолчанию
      </button>
      <button type="button" data-ds-action="undo" aria-label="Отменить последнее изменение" onclick={() => void undo()} disabled={busy || (!undoStack.length && !appliedEdit)}>
        Undo
      </button>
      <button type="button" data-ds-action="cancel" aria-label="Отменить правки и закрыть" onclick={() => void cancel()} disabled={publishing}>
        Отмена
      </button>
      <button type="button" class="close" data-ds-action="close" aria-label="Закрыть редактор" onclick={() => void cancel()}>✕</button>
    </div>
  </header>
  {#if actionError}
    <div class="ds-editor-error" role="alert">{actionError}</div>
  {/if}

  <nav class="ds-section-tabs" aria-label="Разделы дизайн-системы">
    <button type="button" data-ds-tab="source" class:active={activeTab === "source"} onclick={() => (activeTab = "source")}>Source UI <span>{catalogEntries.length || sourceArtifact?.summary.componentCount || 0}</span></button>
    <button type="button" data-ds-tab="components" class:active={activeTab === "components"} onclick={() => (activeTab = "components")}>Components <span>{catalogEntries.length}</span></button>
    <button type="button" data-ds-tab="styleguide" class:active={activeTab === "styleguide"} onclick={() => (activeTab = "styleguide")}>Style Guide{#if styleReview}<span>AI</span>{/if}</button>
    <button type="button" data-ds-tab="foundations" class:active={activeTab === "foundations"} onclick={() => (activeTab = "foundations")}>Foundations</button>
    <button type="button" data-ds-tab="suggestions" class:active={activeTab === "suggestions"} onclick={() => (activeTab = "suggestions")}>Suggestions <span>{semanticSuggestions.length}</span></button>
    <button type="button" data-ds-tab="identity" class:active={activeTab === "identity"} onclick={() => (activeTab = "identity")}>Identity</button>
    <button type="button" data-ds-tab="archetypes" class:active={activeTab === "archetypes"} onclick={() => (activeTab = "archetypes")}>Archetypes</button>
    <button type="button" data-ds-tab="tests" class:active={activeTab === "tests"} onclick={() => (activeTab = "tests")}>Tests <span>{identityTests.length}</span></button>
    <button type="button" data-ds-tab="proof" class:active={activeTab === "proof"} onclick={() => (activeTab = "proof")}>Proof</button>
    <button type="button" data-ds-tab="mock" class:active={activeTab === "mock"} onclick={() => (activeTab = "mock")}>Mock data</button>
    <button type="button" data-ds-tab="validation" class:active={activeTab === "validation"} onclick={() => (activeTab = "validation")}>Validation</button>
  </nav>

  <div class="ds-editor-body" class:source-overview={activeTab === "source"}>
    <aside class="ds-editor-lib">
      <nav class="ds-legacy-tabs" aria-hidden="true"></nav>

      {#if activeTab === "source"}
        <SourceArtifactPanel
          artifact={sourceArtifact}
          {catalogEntries}
          {catalog}
          acceptedMasters={Number((data.summary as Record<string, unknown> | null)?.components || components.length)}
          acceptedVariants={Number((data.summary as Record<string, unknown> | null)?.variants || 0)}
          onOpen={selectCatalogComponent}
        />
      {:else if activeTab === "components"}
        <div class="ds-lib-heading">
          <div><strong>Component library</strong><small>Exact Source families, without content duplicates</small></div>
          <span>{catalogEntries.length}</span>
        </div>
        <section class="ds-ai-organizer" aria-label="AI component catalog organizer">
          <div>
            <strong>AI catalog logic</strong>
            <small>Groups header, controls, button variants and cards. Exact masters stay locked.</small>
          </div>
          <label>
            <span>Sol effort</span>
            <select bind:value={organizerEffort} disabled={busy}>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="max">max</option>
            </select>
          </label>
          <button type="button" data-ds-action="organize" onclick={() => void organizeCatalog()} disabled={busy || !catalogEntries.length}>
            {organizing ? "Organizing…" : "Organize with Sol"}
          </button>
          <span class="ds-organizer-state" data-kind={catalog.organizer?.kind || "deterministic"}>
            {catalog.organizer?.kind === "ai" ? `gpt-5.6-sol · ${catalog.organizer.reasoningEffort}` : "deterministic baseline"}
          </span>
        </section>
        <label class="ds-library-search">
          <span>Search components</span>
          <input type="search" placeholder="Search by name or category" bind:value={componentSearch} />
        </label>
        <div class="ds-component-groups">
          {#each componentGroups as [category, items] (category)}
            <section class="ds-component-group">
              <h4>{category}<span>{items.length}</span></h4>
              <ul class="ds-comp-list">
                {#each items as entry (entry.pool + ":" + entry.key)}
                  {@const key = entry.key}
                  {@const comp = entry.component}
                  <li>
                    <button type="button" class:active={selectedPool === entry.pool && selectedKey === key} data-ds-component={key} aria-label={`Выбрать компонент ${comp.name}`} onclick={() => selectCatalogComponent(key, entry.pool)}>
                      <span class="ds-status-dot" class:verified={comp.status === "verified"} aria-hidden="true"></span>
                      <span class="ds-comp-copy">
                        <span class="ds-comp-name">{comp.name}</span>
                        <small>{comp.provenance?.occurrenceCount || 1} observed · {Object.keys(comp.variants || {}).length} variant{Object.keys(comp.variants || {}).length === 1 ? "" : "s"}</small>
                      </span>
                      <span class="ds-count-badge">{Object.keys(comp.variants || {}).length}</span>
                    </button>
                  </li>
                {/each}
              </ul>
            </section>
          {/each}
          {#if !componentGroups.length}<p class="ds-empty-filter">No components match “{componentSearch}”.</p>{/if}
        </div>
      {:else if activeTab === "suggestions"}
        <div class="ds-lib-heading"><div><strong>Suggestions</strong><small>Semantic hypotheses, separate from exact Source masters</small></div><span>{semanticSuggestions.length}</span></div>
        <div class="ds-suggestion-intro">Exact observed masters are always visible in Components. This queue contains only inferred additions that require an explicit Promote.</div>
        <ul class="ds-comp-list">
          {#each semanticSuggestions as [key, comp] (key)}
            <li>
              <button type="button" class:active={selectedPool === "suggestions" && selectedKey === key} data-ds-suggestion={key} aria-label={`Выбрать предложение ${comp.name}`} onclick={() => selectSuggestion(key)}>
                <span class="ds-origin" data-origin={comp.origin} title={comp.origin}>{originIcon(comp.origin)}</span>
                <span class="ds-comp-name">{comp.name}</span>
                <span class="ds-comp-cat">{comp.origin === "observed" ? "review" : `${Math.round((comp.confidence || 0) * 100)}%`}</span>
              </button>
            </li>
          {/each}
        </ul>
      {:else if activeTab === "styleguide"}
        <div class="ds-styleguide">
          <section class="ds-sg-review-bar" aria-label="AI style review">
            <div>
              <strong>AI-ревью стиля</strong>
              <small>Модель изучает дизайн-язык сайта: тон, правила, характер. Новые компоненты будут генерироваться по этому гайду.</small>
            </div>
            <label>
              <span>Провайдер</span>
              <select bind:value={reviewProvider} disabled={busy}>
                <option value="openai">GPT-5.6 Sol</option>
                <option value="codex">Codex</option>
                <option value="claude">Claude Opus</option>
              </select>
            </label>
            {#if reviewProvider !== "codex"}
              <label>
                <span>Усилие</span>
                <select bind:value={reviewEffort} disabled={busy}>
                  <option value="medium">medium</option>
                  <option value="high">high</option>
                  <option value="max">max</option>
                </select>
              </label>
            {/if}
            <button type="button" data-ds-action="style-review" onclick={() => void runStyleReview()} disabled={busy || !doc.id}>
              {reviewing ? "Ревью…" : styleReview ? "Обновить ревью" : "Сделать ревью"}
            </button>
            <span class="ds-organizer-state" data-kind={styleGuide.origin === "ai" ? "ai" : "deterministic"}>
              {styleGuide.origin === "ai" ? `AI · ${styleGuide.provider || "openai"}` : "measured baseline"}
            </span>
          </section>

          <h4>Семантические токены</h4>
          <p class="ds-sg-hint">Стандартная карта ролей (как в shadcn/ui) — из измеренных значений сайта. Генератор обязан использовать роли, а не сырые hex.</p>
          <div class="ds-sg-tokens">
            {#each styleTokens as [name, value] (name)}
              <div class="ds-sg-token">
                {#if typeof value === "string" && value.startsWith("#")}
                  <i style="background:{value}"></i>
                {:else}
                  <i class="abstract">{typeof value === "number" ? "px" : "Aa"}</i>
                {/if}
                <div><strong>{name}</strong><small>{value}</small></div>
              </div>
            {:else}
              <p class="ds-sg-hint">Токены появятся после сборки из Source.</p>
            {/each}
          </div>

          <h4>Измеренный характер</h4>
          <div class="ds-sg-chips">
            {#each Object.entries(styleGuide.measured || {}) as [name, value] (name)}
              <span><small>{name}</small>{value}</span>
            {/each}
          </div>

          {#if styleReview}
            <h4>Дизайн-язык (AI)</h4>
            <dl class="ds-sg-traits">
              {#each [["tone", "Тон"], ["density", "Плотность"], ["cornerCharacter", "Формы"], ["colorUsage", "Цвет"], ["typographyCharacter", "Типографика"], ["imageryStyle", "Изображения"]] as [field, label] (field)}
                {#if styleReview[field]}
                  <div><dt>{label}</dt><dd>{styleReview[field]}</dd></div>
                {/if}
              {/each}
            </dl>
            {#if styleReview.doRules?.length || styleReview.dontRules?.length}
              <div class="ds-sg-rules">
                {#if styleReview.doRules?.length}
                  <div>
                    <h4>Do</h4>
                    <ul>{#each styleReview.doRules as rule}<li class="do">{rule}</li>{/each}</ul>
                  </div>
                {/if}
                {#if styleReview.dontRules?.length}
                  <div>
                    <h4>Don't</h4>
                    <ul>{#each styleReview.dontRules as rule}<li class="dont">{rule}</li>{/each}</ul>
                  </div>
                {/if}
              </div>
            {/if}
            {#if Object.keys(styleReview.componentNotes || {}).length}
              <h4>Заметки по компонентам</h4>
              {#each Object.entries(styleReview.componentNotes || {}) as [key, note] (key)}
                <p class="ds-sg-note"><code>{key}</code> {note}</p>
              {/each}
            {/if}
          {:else}
            <p class="ds-sg-hint">AI-ревью ещё не выполнялось. Запустите его, чтобы новые компоненты генерировались строго в стилистике сайта.</p>
          {/if}
        </div>
      {:else if activeTab === "foundations"}
        <div class="ds-foundations">
          <h4>Цвета (semantic)</h4>
          <div class="ds-swatches">
            {#each Object.entries(foundations.colors?.semantic || {}) as [name, hex] (name)}
              <span class="ds-swatch"><i style="background:{hex}"></i>{name}</span>
            {/each}
          </div>
          <h4>Типографика</h4>
          <p>{(foundations.typography?.families || []).join(", ") || "—"} · веса {(foundations.typography?.weights || []).join("/")}</p>
          <h4>Spacing</h4>
          <p>{Object.entries(foundations.spacing || {}).map(([k, v]) => `${k}=${v}`).join(" · ")}</p>
          <h4>Радиусы</h4>
          <p>{(foundations.radii || []).join(", ")}</p>
          <h4>Breakpoints</h4>
          <p>{Object.entries(foundations.breakpoints || {}).map(([k, v]) => `${k}≥${v}`).join(" · ")}</p>
        </div>
      {:else if activeTab === "identity"}
        <div class="ds-identity">
          <label>Soul · one line
            <textarea value={identity.soul?.oneLine?.value || ""} onblur={(event) => void updateSoul(event.currentTarget.value)}></textarea>
          </label>
          <small>Status: {identity.status || "not-extracted"} · palette evidence {Math.round((identity.paletteCoverage?.confidence || 0) * 100)}%</small>
          <h4>Signatures</h4>
          {#each identity.signatures || [] as signature (signature.id)}
            <article>
              <strong>{signature.name}</strong>
              <p>{signature.rule}</p>
              <small>{signature.provenance} · {Math.round((signature.confidence || 0) * 100)}%</small>
              {#if !signature.confirmed}<button type="button" onclick={() => void confirmIdentityItem("signatures", signature.id)}>Подтвердить</button>{/if}
            </article>
          {/each}
          <h4>Bans</h4>
          {#each identity.bans || [] as ban (ban.id)}
            <article><strong>{ban.severity} · {ban.rule}</strong><small>{ban.provenance} · {Math.round((ban.confidence || 0) * 100)}%</small>
              {#if !ban.confirmed}<button type="button" onclick={() => void confirmIdentityItem("bans", ban.id)}>Подтвердить</button>{/if}
            </article>
          {/each}
          {#if identity.uncertainty?.length}<h4>Uncertainty</h4>{/if}
          {#each identity.uncertainty || [] as item}
            <p class="ds-uncertain">◐ {item.field}: {item.reason}</p>
          {/each}
        </div>
      {:else if activeTab === "archetypes"}
        <div class="ds-identity">
          {#each archetypes as archetype (archetype.id)}
            <article><strong>{archetype.name}</strong><p>{(archetype.structure || []).join(" → ")}</p><small>{archetype.provenance} · {Math.round((archetype.confidence || 0) * 100)}%</small>
              {#if !archetype.confirmed}<button type="button" onclick={() => void confirmIdentityItem("archetypes", archetype.id)}>Подтвердить</button>{/if}
            </article>
          {/each}
        </div>
      {:else if activeTab === "tests"}
        <div class="ds-identity">
          <button type="button" onclick={() => void runIdentityTests()} disabled={validating || !components.length}>{validating ? "Проверяю…" : "Запустить на мастере"}</button>
          {#if identityResult}<p class:ds-test-fail={!identityResult.passed}>Score {identityResult.score}% · {identityResult.passed ? "hard rules passed" : "hard failure"}</p>{/if}
          {#each identityTests as test (test.id)}
            {@const result = identityResult?.results?.find((item: any) => item.id === test.id)}
            <article class:ds-test-fail={result && !result.passed}><strong>{result ? (result.passed ? "✓" : "⛔") : "○"} {test.severity} · {test.description}</strong><small>{test.id} · {test.provenance} · {Math.round((test.confidence || 0) * 100)}%</small></article>
          {/each}
        </div>
      {:else if activeTab === "proof"}
        <div class="ds-identity">
          <p>Reconstruction проверяет перенос identity тем же валидатором, который используется после генерации.</p>
          <button type="button" onclick={() => void runProof("source")} disabled={proofRunning || !components.length}>{proofRunning ? "Проверяю…" : "Source proof"}</button>
          <button type="button" onclick={() => void runProof("transfer")} disabled={proofRunning || !components.length}>Transfer proof</button>
          {#if reconstruction.sourceProof}<article><strong>Source · {reconstruction.sourceProof.status}</strong><p>Identity {reconstruction.sourceProof.identityScore}%</p></article>{/if}
          {#if reconstruction.transferProof}<article><strong>Transfer · {reconstruction.transferProof.status}</strong><p>Identity {reconstruction.transferProof.identityScore}%</p></article>{/if}
        </div>
      {:else if activeTab === "mock"}
        <div class="ds-mock-list">
          {#each mockSchemas as [id, schema] (id)}
            <div class="ds-mock-item">
              <strong>{id}</strong>
              <small>{(schema.fields || []).map((f: any) => f.name).join(", ")}</small>
            </div>
          {/each}
        </div>
      {:else if activeTab === "validation"}
        <div class="ds-validation" data-ds-validation>
          {#if validationResult?.errors?.length}
            {#each validationResult.errors as err}
              <div class="ds-val-error">⛔ {err.message}</div>
            {/each}
          {:else if validationResult}
            <div class="ds-val-ok">✓ Блокирующих ошибок нет — можно публиковать</div>
          {:else}
            <p>Запустите Validate для проверки перед публикацией.</p>
          {/if}
        </div>
      {/if}
    </aside>

    <main class="ds-editor-canvas">
      {#if hasSelection && selectedComp}
        <header class="ds-workbench-head">
          <div class="ds-workbench-title">
            <span class="ds-eyebrow">{selectedComp.category || "component"} · exact Source family</span>
            <h2>{selectedComp.name}</h2>
            <div class="ds-component-meta">
              <span class:verified={selectedComp.status === "verified"}>{selectedComp.status === "verified" ? "Source verified" : "Needs review"}</span>
              <span>{selectedComp.provenance?.occurrenceCount || 1} наблюдений</span>
              <span>{Object.keys(selectedComp.variants || {}).length} вариантов</span>
            </div>
          </div>
          {#if selectedIsReview}
            <button type="button" class="ds-promote" data-ds-action="review" aria-label="Компонент сохранён в каталоге, но требует повторной fidelity-проверки" disabled>Нужна fidelity-проверка</button>
          {:else if selectedIsSuggestion}
            <button type="button" class="ds-promote" data-ds-action="promote" aria-label={selectedCanPromote ? "Продвинуть предложение в registry" : "Требуется повторная fidelity-проверка Source master"} onclick={() => void promoteSuggestion()} disabled={busy || !selectedCanPromote}>{selectedCanPromote ? "Включить в UI Kit" : "Нужна fidelity-проверка"}</button>
          {:else}
            <button type="button" class="ds-edit-master" data-ds-action="apply" aria-label="Применить мастер-компонент в DNA Editor" aria-busy={applying} onclick={applyToEditor} disabled={busy || !hasSelection}>
              {applying ? "Открываю…" : "Открыть в DNA Editor"}
            </button>
          {/if}
        </header>

        <div class="ds-canvas-head">
          <div class="ds-viewport-switch" role="group" aria-label="Превью viewport">
            {#each ["desktop", "tablet", "mobile"] as vp (vp)}
              <button type="button" class:active={viewport === vp} data-ds-viewport={vp} aria-pressed={viewport === vp} aria-label={`Превью ${vp}`} onclick={() => { viewport = vp as "desktop" | "tablet" | "mobile"; }}>
                {vp}
              </button>
            {/each}
          </div>
          <div class="ds-viewport-switch" role="group" aria-label="Режим сравнения с Source">
            {#each ["reference", "master", "compare"] as mode (mode)}
              <button type="button" class:active={previewMode === mode} aria-pressed={previewMode === mode} onclick={() => { previewMode = mode as "reference" | "master" | "compare"; }}>
                {mode === "reference" ? "Source" : mode === "master" ? "Master" : "Сравнить"}
              </button>
            {/each}
          </div>
          <label class="ds-fixture">
            Данные
            <select data-ds-field="preview-fixture" aria-label="Профиль mock в превью" bind:value={fixtureProfile}>
              <option value="source">Source exact</option>
              <option value="typical">Typical</option>
              <option value="short">Short</option>
              <option value="long">Long</option>
              <option value="empty">Empty</option>
              <option value="loading">Loading</option>
              <option value="error">Error</option>
              <option value="edge-case">Edge case</option>
            </select>
          </label>
        </div>

        {#if Object.keys(selectedComp.variants || {}).length}
          <div class="ds-variant-strip" role="tablist" aria-label="Наблюдаемые варианты компонента">
            <span class="ds-variant-label">Варианты из Source</span>
            {#each Object.entries((selectedComp.variants || {}) as Record<string, any>) as [key, variant] (key)}
              <button type="button" role="tab" data-ds-variant={key} class:active={selectedVariant === key} aria-selected={selectedVariant === key} onclick={() => (selectedVariant = key)}>
                {#if variant.observedStyle?.background}
                  <i class="ds-variant-swatch" style:background={String(variant.observedStyle.background)} aria-hidden="true"></i>
                {/if}
                <span>{variant.label || key}</span>
                <small>×{variant.observedCount || 1}</small>
              </button>
            {/each}
          </div>
        {/if}
      {/if}
      <div class="ds-canvas-empty" style:display={hasSelection ? "none" : "grid"}>Выберите master или suggestion слева</div>
      <div class="ds-canvas-preview" data-ds-preview-host data-ds-preview-fixture={previewMeta?.fixture || fixtureProfile} bind:this={previewHost}></div>
    </main>

    <aside class="ds-editor-inspector">
      {#if hasSelection && selectedComp}
        <div class="ds-inspector-content">
          <span class="ds-inspector-kicker">Inspector</span>
          <h3>{selectedComp.name}</h3>
          <p class="ds-inspector-description">{selectedComp.description || "Точный мастер, извлечённый из Source."}</p>
          <section class="ds-inspector-section">
            <h4>Выбранный вариант</h4>
            <div class="ds-selected-variant">
              {#if selectedObservedStyle.background}<i style:background={String(selectedObservedStyle.background)}></i>{/if}
              <div><strong>{selectedVariantData?.label || selectedVariant}</strong><small>{selectedVariantData?.observedCount || 1} наблюдений в Source</small></div>
            </div>
          </section>
          {#if Object.keys(selectedObservedStyle).length}
            <section class="ds-inspector-section">
              <h4>Измеренный стиль</h4>
              <div class="ds-style-grid">
                {#each Object.entries(selectedObservedStyle) as [name, value] (name)}
                  <span>{name}</span><code>{displayStyleValue(value)}</code>
                {/each}
              </div>
            </section>
          {/if}
          <section class="ds-inspector-section">
            <h4>Источник и точность</h4>
          <dl>
            <dt>Key</dt><dd><code>{selectedComp.componentKey}</code></dd>
            <dt>Origin</dt><dd>{originIcon(selectedComp.origin)} {selectedComp.origin} {selectedComp.confidence != null ? `· ${Math.round(selectedComp.confidence * 100)}%` : ""}</dd>
            <dt>Status</dt><dd class:ds-fidelity-fail={selectedComp.status !== "verified"}>{selectedComp.status || "draft"}</dd>
            <dt>Category</dt><dd>{selectedComp.category}</dd>
            <dt>Props</dt><dd>{Object.keys(selectedComp.propsSchema || {}).join(", ") || "—"}</dd>
            <dt>States</dt>
            <dd>
              {#each Object.entries((selectedComp.states || {}) as Record<string, any>) as [name, st]}
                <button
                  type="button"
                  class="ds-state"
                  class:unconfirmed={st.origin === "generated" && !st.confirmed}
                  data-ds-state={name}
                  aria-label={st.origin === "generated" && !st.confirmed ? `Подтвердить состояние ${name}` : `Состояние ${name}`}
                  disabled={busy || !(st.origin === "generated" && !st.confirmed)}
                  onclick={() => void confirmState(name)}
                >{name}{st.origin === "generated" && !st.confirmed ? "?" : ""}</button>
              {/each}
            </dd>
            {#if selectedComp.dependencies?.length}<dt>Зависимости</dt><dd>{selectedComp.dependencies.join(", ")}</dd>{/if}
            {#if selectedSourceRef.sourceBlock || selectedComp.provenance?.sourceBlock}<dt>Source</dt><dd>{selectedSourceRef.sourceBlock || selectedComp.provenance.sourceBlock}</dd>{/if}
            {#if selectedComp.provenance?.sourceBlocks?.length}<dt>Blocks</dt><dd>{selectedComp.provenance.sourceBlocks.join(", ")}</dd>{/if}
            {#if Object.keys(fidelityMetrics).length}
              <dt>Fidelity</dt>
              <dd class:ds-fidelity-fail={selectedComp.status !== "verified"}>
                similarity {fidelityMetrics.pixelSimilarity ?? "—"}% · paint {fidelityMetrics.paintCoverage ?? "—"}%<br />
                bbox p95 {fidelityMetrics.bboxP95 ?? "—"}px · origin {fidelityMetrics.originError ?? "—"}px · losses {fidelityMetrics.unexplainedLosses ?? "—"}
              </dd>
            {/if}
            {#if selectedSourceRef.sourceRevisionHash}<dt>Revision</dt><dd><code>{String(selectedSourceRef.sourceRevisionHash).slice(0, 20)}…</code></dd>{/if}
          </dl>
          </section>
        </div>
      {:else}
        <p class="ds-insp-empty">Инспектор компонента</p>
      {/if}
    </aside>
  </div>
</div>

<style>
  .ds-editor-overlay {
    --panel: #0f1218;
    --panel-raised: #141821;
    --panel-soft: #191e29;
    --border: #292f3c;
    --border-strong: #3b4353;
    --text: #f4f6fb;
    --muted: #929bad;
    --subtle: #697386;
    --accent: #8b7cff;
    --accent-soft: #292342;
    --success: #45df91;
    position: fixed;
    inset: 0;
    z-index: 200;
    display: flex;
    flex-direction: column;
    background: #090b10;
    color: var(--text);
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }
  .ds-editor-top {
    min-height: 60px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 20px;
    padding: 0 18px;
    border-bottom: 1px solid var(--border);
    background: #0c0f15;
  }
  .ds-editor-top > div:first-child { min-width: 0; display: flex; align-items: baseline; }
  .ds-editor-top strong { flex: none; font-size: 15px; letter-spacing: -.01em; }
  .ds-editor-meta { min-width: 0; margin-left: 14px; overflow: hidden; color: var(--muted); font-size: 11.5px; text-overflow: ellipsis; white-space: nowrap; }
  .ds-editor-actions { flex: none; display: flex; align-items: center; gap: 7px; }
  .ds-editor-actions button,
  .ds-edit-master,
  .ds-promote {
    min-height: 34px;
    padding: 0 12px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--panel-raised);
    color: #e8ebf3;
    font: inherit;
    font-size: 11.5px;
    cursor: pointer;
  }
  .ds-editor-actions button:hover:not(:disabled), .ds-edit-master:hover:not(:disabled) { border-color: var(--border-strong); background: var(--panel-soft); }
  .ds-editor-actions button:disabled, .ds-edit-master:disabled, .ds-promote:disabled { opacity: .45; cursor: not-allowed; }
  .ds-editor-actions [data-ds-action="publish"] { border-color: #675ad4; background: #6f5ee7; color: #fff; }
  .ds-editor-actions .close { width: 34px; padding: 0; border-color: transparent; background: transparent; font-size: 15px; }
  .ds-editor-error { padding: 8px 18px; border-bottom: 1px solid #642e35; background: #2d1519; color: #ff9aa6; font-size: 12px; }

  .ds-section-tabs {
    flex: none;
    min-height: 46px;
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 6px 14px;
    overflow-x: auto;
    border-bottom: 1px solid var(--border);
    background: #0c0f15;
  }
  .ds-section-tabs button {
    flex: none;
    min-height: 32px;
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 0 11px;
    border: 1px solid transparent;
    border-radius: 7px;
    background: transparent;
    color: var(--muted);
    font: inherit;
    font-size: 11.5px;
    cursor: pointer;
  }
  .ds-section-tabs button:hover { background: #151923; color: #dfe3ed; }
  .ds-section-tabs button.active { border-color: #3a4253; background: #1b202b; color: #fff; box-shadow: 0 1px 2px #0005; }
  .ds-section-tabs button span { min-width: 18px; padding: 1px 5px; border-radius: 999px; background: #262c39; color: #b8c0cf; font-size: 10px; text-align: center; }

  .ds-editor-body { flex: 1; min-height: 0; display: grid; grid-template-columns: 300px minmax(0, 1fr) 300px; }
  .ds-editor-body.source-overview { grid-template-columns: minmax(0, 1fr); background: #0a0d12; }
  .ds-editor-body.source-overview .ds-editor-lib { padding: 0; border-right: 0; background: #0a0d12; }
  .ds-editor-body.source-overview .ds-editor-canvas,
  .ds-editor-body.source-overview .ds-editor-inspector { display: none; }
  .ds-editor-lib, .ds-editor-inspector { min-width: 0; overflow-y: auto; background: var(--panel); scrollbar-color: #555d6d transparent; scrollbar-width: thin; }
  .ds-editor-lib { padding: 16px 14px 24px; border-right: 1px solid var(--border); }
  .ds-editor-inspector { padding: 18px; border-left: 1px solid var(--border); }
  .ds-legacy-tabs { display: none !important; }
  .ds-lib-heading { display: flex; align-items: start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
  .ds-lib-heading div { min-width: 0; }
  .ds-lib-heading strong { display: block; font-size: 13px; }
  .ds-lib-heading small { display: block; margin-top: 4px; color: var(--subtle); font-size: 10.5px; line-height: 1.4; }
  .ds-lib-heading > span { min-width: 27px; padding: 3px 7px; border: 1px solid var(--border); border-radius: 999px; color: #bcc3d0; font-size: 10.5px; text-align: center; }
  .ds-library-search { display: block; margin-bottom: 16px; }
  .ds-ai-organizer {
    display: grid; grid-template-columns: minmax(210px, 1fr) auto auto; align-items: center; gap: 10px;
    margin: 0 0 14px; border: 1px solid #343c4b; border-radius: 12px; padding: 11px 12px;
    background: linear-gradient(135deg, #171d28, #121720); box-shadow: inset 3px 0 #7767e8;
  }
  .ds-ai-organizer > div strong, .ds-ai-organizer > div small { display: block; }
  .ds-ai-organizer > div strong { color: #e7eaf1; font-size: 11px; }
  .ds-ai-organizer > div small { margin-top: 3px; color: #858fa1; font-size: 9px; line-height: 1.35; }
  .ds-ai-organizer label { display: grid; gap: 3px; color: #778195; font-size: 8px; text-transform: uppercase; }
  .ds-ai-organizer select, .ds-ai-organizer button {
    min-height: 30px; border: 1px solid #414a5c; border-radius: 8px; background: #1a202b;
    padding: 0 9px; color: #dce1eb; font-size: 9px;
  }
  .ds-ai-organizer button { border-color: #6d5edf; background: #6555d5; color: #fff; font-weight: 700; cursor: pointer; }
  .ds-ai-organizer button:disabled { opacity: .45; cursor: not-allowed; }
  .ds-organizer-state { grid-column: 1 / -1; color: #707b8d; font-size: 8px; }
  .ds-organizer-state[data-kind="ai"] { color: #72cfb9; }
  .ds-library-search > span { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  .ds-library-search input {
    width: 100%;
    height: 36px;
    padding: 0 11px 0 32px;
    border: 1px solid var(--border);
    border-radius: 8px;
    outline: none;
    background: #0b0e13
      url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%237b8496' stroke-width='2'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cpath d='m21 21-4.3-4.3'/%3E%3C/svg%3E")
      no-repeat 10px center;
    color: var(--text);
    font: inherit;
    font-size: 11.5px;
  }
  .ds-library-search input::placeholder { color: #60697a; }
  .ds-library-search input:focus { border-color: #7367d8; box-shadow: 0 0 0 3px #7367d826; }
  .ds-component-groups { display: flex; flex-direction: column; gap: 18px; }
  .ds-component-group h4 {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin: 0 5px 7px;
    color: #7d8799;
    font-size: 9.5px;
    font-weight: 700;
    letter-spacing: .09em;
    text-transform: uppercase;
  }
  .ds-component-group h4 span { color: #555f71; }
  .ds-comp-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
  .ds-comp-list button {
    width: 100%;
    min-height: 50px;
    display: flex;
    align-items: center;
    gap: 9px;
    padding: 8px 9px;
    border: 1px solid transparent;
    border-radius: 9px;
    background: transparent;
    color: #d9dde7;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .ds-comp-list button:hover { border-color: #242a36; background: #151922; }
  .ds-comp-list button.active { border-color: #3d4560; background: #1c2230; box-shadow: 0 1px 2px #0004; }
  .ds-status-dot { flex: none; width: 8px; height: 8px; border-radius: 999px; background: #f0b852; box-shadow: 0 0 0 3px #f0b85212; }
  .ds-status-dot.verified { background: var(--success); box-shadow: 0 0 0 3px #45df9116; }
  .ds-comp-copy { min-width: 0; flex: 1; display: flex; flex-direction: column; gap: 3px; }
  .ds-comp-name { overflow: hidden; font-size: 11.8px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
  .ds-comp-copy small { overflow: hidden; color: #727c8e; font-size: 9.8px; text-overflow: ellipsis; white-space: nowrap; }
  .ds-count-badge { flex: none; min-width: 22px; padding: 2px 5px; border: 1px solid #303746; border-radius: 999px; color: #8f99aa; font-size: 9.5px; text-align: center; }
  .ds-empty-filter { padding: 24px 8px; color: var(--subtle); font-size: 11px; line-height: 1.5; text-align: center; }
  .ds-origin { flex: none; font-size: 10px; }
  .ds-origin[data-origin="observed"] { color: var(--success); }
  .ds-origin[data-origin="inferred"], .ds-origin[data-origin="suggested"] { color: #f7c75b; }
  .ds-origin[data-origin="generated"] { color: #b99cff; }
  .ds-origin[data-origin="user"] { color: #68a9ff; }
  .ds-suggestion-intro { margin-bottom: 10px; padding: 10px; border: 1px solid #4b4128; border-radius: 8px; background: #1d1a12; color: #d6bd7b; font-size: 10.5px; line-height: 1.45; }
  .ds-comp-cat { margin-left: auto; color: #737d8e; font-size: 10px; }

  .ds-editor-canvas { min-width: 0; display: flex; flex-direction: column; gap: 12px; padding: 18px; overflow: hidden; background: #090b10; }
  .ds-workbench-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
  .ds-workbench-title { min-width: 0; }
  .ds-eyebrow { display: block; margin-bottom: 3px; color: #7d8798; font-size: 9.5px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
  .ds-workbench-head h2 { margin: 0; overflow: hidden; font-size: 18px; line-height: 1.25; letter-spacing: -.025em; text-overflow: ellipsis; white-space: nowrap; }
  .ds-component-meta { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 7px; }
  .ds-component-meta span { padding: 3px 7px; border: 1px solid var(--border); border-radius: 999px; color: #8d96a6; font-size: 9.5px; }
  .ds-component-meta span:first-child { color: #f0bd5b; }
  .ds-component-meta span.verified { border-color: #285841; background: #10241a; color: #62e6a1; }
  .ds-edit-master { flex: none; border-color: #675bd1; background: #1d1931; color: #c5bdff; }
  .ds-promote { flex: none; border-color: #80682e; background: #27200f; color: #f2c85d; }
  .ds-canvas-head {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 6px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: #10141b;
  }
  .ds-viewport-switch { display: flex; align-items: center; gap: 3px; }
  .ds-viewport-switch button {
    min-height: 32px;
    padding: 0 11px;
    border: 1px solid transparent;
    border-radius: 7px;
    background: transparent;
    color: #818b9c;
    font: inherit;
    font-size: 10.5px;
    cursor: pointer;
  }
  .ds-viewport-switch button:hover { color: #dce1eb; }
  .ds-viewport-switch button.active { border-color: #4f477f; background: #241f3a; color: #fff; }
  .ds-fixture { display: flex; align-items: center; gap: 7px; margin-left: auto; color: #777f90; font-size: 10.5px; }
  .ds-fixture select { min-height: 32px; padding: 0 26px 0 9px; border: 1px solid var(--border); border-radius: 7px; background: var(--panel-raised); color: #dce1eb; font: inherit; font-size: 10.5px; }
  .ds-variant-strip { flex: none; display: flex; align-items: center; gap: 6px; min-height: 46px; padding: 7px 9px; overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; background: #0f1319; }
  .ds-variant-label { flex: none; padding: 0 4px; color: #707a8c; font-size: 9.5px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }
  .ds-variant-strip button { flex: none; min-height: 32px; display: inline-flex; align-items: center; gap: 7px; padding: 0 9px; border: 1px solid var(--border); border-radius: 7px; background: #151922; color: #aeb6c5; font: inherit; font-size: 10.5px; cursor: pointer; }
  .ds-variant-strip button:hover { border-color: var(--border-strong); }
  .ds-variant-strip button.active { border-color: #7569d9; background: #25203e; color: #fff; box-shadow: 0 0 0 2px #7569d91a; }
  .ds-variant-strip button small { color: #707a8c; font-size: 9px; }
  .ds-variant-swatch { width: 14px; height: 14px; border: 1px solid #ffffff33; border-radius: 4px; box-shadow: inset 0 0 0 1px #0002; }
  .ds-canvas-preview { flex: 1; min-height: 0; overflow: auto; scrollbar-color: #555d6d transparent; scrollbar-width: thin; }
  :global(.ds-preview-stage) { min-height: 100%; display: grid; grid-template-columns: minmax(0, 1fr); gap: 12px; align-items: start; }
  :global(.ds-preview-stage.ds-preview-compare) { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
  :global(.ds-preview-pane) { min-width: 0; min-height: 310px; display: flex; flex-direction: column; margin: 0; overflow: hidden; border: 1px solid var(--border); border-radius: 12px; background: #11151c; box-shadow: 0 8px 24px #0002; }
  :global(.ds-preview-pane figcaption) { flex: none; margin: 0; padding: 9px 11px; border-bottom: 1px solid #292f3c; background: #171b24; color: #929bad; font-size: 9.5px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; }
  :global(.ds-reference-pane img), :global(.ds-reference-pane canvas) { display: block; max-width: 100%; height: auto; margin: 0 auto; background: #fff; }
  :global(.ds-master-pane .ir-preview) { width: 100%; max-width: 100%; margin: 0 auto; background: #fff; overflow: hidden !important; }
  .ds-canvas-empty { flex: 1; place-items: center; border: 1px dashed #252b37; border-radius: 12px; color: #515b6c; font-size: 12px; }

  .ds-inspector-kicker { display: block; margin-bottom: 5px; color: #717b8c; font-size: 9.5px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; }
  .ds-editor-inspector h3 { margin: 0; font-size: 16px; letter-spacing: -.02em; }
  .ds-inspector-description { margin: 7px 0 18px; color: #8892a3; font-size: 10.8px; line-height: 1.5; }
  .ds-inspector-section { padding: 14px 0; border-top: 1px solid #252b36; }
  .ds-inspector-section h4 { margin: 0 0 10px; color: #777f90; font-size: 9.5px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
  .ds-selected-variant { display: flex; align-items: center; gap: 10px; padding: 10px; border: 1px solid var(--border); border-radius: 9px; background: #141821; }
  .ds-selected-variant > i { flex: none; width: 30px; height: 30px; border: 1px solid #ffffff30; border-radius: 7px; box-shadow: inset 0 0 0 1px #0003; }
  .ds-selected-variant strong, .ds-selected-variant small { display: block; }
  .ds-selected-variant strong { font-size: 11.5px; }
  .ds-selected-variant small { margin-top: 3px; color: #768092; font-size: 9.5px; }
  .ds-style-grid { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 7px 10px; font-size: 10px; }
  .ds-style-grid > span { color: #737d8f; }
  .ds-style-grid code { max-width: 160px; overflow-wrap: anywhere; color: #cdd3de; font-family: "SFMono-Regular", Consolas, monospace; text-align: right; }
  .ds-editor-inspector dl { display: grid; grid-template-columns: minmax(58px, auto) minmax(0, 1fr); gap: 7px 10px; margin: 0; font-size: 10px; line-height: 1.45; }
  .ds-editor-inspector dt { color: #70798b; }
  .ds-editor-inspector dd { min-width: 0; margin: 0; overflow-wrap: anywhere; color: #c7cdd8; }
  .ds-editor-inspector code { font-family: "SFMono-Regular", Consolas, monospace; font-size: 9.5px; }
  .ds-fidelity-fail { color: #ff858f !important; }
  .ds-state { display: inline-block; min-height: 24px; margin: 1px 4px 2px 0; padding: 0 7px; border: 1px solid #343b49; border-radius: 6px; background: #171b24; color: inherit; font: inherit; font-size: 9.5px; cursor: pointer; }
  .ds-state:disabled { cursor: default; }
  .ds-state.unconfirmed { border-style: dashed; color: #b99cff; }
  .ds-insp-empty { color: #515b6c; font-size: 11px; }

  .ds-foundations h4 { margin: 14px 0 7px; color: #7d8798; font-size: 9.5px; letter-spacing: .07em; text-transform: uppercase; }
  .ds-foundations p { margin: 0 0 10px; color: #ccd1dc; font-size: 10.5px; line-height: 1.55; }
  .ds-swatches { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; }
  .ds-swatch { min-width: 0; display: inline-flex; align-items: center; gap: 6px; overflow: hidden; color: #a7afbd; font-size: 9.5px; text-overflow: ellipsis; white-space: nowrap; }
  .ds-swatch i { flex: none; width: 20px; height: 20px; border: 1px solid #3a4250; border-radius: 5px; }
  .ds-styleguide { display: grid; gap: 10px; align-content: start; }
  .ds-styleguide h4 { margin: 8px 0 0; font-size: 11px; }
  .ds-sg-review-bar { display: grid; gap: 8px; border: 1px solid #2a303b; border-radius: 10px; background: #11151d; padding: 10px; }
  .ds-sg-review-bar strong { display: block; font-size: 11px; }
  .ds-sg-review-bar small { color: #8f97a8; font-size: 9px; line-height: 1.4; }
  .ds-sg-review-bar label { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: #8f97a8; font-size: 9.5px; }
  .ds-sg-review-bar select { min-width: 0; border: 1px solid #333b49; border-radius: 7px; background: #171c26; color: #dfe4ee; padding: 4px 6px; font-size: 10px; }
  .ds-sg-review-bar button { border: 1px solid #394252; border-radius: 8px; background: #1b222d; padding: 7px 9px; color: #e6eaf2; font-size: 10px; cursor: pointer; }
  .ds-sg-review-bar button:hover:not(:disabled) { border-color: #5e6a7f; }
  .ds-sg-hint { margin: 0; color: #79839a; font-size: 9.5px; line-height: 1.45; }
  .ds-sg-tokens { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; }
  .ds-sg-token { display: flex; align-items: center; gap: 7px; min-width: 0; border: 1px solid #262d38; border-radius: 8px; background: #121720; padding: 6px; }
  .ds-sg-token i { flex: none; display: grid; place-items: center; width: 24px; height: 24px; border: 1px solid #3a4250; border-radius: 6px; color: #97a1b4; font-size: 8px; font-style: normal; }
  .ds-sg-token i.abstract { background: #1a212c; }
  .ds-sg-token div { min-width: 0; }
  .ds-sg-token strong { display: block; overflow: hidden; font-size: 9.5px; text-overflow: ellipsis; white-space: nowrap; }
  .ds-sg-token small { display: block; overflow: hidden; color: #6f788a; font-size: 8.5px; text-overflow: ellipsis; white-space: nowrap; }
  .ds-sg-chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .ds-sg-chips span { border: 1px solid #2c3340; border-radius: 999px; background: #151a23; padding: 4px 9px; color: #c4cad6; font-size: 9.5px; }
  .ds-sg-chips small { margin-right: 5px; color: #6f788a; }
  .ds-sg-traits { display: grid; gap: 6px; margin: 0; }
  .ds-sg-traits div { border-left: 2px solid #3d4658; padding-left: 8px; }
  .ds-sg-traits dt { color: #8f97a8; font-size: 9px; text-transform: uppercase; letter-spacing: .06em; }
  .ds-sg-traits dd { margin: 2px 0 0; color: #d5dae4; font-size: 10.5px; line-height: 1.45; }
  .ds-sg-rules { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .ds-sg-rules ul { margin: 4px 0 0; padding-left: 14px; }
  .ds-sg-rules li { margin-bottom: 4px; font-size: 10px; line-height: 1.4; }
  .ds-sg-rules li.do { color: #7fd7b6; }
  .ds-sg-rules li.dont { color: #e2988a; }
  .ds-sg-note { margin: 0; color: #a7afbd; font-size: 9.5px; line-height: 1.45; }
  .ds-sg-note code { margin-right: 5px; color: #8b7cf6; }
  .ds-mock-item { padding: 9px 0; border-bottom: 1px solid #222833; }
  .ds-mock-item strong { display: block; font-size: 10.8px; }
  .ds-mock-item small { color: #727c8e; font-size: 9.5px; }
  .ds-val-error, .ds-val-ok { margin-bottom: 6px; padding: 9px 10px; border-radius: 8px; font-size: 10.5px; line-height: 1.45; }
  .ds-val-error { border: 1px solid #5c2b32; background: #2d1519; color: #ff919d; }
  .ds-val-ok { border: 1px solid #28573e; background: #10241a; color: #5ee49d; }
  .ds-identity { display: flex; flex-direction: column; gap: 8px; font-size: 10.5px; }
  .ds-identity h4 { margin: 10px 0 0; color: #7d8798; font-size: 9.5px; letter-spacing: .07em; text-transform: uppercase; }
  .ds-identity label { display: flex; flex-direction: column; gap: 5px; color: #8b95a7; }
  .ds-identity textarea { min-height: 76px; resize: vertical; border: 1px solid var(--border); border-radius: 8px; background: #0b0e13; color: #e2e6ef; padding: 9px; font: inherit; }
  .ds-identity article { padding: 9px; border: 1px solid var(--border); border-radius: 8px; background: #141821; }
  .ds-identity article strong, .ds-identity article small { display: block; }
  .ds-identity article p { margin: 5px 0; color: #c5cad6; line-height: 1.45; }
  .ds-identity small { color: #737d8e; }
  .ds-identity button { min-height: 30px; margin-top: 6px; padding: 0 9px; border: 1px solid #394152; border-radius: 7px; background: #1b202b; color: #dce1eb; font: inherit; font-size: 9.8px; cursor: pointer; }
  .ds-uncertain { margin: 0; color: #f1c45c; }
  .ds-test-fail { color: #ff858f !important; border-color: #6b3038 !important; }

  button:focus-visible, select:focus-visible, textarea:focus-visible, input:focus-visible { outline: 2px solid #9a8dff; outline-offset: 2px; }
  @media (max-width: 1220px) {
    .ds-editor-body { grid-template-columns: 260px minmax(0, 1fr) 260px; }
    .ds-editor-top { padding-inline: 12px; }
    .ds-editor-actions { gap: 4px; }
    .ds-editor-actions button { padding-inline: 9px; }
  }
  @media (max-width: 980px) {
    .ds-editor-body { grid-template-columns: 240px minmax(0, 1fr); }
    .ds-editor-inspector { display: none; }
    .ds-editor-meta { display: none; }
    :global(.ds-preview-stage.ds-preview-compare) { grid-template-columns: minmax(0, 1fr); }
  }
</style>
