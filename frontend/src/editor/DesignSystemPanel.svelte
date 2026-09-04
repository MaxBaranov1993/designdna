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

  /* Постоянных вкладок ровно две: «Компоненты» и «Стиль сайта». Девять
   * диагностических экранов (identity, archetypes, tests, proof, validation,
   * mock, suggestions, foundations, библиотека) не занимают место в шапке —
   * каждый открывается своим действием (Validate, Proof, Организовать…) и
   * возвращает пользователя кнопкой «К компонентам». */
  let activeTab = $state<"source" | "styleguide" | "foundations" | "components" | "suggestions" | "mock" | "identity" | "archetypes" | "tests" | "proof" | "validation">("source");
  const DIAGNOSTIC_LABELS: Record<string, string> = {
    foundations: "Основы", suggestions: "Предложения", mock: "Mock-данные",
    identity: "Identity", archetypes: "Архетипы", tests: "Тесты identity",
    proof: "Proof · перенос", validation: "Валидация", components: "Библиотека",
  };
  const isDiagnosticView = $derived(activeTab !== "source" && activeTab !== "styleguide");
  type CatalogPool = "components" | "review" | "suggestions";
  type CatalogEntry = { key: string; pool: CatalogPool; component: Record<string, any> };
  let selectedKey = $state<string>("");
  let selectedPool = $state<CatalogPool>("components");
  let selectedVariant = $state("default");
  let componentSearch = $state("");
  let viewport = $state<"desktop" | "tablet" | "mobile">("desktop");
  let fixtureProfile = $state("source");
  // Пользователю нужны готовые компоненты, а не «до/после»: по умолчанию
  // показываем мастер, сравнение с Source и fidelity — только по тумблеру «Точность».
  let previewMode = $state<"reference" | "master" | "compare">("master");
  let showFidelity = $state(false);
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
  let exportingKit = $state(false);
  /* Живой кит открывается прямо в разделе «Компоненты»: тот же самодостаточный
   * HTML, что уходит в файл, показывается в песочнице <iframe>. Файл стал
   * вторым действием, а не единственным способом увидеть собранный кит. */
  let sourceView = $state<"catalog" | "kit">("catalog");
  let kitUrl = $state("");
  let kitReport = $state<{ filename: string; bytes: number; components: number; warnings: number } | null>(null);
  let savingKit = $state(false);
  let kitBytes: Uint8Array | null = null;
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
  // Генератор пишет в IR роли tokens.v2, а не shadcn-имена ДС. Показываем карту
  // соответствия, чтобы было видно, каким цветом станет каждая роль страницы.
  const V2_ROLE_SOURCES: Array<[string, string, string]> = [
    ["bg", "background", "фон страницы"],
    ["bg2", "muted", "второй фон, чередование секций"],
    ["surface", "card", "карточки и панели"],
    ["surface2", "secondary", "вложенные поверхности"],
    ["ink", "foreground", "основной текст"],
    ["ink2", "foreground", "второй уровень текста"],
    ["inkMuted", "muted-foreground", "подписи, тихий текст"],
    ["line", "border", "линии и рамки"],
    ["accent", "primary", "кнопки и акценты"],
    ["accentInk", "primary-foreground", "текст на акценте"],
    ["accent2", "accent", "второй акцент"],
  ];
  const v2ColorRoles = $derived(
    V2_ROLE_SOURCES.map(([role, source, hint]) => ({
      role, source, hint, value: (styleGuide.tokens || {})[source],
    })).filter((row) => typeof row.value === "string" && row.value.startsWith("#")),
  );
  const v2TypeRoles = $derived([
    { role: "display", source: "font-display" },
    { role: "h1", source: "font-display" },
    { role: "h2", source: "font-display" },
    { role: "h3", source: "font-display" },
    { role: "lead", source: "font-body" },
    { role: "body", source: "font-body" },
    { role: "small", source: "font-body" },
    { role: "eyebrow", source: "font-body" },
  ].map((row) => ({ ...row, family: (styleGuide.tokens || {})[row.source] }))
    .filter((row) => typeof row.family === "string" && row.family));
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

  /* Каталог карточек (прототип ds: dsCat): слева категории, в центре сетка. */
  let dsCat = $state("all");
  const libCategories = $derived(componentGroups.map(([label, items]) => [label, items.length] as const));
  const gridEntries = $derived.by(() => {
    if (dsCat !== "all") {
      const hit = componentGroups.find(([label]) => label === dsCat);
      if (hit) return hit[1];
    }
    return componentGroups.flatMap(([, items]) => items);
  });
  function fidelityOf(comp: Record<string, any>): number | null {
    const value = comp?.fidelity?.viewports?.desktop?.pixelSimilarity;
    return Number.isFinite(Number(value)) ? Math.round(Number(value)) : null;
  }
  /* Мини-превью карточки: тот же IRRenderer, уменьшенный zoom-ом. */
  function cardPreview(node: HTMLElement, ir: unknown) {
    let disposed = false;
    const render = (value: unknown) => {
      node.innerHTML = "";
      if (!value) return;
      void loadRenderer().then(() => {
        if (disposed) return;
        try {
          const renderer = (window as any).IRRenderer;
          if (renderer) renderer.renderIR(node, JSON.parse(JSON.stringify(value)), { viewport: "desktop" });
        } catch { /* мини-превью не критично */ }
      });
    };
    render(ir);
    return { update: render, destroy: () => { disposed = true; } };
  }
  /* Сводка «Уходит в Генератор как style DNA» — из реальных данных документа. */
  const styleDnaSummary = $derived.by(() => {
    const hexTokens = styleTokens.filter(([, value]) => typeof value === "string" && value.startsWith("#")).length;
    return {
      colors: hexTokens || Object.keys(foundations.colors?.semantic || {}).length,
      weights: (foundations.typography?.weights || []).length,
      radii: (foundations.radii || []).length,
      components: components.length,
    };
  });
  /* Передать в Генератор: событие для графа (слушатель пока может быть no-op),
   * затем закрыть панель — контракт события фиксируем здесь. */
  function sendToGenerator() {
    const systemId = String(doc.id || data.systemId || "");
    window.dispatchEvent(new CustomEvent("designdna:ds-to-generator", { detail: { systemId } }));
    void cancel();
  }

  let previewHost = $state<HTMLElement | null>(null);
  let snapshot = $state("");
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
  const selectedPolish = $derived((selectedComp?.fidelity?.polish || {}) as Record<string, any>);
  const selectedPolishDefects = $derived((selectedPolish.defectsAfter || []) as Array<Record<string, any>>);
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
    // Capture the opening baseline once. Regular document updates are edits and
    // must not silently move the Cancel target forward.
    if (document && !snapshot) {
      snapshot = memoJson(document);
    }
  });

  const dirty = $derived(!!snapshot && memoJson(data.document) !== snapshot);
  const busy = $derived(publishing || validating || applying || saving || organizing || reviewing || exportingKit || !!$flowBusy[Number(nodeId)]);

  $effect(() => {
    if (activeTab === "components" && catalogEntries.length && !selectedComp) {
      selectedPool = catalogEntries[0].pool;
      selectedKey = catalogEntries[0].key;
      selectedVariant = "default";
    }
  });

  /* Ревью стиля запускается само, как только документ готов и ревью ещё нет:
   * это не «дополнительная кнопка», а часть разбора сайта. Запускаем один раз
   * на документ; отказ (нет провайдера, не выполнен вход) остаётся тихим —
   * измеренная часть стиль-гайда полноценна и без него. */
  let autoReviewFor = "";
  $effect(() => {
    const systemId = String(doc.id || "");
    if (!systemId || styleReview || reviewing || busy) return;
    if (autoReviewFor === systemId) return;
    autoReviewFor = systemId;
    void runStyleReview({ silent: true });
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
        if (ok) {
          snapshot = "";
        }
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

  /* AI-ревью мастеров: агент вместо пользователя решает судьбу пула «на ревью».
   * Запускается сам после сборки кита, пока есть кандидаты; сервер сравнивает
   * оригинал и рендер vision-моделью (Codex/Claude через консольный аккаунт
   * или OpenAI) и переносит одобренные мастера в реестр. */
  let masterReviewing = $state(false);
  let masterReviewNote = $state("");
  let autoMasterReviewFor = "";
  $effect(() => {
    const systemId = String(doc.id || "");
    if (!systemId || masterReviewing || busy || !reviewComponents.length) return;
    if (autoMasterReviewFor === systemId) return;
    autoMasterReviewFor = systemId;
    void runMasterReview({ silent: true });
  });

  async function runMasterReview({ silent = false }: { silent?: boolean } = {}) {
    if (!doc.id || masterReviewing) return;
    masterReviewing = true;
    if (!silent) actionError = "";
    $flow.setNodeData(Number(nodeId), { busyAction: "master-review", lastError: "" });
    try {
      const resp = await fetch("/api/design-system/master-review", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document: doc, provider: reviewProvider === "openai" ? "auto" : reviewProvider, viewport }),
      });
      const result = await resp.json();
      if (!resp.ok || result.error) throw new Error(result.error || `HTTP ${resp.status}`);
      if (result.reviewed) {
        pushUndo();
        $flow.setNodeData(Number(nodeId), { document: result.document, summary: result.summary, status: "draft" });
      }
      const failed = (result.results || []).filter((r: any) => r.error).length;
      masterReviewNote = result.reviewed
        ? `одобрено ${result.approved} из ${result.reviewed}${failed ? `, ошибок ${failed}` : ""}`
        : "нечего проверять";
    } catch (e) {
      if (!silent) actionError = e instanceof Error ? e.message : String(e);
      masterReviewNote = "";
    } finally {
      masterReviewing = false;
      $flow.setNodeData(Number(nodeId), { busyAction: "" });
    }
  }

  async function runStyleReview({ silent = false }: { silent?: boolean } = {}) {
    if (!doc.id) return;
    reviewing = true;
    if (!silent) actionError = "";
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
      if (!silent) activeTab = "styleguide";
    } catch (e) {
      // Автозапуск не должен кричать ошибкой на весь экран: измеренная часть
      // стиль-гайда полноценна и без AI-ревью. Ручной запуск — сообщает.
      if (!silent) actionError = e instanceof Error ? e.message : String(e);
    } finally {
      reviewing = false;
      $flow.setNodeData(Number(nodeId), { busyAction: "" });
    }
  }

  /* Живой UI kit: сервер собирает самодостаточный HTML (шрифты, картинки и
   * движок рендера внутри). Клиент открывает его прямо в разделе
   * «Компоненты» — там же, где каталог, — а сохранение в файл остаётся
   * отдельным действием рядом с превью. */
  async function buildStyleguide(): Promise<Uint8Array | null> {
    if (!doc.id) return null;
    exportingKit = true;
    actionError = "";
    $flow.setNodeData(Number(nodeId), { busyAction: "styleguide", lastError: "" });
    try {
      const resp = await fetch("/api/design-system/styleguide", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document: doc, includeProof: true }),
      });
      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}));
        throw new Error(detail.error || `HTTP ${resp.status}`);
      }
      const bytes = new Uint8Array(await resp.arrayBuffer());
      kitBytes = bytes;
      kitReport = {
        filename: resp.headers.get("X-DesignDNA-Filename") || "ui-kit.html",
        bytes: Number(resp.headers.get("X-DesignDNA-Bytes")) || bytes.length,
        components: Number(resp.headers.get("X-DesignDNA-Components")) || 0,
        warnings: Number(resp.headers.get("X-DesignDNA-Warnings")) || 0,
      };
      // Blob-URL, а не srcdoc: кит весит мегабайты, и атрибут такого размера
      // браузер разбирает заметно дольше отдельного документа.
      if (kitUrl) URL.revokeObjectURL(kitUrl);
      kitUrl = URL.createObjectURL(new Blob([bytes], { type: "text/html" }));
      return bytes;
    } catch (e) {
      actionError = `UI Kit: ${e instanceof Error ? e.message : String(e)}`;
      return null;
    } finally {
      exportingKit = false;
      $flow.setNodeData(Number(nodeId), { busyAction: "" });
    }
  }

  /** Кнопка шапки: собрать кит и показать его в разделе «Компоненты». */
  async function openStyleguide() {
    activeTab = "source";
    sourceView = "kit";
    await buildStyleguide();
  }

  async function saveStyleguideFile() {
    const bytes = kitBytes || (await buildStyleguide());
    if (!bytes) return;
    savingKit = true;
    try {
      const filename = kitReport?.filename || "ui-kit.html";
      const desktopFiles = window.designDNA?.files;
      if (desktopFiles) {
        // Кусками по 32 КБ: String.fromCharCode(...bytes) на мегабайтах
        // упирается в лимит числа аргументов (образец MotionWorkspace).
        let binary = "";
        for (let offset = 0; offset < bytes.length; offset += 32_768) {
          binary += String.fromCharCode(...bytes.subarray(offset, offset + 32_768));
        }
        await desktopFiles.save(filename, btoa(binary));
      } else if (kitUrl) {
        // Тот же Blob, что показан в превью: второй копии мегабайтов не нужно.
        const anchor = document.createElement("a");
        anchor.href = kitUrl;
        anchor.download = filename;
        anchor.click();
      }
    } catch (e) {
      actionError = `UI Kit: ${e instanceof Error ? e.message : String(e)}`;
    } finally {
      savingKit = false;
    }
  }

  // Blob живёт до закрытия редактора: пока кит открыт во вкладке, ссылку
  // отзывать нельзя, иначе iframe теряет документ при перерисовке.
  $effect(() => () => {
    if (kitUrl) URL.revokeObjectURL(kitUrl);
  });

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
      snapshot = "";
      undoStack = [];
      appliedEdit = null;
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

  async function rollbackPolish() {
    if (!selectedKey || !selectedComp?.polish?.before) return;
    actionError = "";
    try {
      const resp = await fetch("/api/design-system/polish/rollback", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document: doc, componentKey: selectedKey }),
      });
      const result = await resp.json();
      if (!resp.ok || result.error) throw new Error(result.error || `HTTP ${resp.status}`);
      pushUndo();
      $flow.setNodeData(Number(nodeId), { document: result.document, summary: result.summary, status: "draft" });
    } catch (e) {
      actionError = e instanceof Error ? e.message : String(e);
    }
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

<div class="ds-editor-overlay" role="dialog" aria-modal="true" aria-label="Редактор Design System" data-ds-editor>
  <header class="ds-editor-top">
    <div>
      <strong>◈ {data.name}</strong>
      <span class="ds-editor-meta" title="Мастер — точный компонент, извлечённый из Source (импортированного сайта) и хранимый как Design IR, промежуточное представление макета">
        {data.status === "published" ? `Опубликовано · v${data.revision}` : "Черновик"}
        {data.defaultSet ? " · проект по умолчанию" : ""}
        · мастеров из Source: {catalogEntries.length} · принято: {components.length} · предложений: {semanticSuggestions.length}
        {dirty ? " · несохранённые правки" : ""}
      </span>
    </div>
    <div class="ds-editor-actions">
      <button type="button" data-ds-action="styleguide" aria-label="Собрать живой UI Kit и открыть в разделе «Компоненты»"
              title="UI Kit — живой набор компонентов дизайн-системы (DS), собранный из мастеров Source"
              aria-busy={exportingKit} onclick={() => void openStyleguide()} disabled={busy || !catalogEntries.length}>
        {exportingKit ? "Сборка…" : "UI Kit"}
      </button>
      <button type="button" data-ds-action="validate" aria-label="Проверить документ" aria-busy={validating} onclick={validate} disabled={busy || !components.length}>
        {validating ? "Проверка…" : "Проверить"}
      </button>
      <button type="button" data-ds-action="publish" aria-label="Опубликовать immutable-ревизию" aria-busy={publishing} onclick={publish} disabled={busy || !components.length}>
        {publishing ? "Публикация…" : "Опубликовать ревизию"}
      </button>
      <button type="button" data-ds-action="default" aria-label="Назначить системой проекта" onclick={setDefault} disabled={busy || data.status !== "published" || data.defaultSet}>
        По умолчанию
      </button>
      <button type="button" data-ds-action="undo" aria-label="Отменить последнее изменение" onclick={() => void undo()} disabled={busy || (!undoStack.length && !appliedEdit)}>
        Отменить шаг
      </button>
      <button type="button" data-ds-action="cancel" aria-label="Отменить правки и закрыть" onclick={() => void cancel()} disabled={publishing}>
        Отмена
      </button>
      <button type="button" class="dna-btn-sell" data-ds-action="to-generator" aria-label="Передать систему в Генератор как style DNA" title="Style DNA — стилевой профиль системы (токены, правила, компоненты), по которому Генератор собирает новые страницы" onclick={sendToGenerator} disabled={publishing}>
        Передать в Генератор
      </button>
      <button type="button" class="close" data-ds-action="close" aria-label="Закрыть редактор" onclick={() => void cancel()}>✕</button>
    </div>
  </header>
  {#if actionError}
    <div class="ds-editor-error" role="alert">{actionError}</div>
  {/if}

  <nav class="ds-section-tabs" aria-label="Разделы дизайн-системы">
    <button type="button" data-ds-tab="source" class:active={activeTab === "source" || activeTab === "components"} onclick={() => (activeTab = "source")}>Компоненты <span>{catalogEntries.length}</span></button>
    <button type="button" data-ds-tab="styleguide" class:active={activeTab === "styleguide"} onclick={() => (activeTab = "styleguide")}>Стиль сайта{#if styleReview}<span>AI</span>{/if}</button>
    {#if isDiagnosticView}
      <!-- Диагностические экраны (Validation, Tests, Proof…) больше не занимают
           постоянный ряд вкладок: они открываются своим действием и здесь
           показывают, где пользователь находится и как вернуться. -->
      <span class="ds-diagnostic-crumb">{DIAGNOSTIC_LABELS[activeTab] || activeTab}</span>
      <button type="button" class="ds-tab-more" onclick={() => (activeTab = "source")}>← К компонентам</button>
    {/if}
  </nav>

  <div class="ds-editor-body" class:source-overview={activeTab === "source"} class:styleguide-overview={activeTab === "styleguide"} class:catalog-cols={activeTab === "components"}>
    <aside class="ds-editor-lib">
      <nav class="ds-legacy-tabs" aria-hidden="true"></nav>

      {#if activeTab === "source"}
        <div class="ds-source-views" role="tablist" aria-label="Вид раздела «Компоненты»">
          <button type="button" role="tab" data-ds-source-view="catalog" aria-selected={sourceView === "catalog"}
                  class:active={sourceView === "catalog"} onclick={() => (sourceView = "catalog")}>Каталог</button>
          <button type="button" role="tab" data-ds-source-view="kit" aria-selected={sourceView === "kit"}
                  class:active={sourceView === "kit"} aria-busy={exportingKit}
                  onclick={() => void (kitUrl ? (sourceView = "kit") : openStyleguide())}>
            Живой UI Kit{#if kitReport}<span>{kitReport.components}</span>{/if}
          </button>
          {#if semanticSuggestions.length}
            <button type="button" role="tab" data-ds-tab="suggestions" aria-selected="false"
                    onclick={() => (activeTab = "suggestions")}>
              Предложения <span>{semanticSuggestions.length}</span>
            </button>
          {/if}
          {#if sourceView === "kit"}
            <div class="ds-kit-tools">
              {#if kitReport}
                <small>{kitReport.filename} · {(kitReport.bytes / 1_048_576).toFixed(1)} МБ{kitReport.warnings ? ` · ${kitReport.warnings} предупреждений` : ""}</small>
              {/if}
              <button type="button" data-ds-action="styleguide-rebuild" onclick={() => void buildStyleguide()} disabled={busy || exportingKit}>
                {exportingKit ? "Сборка…" : "Пересобрать"}
              </button>
              <button type="button" data-ds-action="styleguide-save" onclick={() => void saveStyleguideFile()} disabled={exportingKit || savingKit}>
                {savingKit ? "Сохранение…" : "Сохранить HTML"}
              </button>
            </div>
          {/if}
        </div>
        {#if sourceView === "kit"}
          <div class="ds-kit-view">
            {#if kitUrl}
              <!-- Кит самодостаточен и рисует мастера своим встроенным движком:
                   отдаём ему песочницу со скриптами, но без доступа к приложению. -->
              <iframe title="Живой UI Kit" src={kitUrl} sandbox="allow-scripts allow-popups" data-ds-kit-frame></iframe>
            {:else}
              <div class="ds-kit-empty">{exportingKit ? "Собираем живой кит…" : "Кит ещё не собран — нажмите «UI Kit» в шапке."}</div>
            {/if}
          </div>
        {:else}
          <SourceArtifactPanel
            artifact={sourceArtifact}
            {catalogEntries}
            {catalog}
            acceptedMasters={Number((data.summary as Record<string, unknown> | null)?.components || components.length)}
            acceptedVariants={Number((data.summary as Record<string, unknown> | null)?.variants || 0)}
            onOpen={selectCatalogComponent}
          />
        {/if}
      {:else if activeTab === "components"}
        <div class="ds-lib-heading">
          <div><strong>Библиотека компонентов</strong><small>Точные семейства из Source, без дублей по контенту</small></div>
          <span>{catalogEntries.length}</span>
        </div>
        <section class="ds-ai-organizer" aria-label="AI-раскладка каталога компонентов">
          <div>
            <strong>AI-раскладка каталога</strong>
            <small>Группирует шапку, контролы, варианты кнопок и карточки. Точные мастера не меняются.</small>
          </div>
          <label>
            <span>Усилие Sol</span>
            <select bind:value={organizerEffort} disabled={busy}>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="max">max</option>
            </select>
          </label>
          <button type="button" data-ds-action="organize" onclick={() => void organizeCatalog()} disabled={busy || !catalogEntries.length}>
            {organizing ? "Раскладываю…" : "Разложить с Sol"}
          </button>
          <span class="ds-organizer-state" data-kind={catalog.organizer?.kind || "deterministic"}>
            {catalog.organizer?.kind === "ai" ? `gpt-5.6-sol · ${catalog.organizer.reasoningEffort}` : "детерминированная база"}
          </span>
        </section>
        <label class="ds-library-search">
          <span>Поиск компонентов</span>
          <input type="search" placeholder="По названию или категории" bind:value={componentSearch} />
        </label>
        <!-- Категории вместо вертикального списка: сами компоненты — карточками в центре. -->
        <nav class="ds-cat-list" aria-label="Категории компонентов">
          <button type="button" class:active={dsCat === "all"} onclick={() => (dsCat = "all")}>
            <span>Все</span><span class="ds-cat-count">{componentGroups.reduce((sum, [, items]) => sum + items.length, 0)}</span>
          </button>
          {#each libCategories as [label, count] (label)}
            <button type="button" class:active={dsCat === label} onclick={() => (dsCat = label)}>
              <span>{label}</span><span class="ds-cat-count">{count}</span>
            </button>
          {/each}
        </nav>
        <div class="ds-strict-note" title="Strict — Генератор не выходит за пределы дизайн-системы (DS): ни новых компонентов, ни чужих стилей">
          <strong>Strict-набор</strong>
          <small>Генератор собирает страницы только из этих компонентов.</small>
        </div>
      {:else if activeTab === "suggestions"}
        <div class="ds-lib-heading"><div><strong>Предложения</strong><small>Семантические гипотезы, отдельно от точных мастеров Source</small></div><span>{semanticSuggestions.length}</span></div>
        <div class="ds-suggestion-intro">Точные наблюдаемые мастера всегда видны в «Компонентах». В этой очереди — только выведенные дополнения, которые нужно явно включить в UI Kit.</div>
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
              <small>Запускается автоматически при готовом ките. Модель изучает дизайн-язык сайта: тон, правила, характер — новые компоненты генерируются по этому гайду.</small>
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
              {reviewing ? "Ревью…" : styleReview ? "Переснять ревью" : "Запустить вручную"}
            </button>
            <span class="ds-organizer-state" data-kind={styleGuide.origin === "ai" ? "ai" : "deterministic"}>
              {styleGuide.origin === "ai" ? `AI · ${styleGuide.provider || "openai"}` : "измеренная база"}
            </span>
          </section>

          <section class="ds-organizer" data-ds-master-review>
            <div>
              <strong>AI-ревью мастеров</strong>
              <small>Мастера, не прошедшие попиксельный порог, проверяет агент: сравнивает оригинал и рендер, одобряет без дефектов или называет конкретные. Подтверждение вручную не нужно.</small>
            </div>
            <button type="button" data-ds-action="master-review" onclick={() => void runMasterReview()} disabled={busy || !doc.id || !reviewComponents.length}>
              {masterReviewing ? "Ревью мастеров…" : reviewComponents.length ? `Проверить ${reviewComponents.length} на ревью` : "Всё проверено"}
            </button>
            {#if masterReviewNote}
              <span class="ds-organizer-state" data-kind="ai">{masterReviewNote}</span>
            {/if}
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

          {#if v2ColorRoles.length}
            <h4>Роли страницы (tokens v2)</h4>
            <p class="ds-sg-hint">Во что превращаются эти токены в IR генератора: цвет по ролям bg/surface/ink/accent и типографика по ролям display…eyebrow.</p>
            <div class="ds-sg-tokens">
              {#each v2ColorRoles as row (row.role)}
                <div class="ds-sg-token">
                  <i style="background:{row.value}"></i>
                  <div><strong>{row.role}</strong><small>{row.source} · {row.hint}</small></div>
                </div>
              {/each}
            </div>
            {#if v2TypeRoles.length}
              <div class="ds-sg-chips">
                {#each v2TypeRoles as row (row.role)}
                  <span><small>{row.role}</small>{row.family}</span>
                {/each}
              </div>
            {/if}
          {/if}

          <!-- Что именно получает Генератор: сводка вместо абстрактного обещания. -->
          <section class="ds-sg-dna" aria-label="Передача в Генератор">
            <div class="ds-sg-dna-head"><i aria-hidden="true"></i><strong>Уходит в Генератор как style DNA</strong></div>
            <p>Генератор строит варианты только на этих токенах и компонентах — стиль сайта сохраняется без отдельного промпта.</p>
            <div class="ds-sg-dna-grid">
              <div><strong>{styleDnaSummary.colors}</strong><small>цвета</small></div>
              <div><strong>{styleDnaSummary.weights}</strong><small>веса</small></div>
              <div><strong>{styleDnaSummary.radii}</strong><small>радиусы</small></div>
              <div><strong>{styleDnaSummary.components}</strong><small>компоненты</small></div>
            </div>
          </section>

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
                    <h4>Можно</h4>
                    <ul>{#each styleReview.doRules as rule}<li class="do">{rule}</li>{/each}</ul>
                  </div>
                {/if}
                {#if styleReview.dontRules?.length}
                  <div>
                    <h4>Нельзя</h4>
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
          <h4>Отступы</h4>
          <p>{Object.entries(foundations.spacing || {}).map(([k, v]) => `${k}=${v}`).join(" · ")}</p>
          <h4>Радиусы</h4>
          <p>{(foundations.radii || []).join(", ")}</p>
          <h4>Брейкпоинты</h4>
          <p>{Object.entries(foundations.breakpoints || {}).map(([k, v]) => `${k}≥${v}`).join(" · ")}</p>
        </div>
      {:else if activeTab === "identity"}
        <div class="ds-identity">
          <label>Soul · одной строкой
            <textarea value={identity.soul?.oneLine?.value || ""} onblur={(event) => void updateSoul(event.currentTarget.value)}></textarea>
          </label>
          <small>Статус: {identity.status || "not-extracted"} · подтверждение палитры {Math.round((identity.paletteCoverage?.confidence || 0) * 100)}%</small>
          <h4>Сигнатуры</h4>
          {#each identity.signatures || [] as signature (signature.id)}
            <article>
              <strong>{signature.name}</strong>
              <p>{signature.rule}</p>
              <small>{signature.provenance} · {Math.round((signature.confidence || 0) * 100)}%</small>
              {#if !signature.confirmed}<button type="button" onclick={() => void confirmIdentityItem("signatures", signature.id)}>Подтвердить</button>{/if}
            </article>
          {/each}
          <h4>Запреты</h4>
          {#each identity.bans || [] as ban (ban.id)}
            <article><strong>{ban.severity} · {ban.rule}</strong><small>{ban.provenance} · {Math.round((ban.confidence || 0) * 100)}%</small>
              {#if !ban.confirmed}<button type="button" onclick={() => void confirmIdentityItem("bans", ban.id)}>Подтвердить</button>{/if}
            </article>
          {/each}
          {#if identity.uncertainty?.length}<h4>Неопределённость</h4>{/if}
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
          {#if identityResult}<p class:ds-test-fail={!identityResult.passed}>Оценка {identityResult.score}% · {identityResult.passed ? "жёсткие правила пройдены" : "нарушено жёсткое правило"}</p>{/if}
          {#each identityTests as test (test.id)}
            {@const result = identityResult?.results?.find((item: any) => item.id === test.id)}
            <article class:ds-test-fail={result && !result.passed}><strong>{result ? (result.passed ? "✓" : "⛔") : "○"} {test.severity} · {test.description}</strong><small>{test.id} · {test.provenance} · {Math.round((test.confidence || 0) * 100)}%</small></article>
          {/each}
        </div>
      {:else if activeTab === "proof"}
        <div class="ds-identity">
          <p>Reconstruction проверяет перенос identity тем же валидатором, который используется после генерации.</p>
          <button type="button" onclick={() => void runProof("source")} disabled={proofRunning || !components.length}>{proofRunning ? "Проверяю…" : "Proof по Source"}</button>
          <button type="button" onclick={() => void runProof("transfer")} disabled={proofRunning || !components.length}>Proof переноса</button>
          {#if reconstruction.sourceProof}<article><strong>Source · {reconstruction.sourceProof.status}</strong><p>Identity {reconstruction.sourceProof.identityScore}%</p></article>{/if}
          {#if reconstruction.transferProof}<article><strong>Перенос · {reconstruction.transferProof.status}</strong><p>Identity {reconstruction.transferProof.identityScore}%</p></article>{/if}
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
            <p>Нажмите «Проверить» перед публикацией.</p>
          {/if}
        </div>
      {/if}
    </aside>

    <main class="ds-editor-canvas" class:ds-catalog-mode={activeTab === "components"}>
      {#if activeTab === "components"}
        <!-- Сетка каталога: живой мини-рендер на светлой поверхности + мета. -->
        <div class="ds-card-grid" aria-label="Каталог компонентов">
          {#each gridEntries as entry (entry.pool + ":" + entry.key)}
            {@const comp = entry.component}
            {@const variantCount = Object.keys(comp.variants || {}).length}
            {@const fidelity = fidelityOf(comp)}
            <button type="button" class="ds-card" class:active={selectedPool === entry.pool && selectedKey === entry.key}
                    data-ds-component={entry.key} data-ds-pool={entry.pool} aria-label={`Выбрать компонент ${comp.name}`}
                    onclick={() => selectCatalogComponent(entry.key, entry.pool)}>
              <span class="ds-card-preview" aria-hidden="true">
                <span class="ds-card-render" use:cardPreview={comp.masterIr || comp.templateIr}></span>
              </span>
              <span class="ds-card-info">
                <span class="ds-card-title">
                  <span class="ds-status-dot" class:verified={comp.status === "verified"} aria-hidden="true"></span>
                  <span class="ds-card-name">{comp.name}</span>
                  {#if comp.fidelity?.polish?.accepted}<span class="ds-polish-badge">Доведён</span>{/if}
                  {#if fidelity != null}<span class="ds-card-fidelity">{fidelity}%</span>{/if}
                </span>
                <small>{comp.provenance?.occurrenceCount || 1} observed · {variantCount} variant{variantCount === 1 ? "" : "s"}</small>
              </span>
            </button>
          {/each}
          {#if !gridEntries.length}<p class="ds-empty-filter">No components match “{componentSearch}”.</p>{/if}
        </div>
      {/if}
      {#if hasSelection && selectedComp}
        <header class="ds-workbench-head">
          <div class="ds-workbench-title">
            <span class="ds-eyebrow">{selectedComp.category || "component"} · exact Source family</span>
            <h2>{selectedComp.name}</h2>
            <div class="ds-component-meta">
              <span class:verified={selectedComp.status === "verified"}>{selectedComp.status === "verified" ? "Готов" : masterReviewing ? "AI доводит…" : "AI-доводка"}</span>
              {#if selectedPolish.accepted}<span class="ds-polish-badge">Доведён</span>{/if}
              {#if selectedPolishDefects.length}<span class="ds-polish-needed">Нужна доводка · {selectedPolishDefects.length}</span>{/if}
              <span>{selectedComp.provenance?.occurrenceCount || 1} наблюдений</span>
              <span>{Object.keys(selectedComp.variants || {}).length} вариантов</span>
            </div>
          </div>
          {#if selectedIsReview}
            <button type="button" class="ds-promote" data-ds-action="review" aria-label="Агент сверяет мастер с оригиналом и доводит его до готовности" onclick={() => void runMasterReview()} disabled={busy || masterReviewing}>{masterReviewing ? "AI доводит…" : "Довести агентом"}</button>
          {:else if selectedIsSuggestion}
            <button type="button" class="ds-promote" data-ds-action="promote" aria-label={selectedCanPromote ? "Продвинуть предложение в registry" : "Требуется повторная fidelity-проверка Source master"} onclick={() => void promoteSuggestion()} disabled={busy || !selectedCanPromote}>{selectedCanPromote ? "Включить в UI Kit" : "Нужна fidelity-проверка"}</button>
          {:else}
            <div class="ds-master-actions">
              {#if selectedComp.polish?.before}<button type="button" class="ds-promote" data-ds-action="rollback-polish" onclick={() => void rollbackPolish()} disabled={busy}>Откатить доводку</button>{/if}
              <button type="button" class="ds-edit-master" data-ds-action="apply" aria-label="Применить мастер-компонент в DNA Editor" aria-busy={applying} onclick={applyToEditor} disabled={busy || !hasSelection}>
                {applying ? "Открываю…" : "Открыть в DNA Editor"}
              </button>
            </div>
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
          <label class="ds-fixture" title="Показать сравнение с Source и метрики точности">
            <input type="checkbox" bind:checked={showFidelity} onchange={() => { if (!showFidelity) previewMode = "master"; }} /> Точность
          </label>
          {#if showFidelity}
            <div class="ds-viewport-switch" role="group" aria-label="Режим сравнения с Source">
              {#each ["reference", "master", "compare"] as mode (mode)}
                <button type="button" class:active={previewMode === mode} aria-pressed={previewMode === mode} onclick={() => { previewMode = mode as "reference" | "master" | "compare"; }}>
                  {mode === "reference" ? "Source" : mode === "master" ? "Мастер" : "Сравнить"}
                </button>
              {/each}
            </div>
          {/if}
          <label class="ds-fixture">
            Данные
            <select data-ds-field="preview-fixture" aria-label="Профиль mock в превью" bind:value={fixtureProfile}>
              <option value="source">Точно как в Source</option>
              <option value="typical">Типичные</option>
              <option value="short">Короткие</option>
              <option value="long">Длинные</option>
              <option value="empty">Пустые</option>
              <option value="loading">Загрузка</option>
              <option value="error">Ошибка</option>
              <option value="edge-case">Крайний случай</option>
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
      <div class="ds-canvas-empty" style:display={hasSelection ? "none" : "grid"}>Выберите мастер или предложение слева</div>
      <div class="ds-canvas-preview" data-ds-preview-host data-ds-preview-fixture={previewMeta?.fixture || fixtureProfile} bind:this={previewHost}></div>
    </main>

    <aside class="ds-editor-inspector">
      {#if hasSelection && selectedComp}
        <div class="ds-inspector-content">
          <span class="ds-inspector-kicker">Инспектор</span>
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
            <dt>Ключ</dt><dd><code>{selectedComp.componentKey}</code></dd>
            <dt>Происхождение</dt><dd>{originIcon(selectedComp.origin)} {selectedComp.origin} {selectedComp.confidence != null ? `· ${Math.round(selectedComp.confidence * 100)}%` : ""}</dd>
            <dt>Статус</dt><dd class:ds-fidelity-fail={selectedComp.status !== "verified"}>{selectedComp.status || "draft"}</dd>
            {#if selectedPolish.accepted}<dt>Доводка</dt><dd><span class="ds-polish-badge">Доведён</span></dd>{/if}
            {#if selectedPolishDefects.length}<dt>Нужна доводка</dt><dd>{selectedPolishDefects.map((d) => `${d.kind}: ${d.path} (${d.px}px)`).join("; ")}</dd>{/if}
            <dt>Категория</dt><dd>{selectedComp.category}</dd>
            <dt title="Props — параметры компонента в Design IR (промежуточном представлении макета), которыми его наполняет Генератор">Props</dt><dd>{Object.keys(selectedComp.propsSchema || {}).join(", ") || "—"}</dd>
            <dt>Состояния</dt>
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
            {#if selectedComp.provenance?.sourceBlocks?.length}<dt>Блоки</dt><dd>{selectedComp.provenance.sourceBlocks.join(", ")}</dd>{/if}
            {#if showFidelity && Object.keys(fidelityMetrics).length}
              <dt title="Fidelity — точность воспроизведения мастера относительно Source: сходство пикселей, покрытие краски, ошибка рамок">Fidelity</dt>
              <dd class:ds-fidelity-fail={selectedComp.status !== "verified"}>
                similarity {fidelityMetrics.pixelSimilarity ?? "—"}% · paint {fidelityMetrics.paintCoverage ?? "—"}%<br />
                bbox p95 {fidelityMetrics.bboxP95 ?? "—"}px · origin {fidelityMetrics.originError ?? "—"}px · losses {fidelityMetrics.unexplainedLosses ?? "—"}
              </dd>
            {/if}
            {#if selectedSourceRef.sourceRevisionHash}<dt>Ревизия</dt><dd><code>{String(selectedSourceRef.sourceRevisionHash).slice(0, 20)}…</code></dd>{/if}
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
  /* Приватная палитра панели заменена на глобальные --dna-* токены темы. */
  .ds-editor-overlay {
    --panel: var(--dna-panel);
    --panel-raised: var(--dna-elevated);
    --panel-soft: var(--dna-hover);
    --border: var(--dna-border);
    --border-strong: var(--dna-border-strong);
    --text: var(--dna-text);
    --muted: var(--dna-muted);
    --subtle: var(--dna-faint);
    --accent: var(--dna-violet-l);
    --accent-soft: rgba(112, 24, 230, .22);
    --success: var(--dna-success);
    position: fixed;
    inset: 0;
    z-index: 200;
    display: flex;
    flex-direction: column;
    background: var(--dna-bg);
    color: var(--text);
    font-family: inherit;
  }
  .ds-editor-top {
    min-height: 60px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 20px;
    padding: 0 18px;
    border-bottom: 1px solid var(--border);
    background: var(--dna-panel-2);
  }
  .ds-editor-top > div:first-child { min-width: 0; display: flex; align-items: baseline; }
  .ds-editor-top strong { flex: none; font-size: 15px; letter-spacing: -.01em; }
  .ds-editor-meta { min-width: 0; margin-left: 14px; overflow: hidden; color: var(--muted); font-size: 11.5px; text-overflow: ellipsis; white-space: nowrap; }
  .ds-editor-actions { flex: none; display: flex; align-items: center; gap: 7px; }
  .ds-editor-actions button:not(.dna-btn-sell),
  .ds-edit-master,
  .ds-promote {
    min-height: 34px;
    padding: 0 12px;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: var(--panel-raised);
    color: var(--dna-text-2);
    font: inherit;
    font-size: 11.5px;
    cursor: pointer;
  }
  .ds-editor-actions button:not(.dna-btn-sell):hover:not(:disabled), .ds-edit-master:hover:not(:disabled) { border-color: var(--border-strong); background: var(--panel-soft); }
  .ds-editor-actions button:disabled, .ds-edit-master:disabled, .ds-promote:disabled { opacity: .45; cursor: not-allowed; }
  .ds-editor-actions [data-ds-action="publish"] { border-color: var(--dna-violet); background: var(--dna-violet); color: #fff; }
  .ds-editor-actions .close { width: 34px; padding: 0; border-color: transparent; background: transparent; font-size: 15px; }
  .ds-editor-error { padding: 8px 18px; border-bottom: 1px solid rgba(229, 48, 92, .4); background: rgba(229, 48, 92, .12); color: var(--dna-danger-text); font-size: 12px; }

  .ds-section-tabs {
    flex: none;
    min-height: 46px;
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 6px 14px;
    overflow-x: auto;
    border-bottom: 1px solid var(--border);
    background: var(--dna-panel-2);
  }
  /* Основные вкладки крупнее: их всего две, и они несут ежедневную работу. */
  .ds-section-tabs:not(.ds-advanced-tabs) button:not(.ds-tab-more) { font-size: 12.5px; padding: 0 14px; }
  .ds-tab-more { margin-left: auto; color: var(--dna-faint) !important; font-size: 11px !important; }
  .ds-diagnostic-crumb {
    margin-left: 12px;
    border: 1px solid var(--border);
    border-radius: 999px;
    background: var(--dna-elevated);
    padding: 4px 10px;
    color: var(--dna-muted-2);
    font-size: 10.5px;
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
  .ds-section-tabs button:hover { background: var(--dna-hover); color: var(--dna-text-3); }
  .ds-section-tabs button.active { border-color: var(--dna-border-strong); background: var(--dna-hover); color: var(--dna-text); box-shadow: 0 1px 2px #0005; }
  .ds-section-tabs button span { min-width: 18px; padding: 1px 5px; border-radius: 999px; background: var(--dna-elevated); color: var(--dna-text-2); font-size: 10px; text-align: center; }

  .ds-editor-body { flex: 1; min-height: 0; display: grid; grid-template-columns: 300px minmax(0, 1fr) 300px; }
  /* Каталог: слева узкая колонка категорий, справа инспектор 300px. */
  .ds-editor-body.catalog-cols { grid-template-columns: 240px minmax(0, 1fr) 300px; }
  .ds-editor-body.source-overview { grid-template-columns: minmax(0, 1fr); background: var(--dna-bg); }
  .ds-editor-body.source-overview .ds-editor-lib { padding: 0; border-right: 0; background: var(--dna-bg); }
  .ds-editor-body.source-overview .ds-editor-canvas,
  .ds-editor-body.source-overview .ds-editor-inspector { display: none; }
  /* «Стиль сайта» — полноширинный обзор, как экран ds прототипа. */
  .ds-editor-body.styleguide-overview { grid-template-columns: minmax(0, 1fr); background: var(--dna-bg); }
  .ds-editor-body.styleguide-overview .ds-editor-lib { border-right: 0; background: var(--dna-bg); }
  .ds-editor-body.styleguide-overview .ds-editor-canvas,
  .ds-editor-body.styleguide-overview .ds-editor-inspector { display: none; }
  .ds-editor-body.styleguide-overview .ds-styleguide { max-width: 880px; margin: 0 auto; padding: 10px 6px 34px; }
  .ds-source-views { display: flex; align-items: center; gap: 6px; border-bottom: 1px solid var(--dna-border-soft); padding: 10px 16px; }
  .ds-source-views > button { border: 1px solid var(--dna-border); border-radius: 8px; background: var(--dna-node); padding: 6px 12px; color: var(--dna-muted); font-size: 11.5px; cursor: pointer; }
  .ds-source-views > button:hover { background: var(--dna-hover); color: var(--dna-text-3); }
  .ds-source-views > button.active { border-color: var(--dna-border-strong); background: var(--dna-hover); color: var(--dna-text); }
  .ds-source-views > button span { margin-left: 6px; border-radius: 999px; background: var(--dna-elevated); padding: 1px 5px; color: var(--dna-text-2); font-size: 9.5px; }
  .ds-kit-tools { display: flex; align-items: center; gap: 6px; margin-left: auto; }
  .ds-kit-tools small { color: var(--dna-faint); font-size: 9.5px; }
  .ds-kit-tools button { border: 1px solid var(--dna-border-strong); border-radius: 8px; background: var(--dna-elevated); padding: 6px 10px; color: var(--dna-text-2); font-size: 11px; cursor: pointer; }
  .ds-kit-tools button:hover:not(:disabled) { border-color: var(--dna-dim); }
  .ds-kit-tools button:disabled { opacity: .55; cursor: default; }
  .ds-kit-view { height: calc(100vh - 168px); min-height: 420px; background: var(--dna-bg); }
  .ds-kit-view iframe { display: block; width: 100%; height: 100%; border: 0; background: var(--dna-sunken); }
  .ds-kit-empty { display: grid; place-items: center; height: 100%; color: var(--dna-faint); font-size: 11px; }
  .ds-editor-lib, .ds-editor-inspector { min-width: 0; overflow-y: auto; background: var(--panel); scrollbar-color: var(--dna-border-strong) transparent; scrollbar-width: thin; }
  .ds-editor-lib { padding: 16px 14px 24px; border-right: 1px solid var(--border); }
  .ds-editor-inspector { padding: 18px; border-left: 1px solid var(--border); }
  .ds-legacy-tabs { display: none !important; }
  .ds-lib-heading { display: flex; align-items: start; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
  .ds-lib-heading div { min-width: 0; }
  .ds-lib-heading strong { display: block; font-size: 13px; }
  .ds-lib-heading small { display: block; margin-top: 4px; color: var(--subtle); font-size: 10.5px; line-height: 1.4; }
  .ds-lib-heading > span { min-width: 27px; padding: 3px 7px; border: 1px solid var(--border); border-radius: 999px; color: var(--dna-text-2); font-size: 10.5px; text-align: center; }
  .ds-library-search { display: block; margin-bottom: 16px; }
  .ds-ai-organizer {
    display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 8px 10px;
    margin: 0 0 14px; border: 1px solid var(--dna-border-strong); border-radius: 12px; padding: 11px 12px;
    background: linear-gradient(135deg, var(--dna-elevated), var(--dna-node)); box-shadow: inset 3px 0 var(--dna-violet-l);
  }
  .ds-ai-organizer > div { grid-column: 1 / -1; }
  .ds-ai-organizer > div strong, .ds-ai-organizer > div small { display: block; }
  .ds-ai-organizer > div strong { color: var(--dna-text-2); font-size: 11px; }
  .ds-ai-organizer > div small { margin-top: 3px; color: var(--dna-dim); font-size: 9px; line-height: 1.35; }
  .ds-ai-organizer label { display: grid; gap: 3px; color: var(--dna-faint); font-size: 8px; text-transform: uppercase; }
  .ds-ai-organizer select, .ds-ai-organizer button {
    min-height: 30px; border: 1px solid var(--dna-border-strong); border-radius: 8px; background: var(--dna-hover);
    padding: 0 9px; color: var(--dna-text-2); font-size: 9px;
  }
  .ds-ai-organizer button { border-color: var(--dna-violet); background: var(--dna-violet); color: #fff; font-weight: 700; cursor: pointer; }
  .ds-ai-organizer button:disabled { opacity: .45; cursor: not-allowed; }
  .ds-organizer-state { grid-column: 1 / -1; color: var(--dna-faint); font-size: 8px; }
  .ds-organizer-state[data-kind="ai"] { color: var(--dna-artifact); }
  .ds-library-search > span { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  .ds-library-search input {
    width: 100%;
    height: 36px;
    padding: 0 11px 0 32px;
    border: 1px solid var(--border);
    border-radius: 8px;
    outline: none;
    background: var(--dna-sunken)
      url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='14' height='14' viewBox='0 0 24 24' fill='none' stroke='%237b8496' stroke-width='2'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cpath d='m21 21-4.3-4.3'/%3E%3C/svg%3E")
      no-repeat 10px center;
    color: var(--text);
    font: inherit;
    font-size: 11.5px;
  }
  .ds-library-search input::placeholder { color: var(--dna-faint-2); }
  .ds-library-search input:focus { border-color: var(--dna-violet-l); box-shadow: 0 0 0 3px rgba(155, 92, 255, .15); }

  /* Категории каталога (прототип ds: dsCat). */
  .ds-cat-list { display: flex; flex-direction: column; gap: 3px; }
  .ds-cat-list button {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    min-height: 34px; padding: 0 10px; border: 1px solid transparent; border-radius: 8px;
    background: transparent; color: var(--dna-muted); font: inherit; font-size: 12px; font-weight: 600;
    text-align: left; cursor: pointer;
  }
  .ds-cat-list button:hover { background: var(--dna-hover); color: var(--dna-text-3); }
  .ds-cat-list button.active {
    border-color: rgba(155, 92, 255, .36); background: rgba(155, 92, 255, .14);
    color: var(--dna-text); font-weight: 700;
  }
  .ds-cat-count { color: var(--dna-faint); font-size: 10.5px; font-weight: 700; }
  .ds-strict-note { margin-top: 14px; padding: 12px; border: 1px solid var(--dna-border-soft); border-radius: 11px; background: var(--dna-node); }
  .ds-strict-note strong { display: block; margin-bottom: 5px; font-size: 11.5px; }
  .ds-strict-note small { display: block; color: var(--dna-dim); font-size: 10.5px; line-height: 1.5; }

  /* Сетка карточек каталога: превью на светлой поверхности + мета. */
  .ds-editor-canvas.ds-catalog-mode { overflow-y: auto; scrollbar-color: var(--dna-border-strong) transparent; scrollbar-width: thin; }
  .ds-editor-canvas.ds-catalog-mode .ds-canvas-preview { flex: none; min-height: 340px; }
  .ds-card-grid { flex: none; display: grid; grid-template-columns: repeat(auto-fill, minmax(232px, 1fr)); gap: 14px; }
  .ds-card {
    display: flex; flex-direction: column; align-items: stretch; padding: 0; overflow: hidden;
    border: 1px solid var(--dna-border); border-radius: 12px; background: var(--dna-node);
    color: var(--dna-text); font: inherit; text-align: left; cursor: pointer;
    transition: border-color .15s ease, box-shadow .15s ease;
  }
  .ds-card:hover { border-color: var(--dna-border-strong); }
  .ds-card.active { border-color: var(--dna-violet-l); box-shadow: 0 0 0 2px rgba(155, 92, 255, .18); }
  .ds-card-preview { height: 118px; margin: 6px 6px 0; display: grid; place-items: center; overflow: hidden; border-radius: 10px; background: #fdfdfd; }
  .ds-card-render { display: block; width: 760px; zoom: .26; pointer-events: none; }
  .ds-card-info { display: flex; flex-direction: column; gap: 3px; padding: 10px 13px 12px; }
  .ds-card-title { display: flex; align-items: center; gap: 7px; }
  .ds-card-name { min-width: 0; flex: 1; overflow: hidden; font-size: 13px; font-weight: 700; letter-spacing: -.01em; text-overflow: ellipsis; white-space: nowrap; }
  .ds-card-fidelity { flex: none; color: var(--dna-violet-text); font-size: 11px; font-weight: 700; }
  .ds-polish-badge { flex:none; color:var(--dna-success-text); font-size:11px; font-weight:700; }
  .ds-polish-needed { color:var(--dna-warning-text); font-size:11px; font-weight:700; }
  .ds-master-actions { display:flex; gap:8px; align-items:center; }
  .ds-card-info small { overflow: hidden; color: var(--dna-dim); font-size: 10.5px; text-overflow: ellipsis; white-space: nowrap; }

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
    color: var(--dna-text-2);
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .ds-comp-list button:hover { border-color: var(--dna-border); background: var(--dna-hover); }
  .ds-comp-list button.active { border-color: var(--dna-border-strong); background: var(--dna-hover-2); box-shadow: 0 1px 2px #0004; }
  .ds-status-dot { flex: none; width: 8px; height: 8px; border-radius: 999px; background: var(--dna-amber); box-shadow: 0 0 0 3px rgba(245, 166, 35, .08); }
  .ds-status-dot.verified { background: var(--success); box-shadow: 0 0 0 3px rgba(34, 197, 94, .1); }
  .ds-comp-name { overflow: hidden; font-size: 11.8px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
  .ds-empty-filter { padding: 24px 8px; color: var(--subtle); font-size: 11px; line-height: 1.5; text-align: center; }
  .ds-origin { flex: none; font-size: 10px; }
  .ds-origin[data-origin="observed"] { color: var(--success); }
  .ds-origin[data-origin="inferred"], .ds-origin[data-origin="suggested"] { color: var(--dna-amber); }
  .ds-origin[data-origin="generated"] { color: var(--dna-violet-text); }
  .ds-origin[data-origin="user"] { color: #68a9ff; }
  .ds-suggestion-intro { margin-bottom: 10px; padding: 10px; border: 1px solid rgba(245, 166, 35, .35); border-radius: 8px; background: rgba(245, 166, 35, .08); color: var(--dna-amber); font-size: 10.5px; line-height: 1.45; }
  .ds-comp-cat { margin-left: auto; color: var(--dna-dim); font-size: 10px; }

  .ds-editor-canvas { min-width: 0; display: flex; flex-direction: column; gap: 12px; padding: 18px; overflow: hidden; background: var(--dna-bg); }
  .ds-workbench-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
  .ds-workbench-title { min-width: 0; }
  .ds-eyebrow { display: block; margin-bottom: 3px; color: var(--dna-faint); font-size: 9.5px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
  .ds-workbench-head h2 { margin: 0; overflow: hidden; font-size: 18px; line-height: 1.25; letter-spacing: -.025em; text-overflow: ellipsis; white-space: nowrap; }
  .ds-component-meta { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 7px; }
  .ds-component-meta span { padding: 3px 7px; border: 1px solid var(--border); border-radius: 999px; color: var(--dna-muted); font-size: 9.5px; }
  .ds-component-meta span:first-child { color: var(--dna-amber); }
  .ds-component-meta span.verified { border-color: rgba(34, 197, 94, .4); background: rgba(34, 197, 94, .1); color: var(--dna-success-text); }
  .ds-edit-master { flex: none; border-color: var(--dna-violet); background: rgba(112, 24, 230, .16); color: var(--dna-violet-text); }
  .ds-promote { flex: none; border-color: rgba(245, 166, 35, .45); background: rgba(245, 166, 35, .08); color: var(--dna-amber); }
  .ds-canvas-head {
    flex: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 6px;
    border: 1px solid var(--border);
    border-radius: 10px;
    background: var(--dna-node);
  }
  .ds-viewport-switch { display: flex; align-items: center; gap: 3px; }
  .ds-viewport-switch button {
    min-height: 32px;
    padding: 0 11px;
    border: 1px solid transparent;
    border-radius: 7px;
    background: transparent;
    color: var(--dna-muted);
    font: inherit;
    font-size: 10.5px;
    cursor: pointer;
  }
  .ds-viewport-switch button:hover { color: var(--dna-text-3); }
  .ds-viewport-switch button.active { border-color: var(--dna-violet); background: rgba(112, 24, 230, .18); color: var(--dna-text); }
  .ds-fixture { display: flex; align-items: center; gap: 7px; margin-left: auto; color: var(--dna-dim); font-size: 10.5px; }
  .ds-fixture select { min-height: 32px; padding: 0 26px 0 9px; border: 1px solid var(--border); border-radius: 7px; background: var(--panel-raised); color: var(--dna-text-2); font: inherit; font-size: 10.5px; }
  .ds-variant-strip { flex: none; display: flex; align-items: center; gap: 6px; min-height: 46px; padding: 7px 9px; overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; background: var(--dna-sunken); }
  .ds-variant-label { flex: none; padding: 0 4px; color: var(--dna-faint); font-size: 9.5px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; }
  .ds-variant-strip button { flex: none; min-height: 32px; display: inline-flex; align-items: center; gap: 7px; padding: 0 9px; border: 1px solid var(--border); border-radius: 7px; background: var(--dna-elevated); color: var(--dna-text-2); font: inherit; font-size: 10.5px; cursor: pointer; }
  .ds-variant-strip button:hover { border-color: var(--border-strong); }
  .ds-variant-strip button.active { border-color: var(--dna-violet-l); background: rgba(112, 24, 230, .18); color: var(--dna-text); box-shadow: 0 0 0 2px rgba(155, 92, 255, .12); }
  .ds-variant-strip button small { color: var(--dna-faint); font-size: 9px; }
  .ds-variant-swatch { width: 14px; height: 14px; border: 1px solid #ffffff33; border-radius: 4px; box-shadow: inset 0 0 0 1px #0002; }
  .ds-canvas-preview { flex: 1; min-height: 0; overflow: auto; scrollbar-color: var(--dna-border-strong) transparent; scrollbar-width: thin; }
  :global(.ds-preview-stage) { min-height: 100%; display: grid; grid-template-columns: minmax(0, 1fr); gap: 12px; align-items: start; }
  :global(.ds-preview-stage.ds-preview-compare) { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
  :global(.ds-preview-pane) { min-width: 0; min-height: 310px; display: flex; flex-direction: column; margin: 0; overflow: hidden; border: 1px solid var(--dna-border); border-radius: 12px; background: var(--dna-node); box-shadow: 0 8px 24px #0002; }
  :global(.ds-preview-pane figcaption) { flex: none; margin: 0; padding: 9px 11px; border-bottom: 1px solid var(--dna-border); background: var(--dna-elevated); color: var(--dna-muted); font-size: 9.5px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; }
  :global(.ds-reference-pane img), :global(.ds-reference-pane canvas) { display: block; max-width: 100%; height: auto; margin: 0 auto; background: #fff; }
  :global(.ds-master-pane .ir-preview) { width: 100%; max-width: 100%; margin: 0 auto; background: #fff; overflow: hidden !important; }
  .ds-canvas-empty { flex: 1; place-items: center; border: 1px dashed var(--dna-border); border-radius: 12px; color: var(--dna-faint-2); font-size: 12px; }

  .ds-inspector-kicker { display: block; margin-bottom: 5px; color: var(--dna-faint); font-size: 9.5px; font-weight: 700; letter-spacing: .09em; text-transform: uppercase; }
  .ds-editor-inspector h3 { margin: 0; font-size: 16px; letter-spacing: -.02em; }
  .ds-inspector-description { margin: 7px 0 18px; color: var(--dna-muted); font-size: 10.8px; line-height: 1.5; }
  .ds-inspector-section { padding: 14px 0; border-top: 1px solid var(--dna-border-soft); }
  .ds-inspector-section h4 { margin: 0 0 10px; color: var(--dna-dim); font-size: 9.5px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
  .ds-selected-variant { display: flex; align-items: center; gap: 10px; padding: 10px; border: 1px solid var(--border); border-radius: 9px; background: var(--dna-elevated); }
  .ds-selected-variant > i { flex: none; width: 30px; height: 30px; border: 1px solid #ffffff30; border-radius: 7px; box-shadow: inset 0 0 0 1px #0003; }
  .ds-selected-variant strong, .ds-selected-variant small { display: block; }
  .ds-selected-variant strong { font-size: 11.5px; }
  .ds-selected-variant small { margin-top: 3px; color: var(--dna-dim); font-size: 9.5px; }
  .ds-style-grid { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 7px 10px; font-size: 10px; }
  .ds-style-grid > span { color: var(--dna-dim); }
  .ds-style-grid code { max-width: 160px; overflow-wrap: anywhere; color: var(--dna-text-2); font-family: "SFMono-Regular", Consolas, monospace; text-align: right; }
  .ds-editor-inspector dl { display: grid; grid-template-columns: minmax(58px, auto) minmax(0, 1fr); gap: 7px 10px; margin: 0; font-size: 10px; line-height: 1.45; }
  .ds-editor-inspector dt { color: var(--dna-dim); }
  .ds-editor-inspector dd { min-width: 0; margin: 0; overflow-wrap: anywhere; color: var(--dna-text-2); }
  .ds-editor-inspector code { font-family: "SFMono-Regular", Consolas, monospace; font-size: 9.5px; }
  .ds-fidelity-fail { color: var(--dna-danger-text) !important; }
  .ds-state { display: inline-block; min-height: 24px; margin: 1px 4px 2px 0; padding: 0 7px; border: 1px solid var(--dna-border-strong); border-radius: 6px; background: var(--dna-elevated); color: inherit; font: inherit; font-size: 9.5px; cursor: pointer; }
  .ds-state:disabled { cursor: default; }
  .ds-state.unconfirmed { border-style: dashed; color: var(--dna-violet-text); }
  .ds-insp-empty { color: var(--dna-faint-2); font-size: 11px; }

  .ds-foundations h4 { margin: 14px 0 7px; color: var(--dna-faint); font-size: 9.5px; letter-spacing: .07em; text-transform: uppercase; }
  .ds-foundations p { margin: 0 0 10px; color: var(--dna-text-2); font-size: 10.5px; line-height: 1.55; }
  .ds-swatches { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; }
  .ds-swatch { min-width: 0; display: inline-flex; align-items: center; gap: 6px; overflow: hidden; color: var(--dna-muted-2); font-size: 9.5px; text-overflow: ellipsis; white-space: nowrap; }
  .ds-swatch i { flex: none; width: 20px; height: 20px; border: 1px solid var(--dna-border-strong); border-radius: 5px; }
  .ds-styleguide { display: grid; gap: 10px; align-content: start; }
  .ds-styleguide h4 { margin: 8px 0 0; font-size: 11px; }
  .ds-sg-review-bar { display: grid; gap: 8px; border: 1px solid var(--dna-border); border-radius: 10px; background: var(--dna-node); padding: 10px; }
  .ds-sg-review-bar strong { display: block; font-size: 11px; }
  .ds-sg-review-bar small { color: var(--dna-muted); font-size: 9px; line-height: 1.4; }
  .ds-sg-review-bar label { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--dna-muted); font-size: 9.5px; }
  .ds-sg-review-bar select { min-width: 0; border: 1px solid var(--dna-border-strong); border-radius: 7px; background: var(--dna-elevated); color: var(--dna-text-2); padding: 4px 6px; font-size: 10px; }
  .ds-sg-review-bar button { border: 1px solid var(--dna-border-strong); border-radius: 8px; background: var(--dna-elevated); padding: 7px 9px; color: var(--dna-text-2); font-size: 10px; cursor: pointer; }
  .ds-sg-review-bar button:hover:not(:disabled) { border-color: var(--dna-dim); }
  .ds-sg-hint { margin: 0; color: var(--dna-dim); font-size: 9.5px; line-height: 1.45; }
  .ds-sg-tokens { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 7px; }
  .ds-sg-token { display: flex; align-items: center; gap: 8px; min-width: 0; border: 1px solid var(--dna-border); border-radius: 10px; background: var(--dna-sunken); padding: 6px; }
  /* Свотч токена 34px — по споке раздела «Стиль сайта». */
  .ds-sg-token i { flex: none; display: grid; place-items: center; width: 34px; height: 34px; border: 1px solid var(--dna-border-strong); border-radius: 8px; color: var(--dna-muted); font-size: 9px; font-style: normal; }
  .ds-sg-token i.abstract { background: var(--dna-elevated); }
  .ds-sg-token div { min-width: 0; }
  .ds-sg-token strong { display: block; overflow: hidden; font-size: 10px; font-family: ui-monospace, "SFMono-Regular", Consolas, monospace; text-overflow: ellipsis; white-space: nowrap; }
  .ds-sg-token small { display: block; overflow: hidden; color: var(--dna-faint); font-size: 8.5px; text-overflow: ellipsis; white-space: nowrap; }
  /* «Уходит в Генератор как style DNA» — тот же градиент, что у карточки Design IR. */
  .ds-sg-dna { padding: 16px; border: 1px solid rgba(112, 24, 230, .35); border-radius: 14px; background: linear-gradient(150deg, rgba(112, 24, 230, .2), rgba(255, 105, 29, .1)); }
  .ds-sg-dna-head { display: flex; align-items: center; gap: 9px; margin-bottom: 8px; }
  .ds-sg-dna-head i { flex: none; width: 9px; height: 9px; border-radius: 999px; background: var(--dna-action); animation: ds-dna-pulse 2s ease-in-out infinite; }
  .ds-sg-dna-head strong { font-size: 12.5px; }
  .ds-sg-dna > p { margin: 0; color: var(--dna-muted-2); font-size: 11px; line-height: 1.55; }
  .ds-sg-dna-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 7px; margin-top: 12px; }
  .ds-sg-dna-grid > div { padding: 10px 6px; border: 1px solid rgba(112, 24, 230, .3); border-radius: 9px; background: rgba(0, 0, 0, .35); text-align: center; }
  .ds-sg-dna-grid strong { display: block; font-size: 16px; font-weight: 700; }
  .ds-sg-dna-grid small { color: var(--dna-dim); font-size: 9px; font-weight: 600; letter-spacing: .05em; text-transform: uppercase; }
  @keyframes ds-dna-pulse { 0%, 100% { opacity: .35; } 50% { opacity: 1; } }
  .ds-sg-chips { display: flex; flex-wrap: wrap; gap: 6px; }
  .ds-sg-chips span { border: 1px solid var(--dna-border); border-radius: 999px; background: var(--dna-elevated); padding: 4px 9px; color: var(--dna-text-2); font-size: 9.5px; }
  .ds-sg-chips small { margin-right: 5px; color: var(--dna-faint); }
  .ds-sg-traits { display: grid; gap: 6px; margin: 0; }
  .ds-sg-traits div { border-left: 2px solid var(--dna-border-strong); padding-left: 8px; }
  .ds-sg-traits dt { color: var(--dna-muted); font-size: 9px; text-transform: uppercase; letter-spacing: .06em; }
  .ds-sg-traits dd { margin: 2px 0 0; color: var(--dna-text-3); font-size: 10.5px; line-height: 1.45; }
  .ds-sg-rules { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .ds-sg-rules ul { margin: 4px 0 0; padding-left: 14px; }
  .ds-sg-rules li { margin-bottom: 4px; font-size: 10px; line-height: 1.4; }
  .ds-sg-rules li.do { color: var(--dna-success-text); }
  .ds-sg-rules li.dont { color: var(--dna-danger-text); }
  .ds-sg-note { margin: 0; color: var(--dna-muted-2); font-size: 9.5px; line-height: 1.45; }
  .ds-sg-note code { margin-right: 5px; color: var(--dna-violet-text); }
  .ds-mock-item { padding: 9px 0; border-bottom: 1px solid var(--dna-border-soft); }
  .ds-mock-item strong { display: block; font-size: 10.8px; }
  .ds-mock-item small { color: var(--dna-dim); font-size: 9.5px; }
  .ds-val-error, .ds-val-ok { margin-bottom: 6px; padding: 9px 10px; border-radius: 8px; font-size: 10.5px; line-height: 1.45; }
  .ds-val-error { border: 1px solid rgba(229, 48, 92, .4); background: rgba(229, 48, 92, .12); color: var(--dna-danger-text); }
  .ds-val-ok { border: 1px solid rgba(34, 197, 94, .4); background: rgba(34, 197, 94, .1); color: var(--dna-success-text); }
  .ds-identity { display: flex; flex-direction: column; gap: 8px; font-size: 10.5px; }
  .ds-identity h4 { margin: 10px 0 0; color: var(--dna-faint); font-size: 9.5px; letter-spacing: .07em; text-transform: uppercase; }
  .ds-identity label { display: flex; flex-direction: column; gap: 5px; color: var(--dna-muted); }
  .ds-identity textarea { min-height: 76px; resize: vertical; border: 1px solid var(--border); border-radius: 8px; background: var(--dna-sunken); color: var(--dna-text-2); padding: 9px; font: inherit; }
  .ds-identity article { padding: 9px; border: 1px solid var(--border); border-radius: 8px; background: var(--dna-elevated); }
  .ds-identity article strong, .ds-identity article small { display: block; }
  .ds-identity article p { margin: 5px 0; color: var(--dna-text-2); line-height: 1.45; }
  .ds-identity small { color: var(--dna-dim); }
  .ds-identity button { min-height: 30px; margin-top: 6px; padding: 0 9px; border: 1px solid var(--dna-border-strong); border-radius: 7px; background: var(--dna-hover); color: var(--dna-text-2); font: inherit; font-size: 9.8px; cursor: pointer; }
  .ds-uncertain { margin: 0; color: var(--dna-amber); }
  .ds-test-fail { color: var(--dna-danger-text) !important; border-color: rgba(229, 48, 92, .45) !important; }

  button:focus-visible, select:focus-visible, textarea:focus-visible, input:focus-visible { outline: 2px solid var(--dna-violet-l); outline-offset: 2px; }
  @media (max-width: 1220px) {
    .ds-editor-body { grid-template-columns: 260px minmax(0, 1fr) 260px; }
    .ds-editor-body.catalog-cols { grid-template-columns: 220px minmax(0, 1fr) 260px; }
    .ds-editor-top { padding-inline: 12px; }
    .ds-editor-actions { gap: 4px; }
    .ds-editor-actions button:not(.dna-btn-sell) { padding-inline: 9px; }
  }
  @media (max-width: 980px) {
    .ds-editor-body, .ds-editor-body.catalog-cols { grid-template-columns: 240px minmax(0, 1fr); }
    .ds-editor-inspector { display: none; }
    .ds-editor-meta { display: none; }
    :global(.ds-preview-stage.ds-preview-compare) { grid-template-columns: minmax(0, 1fr); }
  }
</style>
