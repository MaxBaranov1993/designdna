import type { Edge, Node } from "@xyflow/svelte";

export const PAGE_INPUT_LIMIT = 32;
export const PAGE_INPUT_NAMES = Array.from({ length: PAGE_INPUT_LIMIT }, (_, index) =>
  index < 26 ? String.fromCharCode(97 + index) : `block${index + 1}`);

/* Типы данных актуальных нод графа (см. docs/NODES.md).
 * Runtime-поля legacy (el/geo/history) в React Flow state не переносятся. */

/* kind tokens: design-токены из Source Import/Style DNA в Reskin/Derive. */
/* ds — ссылка на опубликованную дизайн-систему (systemId@revision), чтобы ДС шла в Генератор проводом, а не «из воздуха» */
export type PortKind = "text" | "ir" | "tokens" | "artifact" | "interaction" | "motion" | "timeline" | "video" | "ds" | "image";
export type PortDecl = { name: string; label: string; kind: PortKind; kinds: PortKind[] };

export type NodeType =
  | "prompt"
  | "reference"
  | "generator"
  | "edit"
  | "mix"
  | "page"
  | "sourceimport"
  | "designui"
  | "derive"
  | "reskin"
  | "qualitypass"
  | "recorder"
  | "motion"
  | "motiondesign"
  | "pagebridge"
  | "designsystem"
  | "timeline"
  | "image"
  | "removebackground";

export type IRObject = Record<string, unknown>;
export type SourceViewport = "desktop" | "tablet" | "mobile";
export type ParserDiagnostic = {
  code: string;
  severity: "info" | "warning" | "error";
  message: string;
  nodeRef?: string;
  viewport?: SourceViewport;
};
export type ParserLayoutEvidence = {
  id: string;
  nodeRef: string;
  role: "page-content" | "full-bleed" | "text-column" | "custom";
  anchor: "outer" | "inner-content" | "text" | "grid" | "start" | "center" | "end";
  viewport: SourceViewport;
  maxWidth: number;
  inlineGutter: number;
  confidence: number;
  basis: "measured" | "inferred";
};
export type ParserSourceEnvelope = {
  version: "parser-source-envelope/1.0";
  sourceRecord: Record<string, unknown> & { id: string; confidence: number };
  nodeStates: Record<string, Record<string, unknown>>;
  layoutEvidence: ParserLayoutEvidence[];
  viewports: Partial<Record<SourceViewport, {
    width: number;
    height?: number;
    layers?: number;
    coverage?: number;
    fidelity?: number;
  }>>;
  diagnostics: ParserDiagnostic[];
};
export type FeatureFlags = {
  irV11?: boolean;
  tailwindProjection?: boolean;
  fluidResponsive?: boolean;
  interactionRecorder?: boolean;
  motionEditor?: boolean;
  videoRender?: boolean;
  videoEditor?: boolean;
  aiDirector?: boolean;
};

export type PromptNodeData = { text: string };
export type ReferenceNodeData = {
  role?: import("./generator-visual").ReferenceRole;
  brief: string;
  image: string | null;
  fileName: string;
  decomposed: boolean;
  // IR, полученный по проводу через propagate (runtime-поле legacy, nodes.js:957-963)
  ir?: IRObject | null;
};
/** Маршрут AI, выбираемый в ноде. Sol и Astra — по одному OpenAI API-ключу, Codex и Claude — по
 *  подписке через локальный CLI (OAuth живёт внутри самого CLI). */
export type NodeProvider = "openai" | "astra" | "codex" | "claude";
export type GeneratorNodeData = {
  referenceRole?: import("./generator-visual").ReferenceRole;
  conceptMode?: "off" | "on";
  conceptRuns?: import("./generator-visual").ConceptRun[];
  assetConsistency?: "series" | "independent";
  assetMode?: "auto" | "codex" | "off";
  assetModel?: string;
  assetRuns?: import("./generator-assets").AssetRun[];
  surface?: string;
  designStyle?: string;
  provider: NodeProvider;
  effort: "medium" | "high" | "max";
  count: number;
  ownPrompt: string;
  preset: string;
  variants: IRObject[];
  active: number;
  /** Оценки встроенного Quality Pass по вариантам (null — судья не ответил). */
  qualityScores?: (number | null)[];
  generationContext?: { inputKey: string; baseInputKey?: string; pageId: string; brief: string; startedAt: number; designSystem?: Record<string, unknown> | null };
  /** Режим использования ДС для этой ноды: strict | extend | style-only (иначе — из пикера проекта). */
  designSystemUsageMode?: string;
  /** Журнал решений последней генерации: ДС, мастера в контексте, линт, автофиксы. */
  generationLog?: Record<string, unknown> | null;
};
export type SourceRecordView = {
  id: string;
  kind: string;
  label: string;
  colorToken?: string;
  symbol?: string;
  confidence?: number;
};
export type SourceAwareNodeData = {
  sourceRegistry?: Record<string, SourceRecordView>;
  nodeSources?: Record<string, string>;
  layoutEvidence?: ParserLayoutEvidence[];
};
export type EditNodeData = SourceAwareNodeData & {
  inputs: string[];
  ir: IRObject | null;
};
export type PageNodeData = SourceAwareNodeData & {
  inputs: string[];
  ir: IRObject | null;
  activeViewport: SourceViewport;
};
export type MixNodeData = {
  inputs: string[];
  weights: Record<string, number>;
  /** Сколько вариантов собрать (1–8) — счётчик из дизайн-хендоффа. */
  variants?: number;
  /** Промпт микса (хендофф): намерение смешения, хранится с нодой. */
  prompt?: string;
  /** Результаты последнего запуска: вариант 0 — точные веса, дальше —
   * детерминированная ротация акцента по входам. */
  mixVariants?: IRObject[];
  mixActive?: number;
  ir: IRObject | null;
};
/* Блок Source Import: lit — «зажжён» ли выходной порт блока. */
export type DroppedRecord = {
  sourceKey: string;
  reason: string;
  visual: boolean;
};
export type ExtraPaintRecord = {
  sourceKey: string;
  reason: string;
  visual: boolean;
  rect: { x: number; y: number; width: number; height: number };
};
export type BlockParseBlock = {
  name: string;
  label?: string;
  kind?: string;
  selector: string;
  ir?: IRObject;
  error?: string;
  cached?: boolean;
  source?: "dom" | "llm" | "vision";
  layers?: number;
  size?: { width?: number; height?: number };
  preview?: string;
  previews?: Partial<Record<SourceViewport, string>>;
  sizes?: Partial<Record<SourceViewport, { width?: number; height?: number }>>;
  layersByViewport?: Partial<Record<SourceViewport, number>>;
  editableLayersByViewport?: Partial<Record<SourceViewport, number>>;
  componentBoundariesByViewport?: Partial<Record<SourceViewport, number>>;
  coverage?: Partial<Record<SourceViewport, number>>;
  paintCoverage?: Partial<Record<SourceViewport, number>>;
  fidelity?: Partial<Record<SourceViewport, number | null>>;
  fidelityReport?: {
    gate?: { passed?: boolean; reasons?: string[] };
    viewports?: Partial<Record<SourceViewport, {
      pixel_similarity?: number | null;
      paint_coverage?: number | null;
      bbox_p95?: number | null;
      grid_origin_error?: number | null;
      unexplained_losses?: number | null;
      size_match?: boolean | null;
      gate?: { passed?: boolean; reasons?: string[] };
      [key: string]: unknown;
    }>>;
    [key: string]: unknown;
  };
  p95LayoutError?: Partial<Record<SourceViewport, number | null>>;
  droppedByViewport?: Partial<Record<SourceViewport, DroppedRecord[]>>;
  extrasByViewport?: Partial<Record<SourceViewport, ExtraPaintRecord[]>>;
  warnings?: string[];
  repeat?: { count?: number; kind?: string } | null;
  parserContract?: ParserSourceEnvelope;
  lit: boolean;
};
export type SourceArtifactViewport = {
  size?: { width?: number; height?: number };
  layers?: number;
  editableLayers?: number;
  coverage?: number;
  paintCoverage?: number;
  fidelity?: number;
  p95LayoutError?: number;
};
export type SourceArtifactComponent = {
  componentKey: string;
  name: string;
  role: string;
  master: { blockIndex: number; selector: string; irContentHash: string };
  states: Record<string, { observed: boolean; basis: "measured" | "inferred"; viewports: string[] }>;
  stateCoverage: { observed: string[]; inferred: string[] };
  responsive: Record<string, SourceArtifactViewport>;
  quality: { gate?: { passed?: boolean; reasons?: string[] }; warnings: string[] };
  provenance: { sourceRecord?: Record<string, unknown>; parserContractVersion?: string; nodeStateCount: number };
};
export type SourceArtifactFoundationGroup = {
  key: string;
  name: string;
  tokenCount: number;
};
export type SourceArtifactScreen = {
  screenKey: string;
  name: string;
  viewport: string;
  theme?: string;
  basis: "assembled-from-source-blocks";
  size: { width?: number; height?: number };
  componentKeys: string[];
  hierarchy: Array<{
    componentKey: string;
    name: string;
    role: string;
    blockIndex: number;
    selector: string;
  }>;
  metrics: {
    layers?: number;
    editableLayers?: number;
    fidelityMean?: number;
    fidelityMin?: number;
    p95LayoutErrorMax?: number;
  };
};
export type SourceArtifactLibrary = {
  componentSetCount: number;
  variantCount: number;
  observedStateCount: number;
};
export type SourceArtifact = {
  version: "source-artifact/1.0";
  source: { url: string; finalUrl?: string; authenticated: boolean; pipelineVersion: string };
  foundations: {
    tokens: Record<string, unknown> | null;
    groups?: SourceArtifactFoundationGroup[];
  };
  /** Additive fields are optional so persisted v1.0 projects remain readable. */
  screens?: SourceArtifactScreen[];
  library?: SourceArtifactLibrary;
  components: SourceArtifactComponent[];
  summary: {
    screenCount?: number;
    componentCount: number;
    componentSetCount?: number;
    variantCount?: number;
    observedStateCount: number;
    viewportCount: number;
    tokenGroupCount?: number;
    tokenCount?: number;
  };
};
export type SourceImportNodeData = {
  mode: "url" | "screenshot";
  url: string;
  image: string | null;
  fileName: string;
  mine: boolean;
  authenticatedSession: boolean;
  activeViewport: SourceViewport;
  previewMode: "reference" | "ir" | "compare";
  /** Last URL whose parsed blocks are already present in this node. */
  importedUrl?: string | null;
  blocks: BlockParseBlock[];
  tokens: Record<string, unknown> | null;
  sourceArtifact?: SourceArtifact | null;
  /** Опциональный AI-проход: уточняет имена компонентов и роли блоков. */
  aiRefine?: boolean;
  aiProvider?: NodeProvider;
  aiEffort?: "medium" | "high" | "max";
  pipelineStatus?: Record<string, AiPipelineStage>;
  lastRun?: {
    cached: boolean;
    pipelineVersion?: string;
    totalMs: number;
    timingsMs: Record<string, number>;
  } | null;
};
export type DesignUiNodeData = {
  artifact: SourceArtifact | null;
  selectedComponent: number;
};
export type DeriveNodeData = {
  provider?: NodeProvider;
  effort?: "medium" | "high" | "max";
  prompt: string;
  count: number;
  variants: IRObject[];
  active: number;
};

/* Reskin: маска — что модели разрешено менять (merge-back лочит остальное) */
export type ReskinMask = {
  colors: boolean;
  fonts: boolean;
  radii: boolean;
  shadows: boolean;
  texts: boolean;
  images: boolean;
};
export type ReskinNodeData = {
  prompt: string;
  provider: NodeProvider;
  effort: "medium" | "high" | "max";
  mask: ReskinMask;
  ir: IRObject | null;
  log: string[];
};
export type QualityPassNodeData = {
  brief: string;
  minScore: number;
  repair: boolean;
  /** Провайдер судьи/починки; легаси-сейвы без поля судят через Sol. */
  provider?: NodeProvider;
  ir: IRObject | null;
  result: Record<string, unknown> | null;
};
export type DesignSystemUsageMode = "strict" | "extend" | "style-only";
export type DesignSystemPickerChange = {
  selection: "inherit" | "none" | string;
  usageMode: DesignSystemUsageMode;
  fixtureProfile: string;
};
export type DesignSystemAiProvider = "inherit" | NodeProvider;
export type DesignSystemAiOperation = "organize" | "style-review" | "master-review";
export type AiPipelineStage = {
  status: "running" | "success" | "warning" | "failed" | "cancelled" | "skipped";
  message: string;
  provider?: NodeProvider;
  updatedAt: string;
  timings?: { elapsedMs: number; prepareMs: number; providerMs: number; applyMs: number; requests: number; retries: number };
};
export type DesignSystemNodeData = {
  /** Missing values inherit the provider of the Source wired to artifact. */
  aiProvider?: DesignSystemAiProvider;
  aiEffort?: "medium" | "high" | "max";
  pipelineStatus?: Record<string, AiPipelineStage>;
  systemId: string | null;
  name: string;
  status: "draft" | "published" | "outdated" | "archived";
  revision: number;
  contentHash?: string;
  summary: Record<string, unknown> | null;
  sourceNodeId: number | string | null;
  defaultSet: boolean;
  sourceUpdate: boolean;
  autoPublish: boolean;
  /* Кэш редактирования: полный документ живёт на сервере (draft — revision 0),
   * в ноде — только ссылка systemId@revision+contentHash; документ грузится
   * по требованию при открытии панели. */
  document?: Record<string, unknown> | null;
  lastError?: string;
  busyAction?: "publish" | "default" | "sync" | "validate" | "apply" | DesignSystemAiOperation | "";
} & Record<string, unknown>;

export type PageBridgeNodeData = {
  channel: string;
  mode: "send" | "receive";
  ir: IRObject | null;
};
export type InteractionObject = Record<string, unknown>;
export type InteractionDraftEvent = {
  id: string;
  time: number;
  type: "click" | "type" | "scroll" | "navigate" | "focus" | "blur" | "submit";
  targetSourceKey: string;
  payload: Record<string, unknown>;
  resultingSceneId: string;
};
export type InteractionDraftScene = {
  id: string;
  viewport: SourceViewport;
  patch: Array<{ op: "add" | "replace" | "remove"; path: string; value?: unknown }>;
};
export type InteractionLiveAction = {
  type: "click" | "type" | "scroll" | "navigate" | "focus" | "submit";
  targetSourceKey: string;
  selector: string;
  value?: string;
  y?: number;
  url?: string;
};
export type RecorderNodeData = {
  ir: IRObject | null;
  interaction: InteractionObject | null;
  recording: boolean;
  selectedTarget: string;
  selectedPath: string;
  draftEvents: InteractionDraftEvent[];
  draftScenes: InteractionDraftScene[];
  mode: "preview" | "live";
  liveUrl: string;
  mine: boolean;
  liveViewport: SourceViewport;
};
export type MotionSceneSettings = {
  duration: number;
  transition: "cut" | "fade" | "slide-left" | "slide-up" | "zoom";
  transitionDuration: number;
  easing: "linear" | "ease" | "ease-in" | "ease-out" | "ease-in-out";
};
export type MotionScenePreview = { sceneId: string; ir: IRObject };
/* Слой композиции Motion Editor (см. README хендоффа, State Management).
 * Времена кейфреймов — локальные мс внутри сцены; sceneId привязывает слой
 * к композиции (сцене построенного motion). */
export type MotionLayerKeyframe<V> = { t: number; v: V };
export type MotionCompLayer = {
  id: string;
  name: string;
  group: "src" | "kit" | "gen" | "media";
  type: "text" | "image" | "comp";
  sceneId?: string;
  text?: string;
  src?: string;
  size: number;
  weight: number;
  color: string;
  w: number;
  props: {
    p: { keys: Array<MotionLayerKeyframe<[number, number]>> };
    s: { keys: Array<MotionLayerKeyframe<number>> };
    r: { keys: Array<MotionLayerKeyframe<number>> };
    o: { keys: Array<MotionLayerKeyframe<number>> };
  };
};
export type MotionRenderJob = {
  id: string;
  status: "queued" | "rendering" | "complete" | "error";
  progress: number;
  framesDone?: number;
  framesTotal?: number;
  filename?: string;
  downloadUrl?: string;
  error?: string;
  result?: { bytes?: number; frames?: number; width?: number; height?: number; fps?: number; duration?: number };
};
export type MotionNodeData = {
  ir: IRObject | null;
  interaction: InteractionObject | null;
  /* Сцены композиции авторятся в самой ноде (Recorder исключён из хендоффа);
   * runMotion строит из них Interaction IR, когда провода interaction нет. */
  scenes?: InteractionDraftScene[];
  /* Слои композиций Motion Editor; пусто — воркспейс выводит дефолтный
   * набор из IR сцены (детерминированно). */
  layers?: MotionCompLayer[];
  motion: IRObject | null;
  sceneIrs: MotionScenePreview[];
  selectedScene: number;
  composition: { width: number; height: number; fps: number };
  renderSettings: { format: "mp4" | "webm"; quality: "draft" | "high" | "lossless" };
  renderJob: MotionRenderJob | null;
  sceneSettings: Record<string, Partial<MotionSceneSettings>>;
};

export type VideoEffort = "low" | "medium" | "high" | "xhigh" | "max" | "ultra";
/* Persistent video revisions include the source needed to verify restoration. */
export type VideoRevision = {
  id: string;
  parentId: string | null;
  createdAt: string;
  kind: "initial" | "manual" | "prompt" | "restore";
  label: string;
  prompt?: string;
  provider?: NodeProvider;
  effort?: VideoEffort;
  model?: string;
  restoredFrom?: string;
  sourceIr: IRObject | null;
  timeline: IRObject;
};
export type VideoRevisionChange = Pick<VideoRevision, "kind" | "label"> &
  Partial<Pick<VideoRevision, "prompt" | "provider" | "effort" | "model" | "restoredFrom">>;
export type VideoChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  createdAt: string;
  provider?: "codex" | "claude";
  kind?: "message" | "question" | "error" | "preview" | "applied" | "cancelled";
};
export type TimelineNodeData = {
  aiPreview?: {
    chatMessageId: string; prompt: string; provider: "codex" | "claude"; effort: VideoEffort; model: string;
    timeline: Record<string, any>; changeSet: Record<string, any>; baseTimeline: Record<string, any>;
    intent: string; planSource: string; warning: string | null; operations: number;
  } | null;
  directorRunId?: string | null;
  directorStartedAt?: number;
  chatMessages?: VideoChatMessage[];
  inputs?: string[];
  pageNames?: Record<string, string>;
  sourcePages?: Array<{ id: string; name: string; ir: IRObject }>;
  prompt?: string;
  revisions?: VideoRevision[];
  activeRevisionId?: string | null;
  provider?: NodeProvider;
  effort?: VideoEffort;
  model?: string;
  ir: IRObject | null;
  timeline: IRObject | null;
  settings: { width: number; height: number; fps: number; duration: number };
  renderJob: MotionRenderJob | null;
};

export type VideoArtifact = {
  version: "video-artifact/1.0";
  origin: "motion-editor" | "video-editor" | "motion-design";
  jobId: string;
  downloadUrl: string;
  filename: string;
  mime: "video/mp4" | "video/webm";
  width?: number;
  height?: number;
  fps?: number;
  duration?: number;
  bytes?: number;
  parameters?: Record<string, unknown>;
};

export type MotionDesignPlanner = "direct" | "openai" | "astra" | "claude";
export type SeedanceVideoJob = {
  id: string;
  status: "pending" | "queued" | "processing" | "running" | "completed" | "failed" | "cancelled" | "expired";
  model: "bytedance/seedance-2.5";
  created_at?: number | string;
  usage?: { cost?: number; [key: string]: unknown };
  error?: unknown;
  [key: string]: unknown;
};
export type MotionDesignNodeData = {
  prompt: string;
  plannedPrompt: string;
  planner: MotionDesignPlanner;
  effort: "medium" | "high" | "max";
  inputMode: "auto" | "prompt" | "reference";
  settings: {
    duration: number;
    aspectRatio: "16:9" | "4:3" | "1:1" | "3:4" | "9:16" | "21:9";
    resolution: "480p" | "720p";
    generateAudio: boolean;
    seed: number | null;
  };
  sourceMotion: IRObject | null;
  sourceTimeline: IRObject | null;
  sourceVideo: VideoArtifact | null;
  job: SeedanceVideoJob | null;
  video: VideoArtifact | null;
};

/* `png` is the legacy asset field: a PNG/JPEG data URL or desktop blob URL. */
export type ImageStyle = "vector" | "texture" | "icon";
export type ImageVariant = { png: string; svg?: string; width: number; height: number; createdAt: number; format?: "png" | "jpeg"; transparent?: boolean; mask?: string; edge?: string; method?: 'chroma'; keyColor?: string };
export type ImageNodeData = {
  engine: "raster" | "svg";
  model?: string;
  rasterModel?: string;
  outputFormat: "png" | "jpeg";
  prompt: string;
  style: ImageStyle;
  width: number;
  height: number;
  tileable: boolean;
  provider: NodeProvider;
  effort: string;
  variants: ImageVariant[];
  active: number;
};

export type RemoveBackgroundNodeData = {
  method?: 'ai' | 'chroma';
  keyColor?: string;
  tolerance?: number;
  softness?: number;
  despill?: boolean;
  image: string | null;
  fileName: string;
  prompt: string;
  variants: ImageVariant[];
  active: number;
};

export type AnyNodeData =
  | PromptNodeData
  | ReferenceNodeData
  | GeneratorNodeData
  | EditNodeData
  | MixNodeData
  | PageNodeData
  | SourceImportNodeData
  | DesignUiNodeData
  | DeriveNodeData
  | ReskinNodeData
  | QualityPassNodeData
  | RecorderNodeData
  | MotionNodeData
  | MotionDesignNodeData
  | TimelineNodeData
  | PageBridgeNodeData
  | DesignSystemNodeData
  | ImageNodeData
  | RemoveBackgroundNodeData;

export type PromptFlowNode = Node<PromptNodeData, "prompt">;
export type ReferenceFlowNode = Node<ReferenceNodeData, "reference">;
export type GeneratorFlowNode = Node<GeneratorNodeData, "generator">;
export type EditFlowNode = Node<EditNodeData, "edit">;
export type MixFlowNode = Node<MixNodeData, "mix">;
export type PageFlowNode = Node<PageNodeData, "page">;
export type SourceImportFlowNode = Node<SourceImportNodeData, "sourceimport">;
export type DesignUiFlowNode = Node<DesignUiNodeData, "designui">;
export type DeriveFlowNode = Node<DeriveNodeData, "derive">;
export type ReskinFlowNode = Node<ReskinNodeData, "reskin">;
export type QualityPassFlowNode = Node<QualityPassNodeData, "qualitypass">;
export type RecorderFlowNode = Node<RecorderNodeData, "recorder">;
export type MotionFlowNode = Node<MotionNodeData, "motion">;
export type MotionDesignFlowNode = Node<MotionDesignNodeData, "motiondesign">;
export type TimelineFlowNode = Node<TimelineNodeData, "timeline">;
export type PageBridgeFlowNode = Node<PageBridgeNodeData, "pagebridge">;
export type DesignSystemFlowNode = Node<DesignSystemNodeData, "designsystem">;

export type ImageFlowNode = Node<ImageNodeData, "image">;
export type RemoveBackgroundFlowNode = Node<RemoveBackgroundNodeData, "removebackground">;

export type FlowNode =
  | PromptFlowNode
  | ReferenceFlowNode
  | GeneratorFlowNode
  | EditFlowNode
  | MixFlowNode
  | PageFlowNode
  | SourceImportFlowNode
  | DesignUiFlowNode
  | DeriveFlowNode
  | ReskinFlowNode
  | QualityPassFlowNode
  | RecorderFlowNode
  | MotionFlowNode
  | MotionDesignFlowNode
  | TimelineFlowNode
  | PageBridgeFlowNode
  | DesignSystemFlowNode
  | ImageFlowNode
  | RemoveBackgroundFlowNode;

/* Ребро RF: id строится по формату из спеки — e<from.node>:<from.port>-<to.node>:<to.port> */
export type FlowEdge = Edge;

/* Legacy-формат designai-graph-v1: id числовые, рёбра с вложенными from/to.
 * Конвертация в типы RF (строковые id) — только в рантайме. */
export type LegacyView = { x: number; y: number; zoom: number };
export type LegacyEdgeEndpoint = { node: number; port: string };
export type LegacyNodePayload = {
  id: number;
  type: NodeType;
  x: number;
  y: number;
  data: AnyNodeData;
};
export type LegacyEdgePayload = {
  from: LegacyEdgeEndpoint;
  to: LegacyEdgeEndpoint;
};
export type LegacyGraphPayload = {
  nodes: LegacyNodePayload[];
  edges: LegacyEdgePayload[];
  view: LegacyView;
  nextId?: number;
};

export type FlowPage = {
  id: string;
  name: string;
  nodes: FlowNode[];
  edges: FlowEdge[];
  view: LegacyView;
  nextId: number;
};
