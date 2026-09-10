import { componentMasterPreview, selectedComponentMaster } from "../engine/componentMaster";
import { PAGE_INPUT_LIMIT, PAGE_INPUT_NAMES } from "./types";
import { createStore } from "zustand/vanilla";

import { api, apiGet } from "./api";
import { imageDataUrl, isImageSource } from "./image-assets";
import { flushNodeText, flushAllNodeText } from "./textcommit";
import type {
  BlockParseJobResp,
  BlockParseResp,
  GenerateResp,
  MixResp,
  ReproduceResp,
  ReskinResp,
  QualityPassResp,
} from "./api";
import { NODE_DEFS, defaultData, portsOfNode } from "./ports";
import { deepClone, outValue, pullInput, reachable } from "./dataflow";
import { generatorInputKey } from "./generator-inputs";
import { inputFingerprint } from "./fingerprint";
import { runDesktopAiQueue } from "./desktop-ai-queue";
import { videoHistoryPatch, videoSourceCheckpoint } from "./video-history";
import { videoPages } from "./video-inputs";
import type { VideoRevisionChange } from "./types";
import { composeSourceInputs, sourceInputForPort } from "./sourceComposition";
import type { SourceInputBlock } from "./sourceComposition";
import {
  DEFAULT_VIEW,
  FLOW_LS_KEY,
  buildPagesProjectPayload,
  compactLegacyLocalStorage,
  loadPagesProjectFromDb,
  loadPagesProjectFromStorage,
  loadFromStorage,
  makeRfEdge,
  payloadToRf,
  scheduleProjectSave,
} from "./serialize";
import { toast } from "./toast";
import { fitFlowView, focusFlowNode } from "./graphdev";
import { offloadSourceEvidenceInPlace } from "../desktop/blobStore";
import type {
  AnyNodeData,
  FlowPage,
  FlowEdge,
  FlowNode,
  GeneratorNodeData,
  ImageNodeData,
  ImageVariant,
  RemoveBackgroundNodeData,
  IRObject,
  LegacyEdgeEndpoint,
  LegacyGraphPayload,
  LegacyView,
  MixNodeData,
  PageNodeData,
  NodeProvider,
  NodeType,
  ReskinNodeData,
  DesignSystemNodeData,
  DesignSystemAiOperation,
  AiPipelineStage,
  SourceImportNodeData,
  DeriveNodeData,
  EditNodeData,
  QualityPassNodeData,
  PageBridgeNodeData,
  RecorderNodeData,
  InteractionLiveAction,
  MotionNodeData,
  MotionDesignNodeData,
  SeedanceVideoJob,
  SourceArtifact,
  TimelineNodeData,
  VideoArtifact,
} from "./types";

function friendlyProviderError(error: unknown) {
  const raw = error instanceof Error ? error.message : String(error);
  const detail = raw.replace(/^Error invoking remote method '[^']+':\s*Error:\s*/i, "").trim();
  if (/OpenAI API key|Codex не подключён|Claude не подключён|Codex CLI|Claude Code|нет подключённого AI-аккаунта|Agents\s*→\s*Connections/i.test(detail)) {
    return "AI-аккаунт не подключён. Откройте Agents → Connections.";
  }
  return detail || "AI не ответил. Повторите запуск.";
}

/* Провайдер ноды: поддерживаемый выбор проходит как есть, ретро-значения из
 * старых проектов мигрируют на Sol (тот же контракт, что в serialize.ts и
 * desktop/services/provider-router.mjs). */
const NODE_PROVIDERS = new Set<NodeProvider>(["openai", "astra", "codex", "claude"]);
function nodeProvider(value: unknown): NodeProvider {
  return NODE_PROVIDERS.has(value as NodeProvider) ? (value as NodeProvider) : "openai";
}
const PROVIDER_LABELS: Record<NodeProvider, string> = {
  openai: "GPT-5.6 Sol",
  astra: "GPT-6 Astra",
  codex: "Codex",
  claude: "Claude Opus",
};

// Canvas-only selection/viewport changes do not change the captured kit.
function sourceKitFingerprint(data: SourceImportNodeData): string {
  return inputFingerprint({
    url: data.importedUrl || data.url,
    blocks: data.blocks.map(({ lit, cached, ...block }) => block),
    tokens: data.tokens,
    artifact: data.sourceArtifact,
  });
}

function connectedDesignSystemSource(nodes: FlowNode[], edges: FlowEdge[], target: FlowNode) {
  const edge = edges.find((e) => e.target === target.id && e.targetHandle === "artifact");
  const source = nodes.find((n) => n.id === edge?.source);
  return source?.type === "sourceimport" ? source : null;
}

export function resolveDesignSystemAiProvider(nodes: FlowNode[], edges: FlowEdge[], target: FlowNode): NodeProvider {
  const selection = (target.data as DesignSystemNodeData).aiProvider;
  if (selection && selection !== "inherit") return nodeProvider(selection);
  return nodeProvider(connectedDesignSystemSource(nodes, edges, target)?.data.aiProvider);
}

type DesktopDsPreparation = {
  prepareId: string;
  documentHash: string;
  operation: DesignSystemAiOperation;
  provider: NodeProvider;
  reasoningEffort: NodeEffort;
  stage: string;
  tasks: Array<{ id: string; status: "ready" | "unsupported"; reason?: string | null; componentKey?: string; viewport?: string;
    messages: Parameters<NonNullable<Window["designDNA"]>["providers"]["chatRequest"]>[0]["messages"] }>;
};
export type DesignSystemAiResult = {
  document: Record<string, unknown>;
  summary?: Record<string, unknown>;
  results?: Array<Record<string, any>>;
  reviewed?: number;
  approved?: number;
  complete?: boolean;
  nextPreparation?: DesktopDsPreparation | null;
  error?: string;
};

/** Shared panel/QA action. The provider, document and artifact wire are captured
 * once. No delayed answer may apply to a replaced node, document or Source. */
export async function runDesktopDesignSystemAi(
  nodeId: number,
  operation: DesignSystemAiOperation,
  options: { viewport?: string; repair?: boolean; beforeCommit?: () => void } = {},
): Promise<DesignSystemAiResult | null> {
  const get = useFlowStore.getState;
  const initial = get();
  const node = initial.nodes.find((n) => Number(n.id) === nodeId);
  if (!node || node.type !== "designsystem" || initial.busy[nodeId] || node.data.busyAction) return null;
  if (!["organize", "style-review", "master-review"].includes(operation)) throw new Error("Unknown DS AI operation");
  if (!node.data.document?.id && !node.data.systemId) return null;
  const provider = resolveDesignSystemAiProvider(initial.nodes, initial.edges, node);
  const effort = nodeEffort(node.data.aiEffort || "high");
  const systemId = node.data.systemId;
  const revision = node.data.revision;
  let originalDocument = node.data.document || {};
  const documentFingerprint = inputFingerprint(node.data.document ?? null);
  const source = connectedDesignSystemSource(initial.nodes, initial.edges, node);
  const sourceFingerprint = source ? sourceKitFingerprint(source.data) : null;
  const pageId = initial.activePageId;
  const signal = beginRunAbort(nodeId);
  const runToken = newRunId();
  const activeChatIds = new Set<string>();
  const cancelledChatIds = new Set<string>();
  const startedAt = Date.now();
  const timings = { elapsedMs: 0, prepareMs: 0, providerMs: 0, applyMs: 0, requests: 0, retries: 0 };
  let workingDocument = deepClone(originalDocument);
  let acceptedSummary: DesignSystemAiResult["summary"];
  let hasAcceptedStage = false;
  const ownsRun = () => runAborts.get(nodeId)?.signal === signal && get().activePageId === pageId
    && get().nodes.some((n) => Number(n.id) === nodeId && n.type === "designsystem" && n.data._dsAiRun === runToken);
  const guard = (allowCancelled = false) => {
    if ((!allowCancelled && signal.aborted) || !ownsRun()) throw new DOMException("DS AI run cancelled", "AbortError");
    const current = get().nodes.find((n) => Number(n.id) === nodeId)!;
    const currentSource = connectedDesignSystemSource(get().nodes, get().edges, current);
    if (inputFingerprint((current.data as DesignSystemNodeData).document ?? null) !== documentFingerprint
      || (current.data as DesignSystemNodeData).systemId !== systemId
      || (current.data as DesignSystemNodeData).revision !== revision
      || currentSource?.id !== source?.id
      || (currentSource ? sourceKitFingerprint(currentSource.data) : null) !== sourceFingerprint) {
      throw new DOMException("Source или документ изменился — повторите AI-операцию", "AbortError");
    }
  };
  const stage = (status: AiPipelineStage["status"], message: string) => {
    if (!ownsRun()) return;
    const current = get().nodes.find((n) => Number(n.id) === nodeId)!.data as DesignSystemNodeData;
    get().setNodeData(nodeId, { pipelineStatus: { ...current.pipelineStatus,
      [operation]: { status, message, provider, updatedAt: new Date().toISOString(),
        timings: { ...timings, elapsedMs: Date.now() - startedAt } } } });
    get().setStatus(nodeId, message, status === "success" ? "ok" : status === "running" ? undefined : "err");
  };
  const cancelChat = () => {
    for (const chatId of activeChatIds) {
      if (cancelledChatIds.has(chatId)) continue;
      cancelledChatIds.add(chatId);
      void window.designDNA?.providers.cancel?.(chatId).catch(() => undefined);
    }
  };
  signal.addEventListener("abort", cancelChat);
  get().setNodeData(nodeId, { _dsAiRun: runToken, _dsAiRetryable: false, busyAction: operation, lastError: "" });
  get().setBusy(nodeId, true);
  stage("running", `${PROVIDER_LABELS[provider]} · ${operation}: подготовка…`);
  const request = async <T>(path: string, body: unknown): Promise<T> => {
    const requestStarted = Date.now();
    try {
      const response = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body), signal });
      const payload = await response.json();
      if (!response.ok || payload.error) {
        const detail = payload.detail || payload.error;
        if (detail && typeof detail === "object") {
          const first = Array.isArray(detail.errors) ? detail.errors[0] : null;
          throw Object.assign(new Error([detail.message || detail.code || `HTTP ${response.status}`,
            first?.message, first?.path, detail.errors?.length > 1 ? `Ошибок: ${detail.errors.length}` : ""].filter(Boolean).join(" · ")),
            { httpStatus: response.status, detail });
        }
        throw new Error(String(detail || `HTTP ${response.status}`));
      }
      return payload as T;
    } finally {
      if (path.endsWith('/prepare')) timings.prepareMs += Date.now() - requestStarted;
      if (path.endsWith('/apply')) timings.applyMs += Date.now() - requestStarted;
    }
  };
  try {
    if (!originalDocument.id) {
      guard();
      const loaded = await request<{ document?: Record<string, unknown>; error?: string }>("/api/design-system/get", {
        systemId: node.data.systemId, revision: Number(node.data.revision) || 0,
      });
      guard();
      if (!loaded.document || loaded.document.id !== node.data.systemId) throw new Error(loaded.error || "Документ Design System недоступен");
      originalDocument = loaded.document;
      workingDocument = deepClone(loaded.document);
    }
    if (operation === "master-review") {
      const assets = (originalDocument.referenceAssets || {}) as Record<string, { referencePreviews?: Record<string, unknown> }>;
      const missing = Object.values(originalDocument.reviewComponents || {}).filter((component: any) =>
        component?.sourceRef?.evidenceKey && !Object.values(assets[component.sourceRef.evidenceKey]?.referencePreviews || {}).some(Boolean));
      if (missing.length) throw new Error(`Нет исходных снимков Source для ${missing.length} мастеров. Обновите Source Import и выполните синхронизацию UI Kit; повтор AI-ревью без снимков не поможет.`);
    }
    let result: DesignSystemAiResult;
    const warnings: string[] = [];
    const verdicts = new Map<string, Record<string, any>>();
    const collectResults = (items: DesignSystemAiResult["results"]) => {
      for (const item of items || []) {
        if (item.key && (item.kind === "master-review" || item.kind === "master-verify" || item.approved !== undefined)) verdicts.set(String(item.key), item);
        else if (item.error || item.rejected?.length) warnings.push(String(item.error || item.rejected.join("; ")));
      }
    };
    if (window.designDNA?.providers?.chatRequest || provider === "codex" || provider === "claude") {
      const desktop = window.designDNA;
      if (!desktop?.providers?.chatRequest) throw new Error(`${PROVIDER_LABELS[provider]}: требуется подключённый desktop-аккаунт`);
      guard();
      let preparation = await request<DesktopDsPreparation>("/api/design-system/desktop-ai/prepare", {
        document: workingDocument, operation, provider, reasoningEffort: effort, repair: options.repair ?? true,
      });
      const seen = new Set<string>();
      for (;;) {
        guard();
        if (!preparation.prepareId || !preparation.documentHash || !Array.isArray(preparation.tasks)
          || preparation.provider !== provider || preparation.operation !== operation
          || seen.has(preparation.prepareId) || seen.size >= 4) throw new Error("Некорректный desktop AI contract");
        seen.add(preparation.prepareId);
        stage("running", `${PROVIDER_LABELS[provider]} · ${preparation.stage}…`);
        const outputs = new Map<string, string>();
        let completed = 0;
        const parallel = preparation.stage.startsWith("master-") ? 2 : 1;
        const runTask = async (task: DesktopDsPreparation["tasks"][number], taskIndex: number, correction?: string) => {
          guard();
          stage("running", `${PROVIDER_LABELS[provider]} · ${preparation.stage}: готово ${completed}/${preparation.tasks.length} · ${correction ? "исправление формата 1/1" : [task.componentKey || `проверка ${taskIndex + 1}`, task.viewport].filter(Boolean).join(" / ")}…`);
          if (task.status === "unsupported") {
            warnings.push(`${task.componentKey || task.id}${task.viewport ? ` (${task.viewport})` : ""}: ${task.reason || "Нет исходного снимка для проверки"}`);
            completed++; return;
          }
          if (task.status !== "ready" || !task.messages?.length) throw new Error("Некорректная AI-задача");
          const chatId = `${runToken}:${task.id}${correction ? ":format-correction" : ""}`;
          activeChatIds.add(chatId);
          const profile = preparation.stage === "master-repair" ? "quality_repair"
            : preparation.stage === "master-review" || preparation.stage === "master-verify" ? "quality_judge" : "editor";
          // The subscription transport supports a real output schema; prompts alone
          // let judges invent verdict/issue keys and non-contract severity values.
          // Claude Code carries it as --json-schema (structured_output); an older
          // CLI reports the schema as dropped and the prompt still requests JSON.
          const responseFormat = profile === "quality_judge" ? {
            type: "json_schema" as const,
            jsonSchema: { name: "design_system_verdict", schema: {
              type: "object", additionalProperties: false,
              required: ["approved", "score", "summary", "defects"],
              properties: {
                approved: { type: "boolean" }, score: { type: "number", minimum: 0, maximum: 100 },
                summary: { type: "string", minLength: 1 },
                defects: { type: "array", maxItems: 12, items: {
                  type: "object", additionalProperties: false, required: ["severity", "what", "where"],
                  properties: { severity: { type: "string", enum: ["minor", "major", "critical"] },
                    what: { type: "string", minLength: 1 }, where: { type: "string" } },
                } },
              },
            } },
          } : undefined;
          try {
            const messages = correction ? [...task.messages,
              { role: "assistant" as const, content: outputs.get(task.id)! },
              { role: "user" as const, content: `The server rejected your previous response format: ${correction}\nReturn the complete corrected JSON object only, matching the original task schema. Preserve the intended answer. No markdown or explanation. This is the only format-correction attempt.` }] : task.messages;
            const chat = async () => {
              for (let attempt = 0; attempt < 2; attempt++) {
                guard();
                const attemptId = attempt ? `${chatId}:retry-${attempt}` : chatId;
                activeChatIds.add(attemptId);
                const chatStarted = Date.now();
                timings.requests++;
                try {
                  return await desktop.providers.chatRequest({ ...chatRoute(provider, effort), id: attemptId, profile, messages,
                    ...(responseFormat ? { responseFormat } : {}),
                    timeoutMs: profile === "quality_repair" ? 360_000 : 180_000 });
                } catch (error) {
                  guard(); // Cancellation or changed Source must never restart a request.
                  const message = error instanceof Error ? error.message : String(error);
                  // A full model deadline already consumed its budget. Repeating
                  // it silently doubles the wait; retry only transport failures.
                  if (attempt || !/ECONNRESET|ETIMEDOUT|\b429\b|\b50[234]\b/i.test(message)) throw error;
                  timings.retries++;
                  stage("running", `${PROVIDER_LABELS[provider]} · повтор временно прерванного запроса…`);
                } finally { timings.providerMs += Date.now() - chatStarted; activeChatIds.delete(attemptId); }
              }
              throw new Error("AI-запрос не завершён");
            };
            const answer = await chat();
            guard();
            // GPT subscriptions intentionally use Codex with the selected model.
            const answeredProvider = answer.transport?.requestedProvider || answer.provider;
            if (answeredProvider && answeredProvider !== provider
              && !(provider === "astra" && answeredProvider === "openai" && answer.transport?.model === "gpt-6-astra"))
              throw new Error("AI ответил через другой провайдер");
            outputs.set(task.id, answer.content);
            if (!correction) completed++;
            stage("running", `${PROVIDER_LABELS[provider]} · ${preparation.stage}: готово ${completed}/${preparation.tasks.length}…`);
          } finally { activeChatIds.delete(chatId); }
        };
        guard();
        try { await runDesktopAiQueue(preparation.tasks, parallel, runTask); }
        catch (error) { cancelChat(); throw error; }
        // Completion order can differ; the server always receives task order.
        const responses = () => preparation.tasks.filter((task) => task.status === "ready")
          .map((task) => ({ taskId: task.id, output: outputs.get(task.id)! }));
        const apply = () => {
          guard(); // In particular, cancel/stale answers must never reach /apply.
          stage("running", `${PROVIDER_LABELS[provider]} · ${preparation.stage}: серверная проверка ответа и fidelity…`);
          return request<DesignSystemAiResult>("/api/design-system/desktop-ai/apply", {
            prepareId: preparation.prepareId, documentHash: preparation.documentHash, document: workingDocument, responses: responses(),
          });
        };
        const correctedTaskIds = new Set<string>();
        for (;;) {
          try { result = await apply(); break; }
          catch (error) {
            guard();
            const failure = error as { httpStatus?: number; detail?: Record<string, unknown> };
            const detail = failure.detail;
            const taskIndex = preparation.tasks.findIndex((task) => task.id === detail?.taskId && task.status === "ready");
            if (failure.httpStatus !== 422 || detail?.code !== "invalid-ai-output"
              || detail.retryable !== true || detail.stage !== preparation.stage || taskIndex < 0
              || correctedTaskIds.has(preparation.tasks[taskIndex].id)
              || correctedTaskIds.size >= responses().length) throw error;
            correctedTaskIds.add(preparation.tasks[taskIndex].id);
            await runTask(preparation.tasks[taskIndex], taskIndex, String(detail.message || "Invalid JSON output"));
            // Same preparation/hash, complete envelope. Each ready task gets at most one correction.
          }
        }
        guard();
        if (result.error || !result.document) throw new Error(result.error || "AI не вернул документ");
        collectResults(result.results);
        workingDocument = result.document;
        acceptedSummary = result.summary;
        hasAcceptedStage = true;
        if (result.complete === true) break;
        if (!result.nextPreparation) throw new Error("AI завершился без финальной проверки");
        preparation = result.nextPreparation;
      }
    } else {
      guard();
      result = await request<DesignSystemAiResult>(`/api/design-system/${operation}`, {
        document: workingDocument, provider, reasoningEffort: effort, viewport: options.viewport || "desktop",
      });
      guard();
      if (result.error || !result.document) throw new Error(result.error || "AI не вернул документ");
      collectResults(result.results);
    }
    if (operation === "master-review") {
      const keys = new Set([...Object.keys(originalDocument.reviewComponents || {}), ...verdicts.keys()]);
      for (const key of keys) {
        const verdict = verdicts.get(key);
        if (!verdict || verdict.approved !== true || verdict.supported === false || verdict.rejected?.length)
          warnings.push(`${key}: ${verdict?.error || verdict?.rejected?.join("; ") || verdict?.summary || "мастер не одобрен"}`);
      }
      result.results = [...verdicts.values()];
      result.reviewed = verdicts.size;
      result.approved = [...verdicts.values()].filter((item) => item.approved === true && item.supported !== false).length;
    }
    guard();
    options.beforeCommit?.();
    guard(); // beforeCommit is external code; recheck before saving node state.
    get().setNodeData(nodeId, { document: result.document, summary: result.summary, status: "draft", lastError: warnings.join("; ") });
    stage(warnings.length ? "warning" : "success", warnings.length ? `Проверка не завершена: ${warnings.length} замечаний. Подробности в диагностике.` : `${PROVIDER_LABELS[provider]} · ${operation}: завершено`);
    get().propagate(nodeId);
    return result;
  } catch (error) {
    let message = friendlyProviderError(error);
    if (hasAcceptedStage) {
      try {
        // /apply persists each accepted stage. Reflect that server state after a
        // later failure/cancel, but never replace an edited/reconnected/deleted node.
        guard(true);
        get().setNodeData(nodeId, { document: workingDocument, summary: acceptedSummary, status: "draft" });
        message += " · Предыдущий принятый этап сохранён; текущий этап не завершён";
      } catch { /* Stale identity/content must retain the newer local state. */ }
    }
    stage(error instanceof DOMException && error.name === "AbortError" ? "cancelled" : "failed", message);
    if (ownsRun()) get().setNodeData(nodeId, { lastError: message,
      _dsAiRetryable: (error as { detail?: { code?: string; retryable?: boolean } })?.detail?.code === "invalid-ai-output"
        && (error as { detail?: { retryable?: boolean } }).detail?.retryable === true });
    return null;
  } finally {
    signal.removeEventListener("abort", cancelChat);
    if (ownsRun()) { get().setNodeData(nodeId, { busyAction: "", _dsAiRun: null }); get().setBusy(nodeId, false); }
    endRunAbort(nodeId, signal);
  }
}
type NodeEffort = "medium" | "high" | "max";
function nodeEffort(value: unknown): NodeEffort {
  return value === "high" || value === "max" ? value : "medium";
}
/* Codex — text-only контракт без reasoning; модель выбирает сам транспорт. */
function chatRoute(provider: NodeProvider, effort: unknown) {
  if (provider === "codex") return { provider, model: null };
  const reasoning = { effort: nodeEffort(effort) };
  if (provider === "claude") return { provider, model: "opus", reasoning };
  return { provider, model: provider === "astra" ? "gpt-6-astra" : "gpt-5.6-sol", reasoning };
}

async function cancellableChat(request: Parameters<NonNullable<Window["designDNA"]>["providers"]["chatRequest"]>[0], signal?: AbortSignal) {
  if (signal?.aborted) throw new DOMException("Отменено", "AbortError");
  const desktop = window.designDNA!;
  const id = request.id || newRunId();
  const cancel = () => { void desktop.providers.cancel(id).catch(() => undefined); };
  signal?.addEventListener("abort", cancel, { once: true });
  try {
    const result = await desktop.providers.chatRequest({ ...request, id });
    if (signal?.aborted) throw new DOMException("Отменено", "AbortError");
    return result;
  } finally { signal?.removeEventListener("abort", cancel); }
}

/* Quality Pass — судья + починка + пересуд одного IR. Встроен в прогон
 * генератора (отдельная нода снята с палитры создания; легаси-графы с нодой
 * продолжают работать). Web-режим судит сервером; desktop гоняет этапы через
 * подключённый аккаунт ноды с профилями quality_judge/quality_repair. */
async function qualityPassCycle(
  ir: IRObject,
  brief: string,
  provider: NodeProvider,
  effort: "medium" | "high" | "max",
  onStage: (stage: string) => void,
  { minScore = 80, repair = true, signal, runId, designSystem, surface = "auto", visualReview = false }: {
    minScore?: number; repair?: boolean; signal?: AbortSignal; runId?: string;
    designSystem?: Record<string, unknown> | null; surface?: string; visualReview?: boolean;
  } = {},
): Promise<QualityPassResp> {
  const request = { ir, brief, provider, effort, min_score: minScore, repair, rejudge: repair, designSystem, surface, visualReview };
  const desktop = window.designDNA;
  if (!desktop) return api<QualityPassResp>("/api/quality-pass", { ...request, runId }, { signal, runId });
  const outputs: Partial<Record<"judge" | "repair" | "rejudge", string>> = {};
  const seen = new Set<string>();
  for (;;) {
    if (signal?.aborted) throw new DOMException("Отменено", "AbortError");
    const res = await api<QualityPassResp>("/api/quality-pass/codex-step", { ...request, outputs }, { signal });
    if (signal?.aborted) throw new DOMException("Отменено", "AbortError");
    const pending = res.pending;
    if (!pending) return res;
    if (seen.has(pending.stage) || seen.size >= 3) {
      throw new Error("Quality Pass: некорректная последовательность этапов");
    }
    seen.add(pending.stage);
    onStage(pending.stage);
    const answer = await cancellableChat({
      // Усилие судьи наследует ноду: на CLI-провайдерах high — это минуты
      // thinking на каждый вариант, выбор скорости/строгости за пользователем.
      ...chatRoute(provider, effort),
      profile: pending.profile,
      messages: pending.messages,
    }, signal);
    outputs[pending.stage] = answer.content;
  }
}

type GeneratorDirection = {
  id: string;
  label: string;
  motivation: string;
  tradeoff: string;
};

type GeneratorQualityReview = {
  score: number | null;
  passed: boolean | null;
  reasons: string[];
};

type GenerateDirectionResp = GenerateResp & {
  directions?: unknown[];
  artDirections?: unknown[];
  designDirections?: unknown[];
  designBriefs?: unknown[];
  variantDirections?: unknown[];
};

function generatorDirections(response: GenerateDirectionResp): GeneratorDirection[] {
  const raw = response.directions || response.artDirections || response.designDirections || response.designBriefs || [];
  return raw.slice(0, 3).flatMap((item, index) => {
    if (typeof item === "string") {
      const value = item.trim();
      return value ? [{ id: value, label: value, motivation: "", tradeoff: "" }] : [];
    }
    if (!item || typeof item !== "object") return [];
    const value = item as Record<string, any>;
    const tone = typeof value.tone === "object" ? value.tone : {};
    const id = String(value.id || value.key || tone.id || tone.name || value.tone || `direction-${index + 1}`);
    const label = String(value.label || value.name || tone.label || tone.name || value.tone || id);
    const audience = value.audience && typeof value.audience === "object" ? value.audience : {};
    const rhythm = value.rhythm && typeof value.rhythm === "object" ? value.rhythm : {};
    return [{
      id,
      label,
      motivation: String(value.motivation || value.rationale || value.reason || audience.task || ""),
      tradeoff: String(value.tradeoff || value.compromise || rhythm.risk || ""),
    }];
  });
}

function generatorVariantDirections(
  response: GenerateDirectionResp,
  variants: IRObject[],
  directions: GeneratorDirection[],
): string[] {
  const explicit = Array.isArray(response.variantDirections) ? response.variantDirections : [];
  return variants.map((variant, index) => {
    const entry = explicit[index];
    if (typeof entry === "string" && entry.trim()) return entry.trim();
    if (entry && typeof entry === "object") {
      const named = entry as Record<string, unknown>;
      const label = named.label || named.name || named.direction || named.tone;
      if (label) return String(label);
    }
    const meta = ((variant as Record<string, any>).meta || {}) as Record<string, any>;
    const label = meta.directionLabel || meta.designDirectionLabel || meta.designDirection || meta.direction || meta.tone;
    return label ? String(label) : (directions[index]?.label || `Направление ${index + 1}`);
  });
}

const MOTION_DESIGN_TERMINAL = new Set(["completed", "failed", "cancelled", "expired"]);
const motionDesignPollTimers = new Map<number, ReturnType<typeof setTimeout>>();
const MOTION_DESIGN_POLL_MS = 30_000;

/* Поллинг Seedance-джоба: раз в 30 с, но только пока вкладка видима и нода
 * ещё есть на активной странице. Скрытая вкладка — ждём visibilitychange,
 * а не дёргаем провайдера вхолостую; удалённая/чужая нода — таймер снимается. */
function scheduleMotionDesignPoll(id: number, refresh: () => void): void {
  const oldTimer = motionDesignPollTimers.get(id);
  if (oldTimer) clearTimeout(oldTimer);
  const fire = () => {
    motionDesignPollTimers.delete(id);
    const st = useFlowStore.getState();
    if (!st.nodes.some((node) => Number(node.id) === id && node.type === "motiondesign")) return;
    if (typeof document !== "undefined" && document.hidden) {
      const resume = () => {
        document.removeEventListener("visibilitychange", resume);
        if (!document.hidden) fire();
      };
      document.addEventListener("visibilitychange", resume);
      return;
    }
    refresh();
  };
  motionDesignPollTimers.set(id, setTimeout(fire, MOTION_DESIGN_POLL_MS));
}

function motionDesignDigest(motion: IRObject | null, timeline: IRObject | null, video: VideoArtifact | null) {
  const motionScenes = Array.isArray(motion?.scenes) ? motion.scenes.slice(0, 16) : [];
  const timelineLayers = Array.isArray(timeline?.layers) ? timeline.layers.slice(0, 24) : [];
  return {
    video: video ? {
      origin: video.origin,
      filename: video.filename,
      width: video.width,
      height: video.height,
      fps: video.fps,
      duration: video.duration,
      parameters: JSON.stringify(video.parameters || {}).slice(0, 2_000),
    } : null,
    motion: motion ? {
      version: motion.version,
      composition: motion.composition,
      scenes: motionScenes.map((scene) => {
        const item = scene as Record<string, unknown>;
        return {
          id: item.id,
          duration: item.duration,
          transition: item.transition,
          tracks: Array.isArray(item.tracks) ? item.tracks.length : undefined,
        };
      }),
    } : null,
    timeline: timeline ? {
      version: timeline.version,
      composition: timeline.composition,
      layers: timelineLayers.map((layer) => {
        const item = layer as Record<string, unknown>;
        return {
          id: item.id,
          name: item.name,
          type: item.type,
          in: item.in,
          out: item.out,
          keyframes: Array.isArray(item.keyframes) ? item.keyframes.length : undefined,
        };
      }),
    } : null,
  };
}

function directMotionDesignPrompt(brief: string, video: VideoArtifact | null) {
  const clean = brief.trim();
  if (!video) return clean;
  const instruction = [
    "Use the supplied video as the exact visual and motion reference.",
    "Preserve product identity, UI legibility, layout, timing continuity, and original camera direction.",
    "Apply only the requested motion-design change; avoid invented text, warped interfaces, cuts, or style drift.",
  ].join(" ");
  return clean ? `${clean}\n\n${instruction}` : `${instruction} Extend and polish the motion naturally.`;
}

async function videoReferenceUrl(video: VideoArtifact): Promise<string> {
  if (/^https:\/\//i.test(video.downloadUrl)) return video.downloadUrl;
  const response = await fetch(video.downloadUrl);
  if (!response.ok) throw new Error(`Не удалось прочитать готовое видео: HTTP ${response.status}`);
  const blob = await response.blob();
  if (blob.size > 48 * 1024 * 1024) throw new Error("Готовое видео больше лимита reference 48 MiB");
  const bytes = new Uint8Array(await blob.arrayBuffer());
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return `data:${blob.type || video.mime || "video/mp4"};base64,${btoa(binary)}`;
}

/* AI-уточнение разбора Source.
 *
 * Модель видит только компактную сводку структуры (роли, имена, размеры) и
 * список того, чего не решили эвристики, — не весь IR: он весит мегабайты.
 * Ответ жёстко ограничен переименованиями и сменой роли блока; применяет их
 * сервер (blockparse.apply_refinements) с собственной валидацией. */
const REFINE_ROLES = [
  "header", "footer", "carousel", "categories", "product-grid", "services-grid",
  "journal", "how-it-works", "faq", "cta", "trust", "pricing", "testimonials",
  "gallery", "navigation", "status", "toolbar", "profile", "panel", "section",
];

function sourceStructureDigest(response: BlockParseResp) {
  return (response.blocks || []).map((block) => {
    const boundaries: Array<{ sourceKey: string; role: string; label: string }> = [];
    const walk = (node: unknown) => {
      if (!node || typeof node !== "object") return;
      const record = node as Record<string, unknown>;
      const meta = record.sourceMeta as Record<string, unknown> | undefined;
      if (meta?.componentBoundary && boundaries.length < 30) {
        boundaries.push({
          sourceKey: String(record.sourceKey || ""),
          role: String(meta.componentRole || ""),
          label: String(meta.componentLabel || ""),
        });
      }
      for (const child of (record.children as unknown[]) || []) walk(child);
    };
    for (const root of ((block.ir as Record<string, unknown> | undefined)?.tree as unknown[]) || []) walk(root);
    return {
      name: block.name,
      label: block.label,
      kind: block.kind,
      size: block.size,
      components: boundaries,
    };
  });
}

async function refineSourceWithAi(
  response: BlockParseResp,
  provider: NodeProvider,
  setStatus: (id: number, text: string, kind?: "ok" | "err") => void,
  id: number,
  effort: NodeEffort = "high",
  guard: () => void = () => {},
): Promise<BlockParseResp | null> {
  const desktop = window.designDNA;
  if (!desktop) return null;
  setStatus(id, "AI-уточнение структуры…");
  const instruction = [
    "Ты уточняешь результат автоматического разбора веб-страницы на компоненты.",
    "Дай человекочитаемые названия компонентам и уточни роли блоков.",
    `Допустимые роли блока: ${REFINE_ROLES.join(", ")}.`,
    "Ответь СТРОГО одним JSON-объектом вида",
    '{"operations":[{"op":"rename-block","block":"<name>","label":"<текст>"},',
    '{"op":"set-block-role","block":"<name>","role":"<роль>"},',
    '{"op":"rename-component","block":"<name>","sourceKey":"<ключ>","label":"<текст>"}]}',
    "Не добавляй пояснений. Не выдумывай блоки и sourceKey, которых нет во входных данных.",
  ].join(" ");
  const answer = await desktop.providers.chatRequest({
    ...chatRoute(provider, effort),
    messages: [
      { role: "system", content: instruction },
      {
        role: "user",
        content: JSON.stringify({
          structure: sourceStructureDigest(response),
          ambiguities: response.ambiguities || [],
        }),
      },
    ],
  });
  guard();
  const match = String(answer.content || "").match(/\{[\s\S]*\}/);
  if (!match) throw new Error("AI-уточнение: ответ не содержит JSON");
  let operations: unknown;
  try {
    operations = (JSON.parse(match[0]) as { operations?: unknown }).operations;
  } catch {
    throw new Error("AI-уточнение: некорректный JSON");
  }
  if (!Array.isArray(operations) || !operations.length) return null;
  const applied = await api<{ blocks: BlockParseResp["blocks"]; sourceArtifact: unknown; appliedCount: number }>(
    "/api/block-parse/refine", {
      blocks: response.blocks, operations, source: response.sourceArtifact?.source,
    },
  );
  guard();
  if (!applied?.appliedCount) return null;
  setStatus(id, `AI-уточнение: ${applied.appliedCount} правок`);
  return { ...response, blocks: applied.blocks, sourceArtifact: applied.sourceArtifact as never };
}

/* Скриншот → компоненты: агент-сегментатор с детерминированным судьёй.
 *
 * Модель (Claude/GPT — выбор пользователя на ноде) только размечает рамки
 * по тайлам; сервер клампит координаты, отклоняет рамки без пиксельного
 * содержимого, схлопывает повторы и собирает Source-блок, где каждая рамка —
 * boundary-узел с растровым кропом. Ни одна цифра модели не идёт в IR. */
type SegmentTask = { tileIndex: number; messages: import("./api").ApiChatMessage[] };
type SegmentResp = {
  regions: Array<Record<string, unknown>>;
  block?: BlockParseResp["blocks"][number];
  tokens?: Record<string, unknown> | null;
  sourceArtifact?: SourceArtifact;
  rejectedOutputs?: number;
};

async function segmentScreenshotWithAi(
  image: string,
  provider: NodeProvider,
  setStatus: (id: number, text: string, kind?: "ok" | "err") => void,
  id: number,
  effort: NodeEffort = "high",
  guard: () => void = () => {},
): Promise<SegmentResp | null> {
  const desktop = window.designDNA;
  if (!desktop) return null;
  const prepared = await api<{ tasks: SegmentTask[] }>("/api/reproduce/segment", {
    image, prepareOnly: true,
  });
  const tasks = prepared?.tasks || [];
  guard();
  if (!tasks.length) return null;

  const rawOutputs: Array<{ tileIndex: number; content: string }> = [];
  for (const [index, task] of tasks.entries()) {
    guard();
    setStatus(id, `Разметка компонентов: тайл ${index + 1}/${tasks.length}…`);
    const answer = await desktop.providers.chatRequest({
      ...chatRoute(provider, effort),
      messages: task.messages,
    });
    guard();
    rawOutputs.push({ tileIndex: task.tileIndex, content: answer.content });
  }

  setStatus(id, "Проверяю рамки по пикселям…");
  const applied = await api<SegmentResp>("/api/reproduce/segment", { image, rawOutputs });
  guard();
  if (!applied?.block || !(applied.regions || []).length) return null;
  return applied;
}

/* Цикл AI-починки захвата.
 *
 * Судья — тот же fidelity-harness, что решает публикуемость: сервер применяет
 * предложение к КОПИИ IR, перемеряет пиксельное сходство и оставляет правку,
 * только если она реально улучшила картинку. Поэтому неудачная гипотеза
 * модели не может ухудшить результат — худший исход это откат. */
type RepairTask = { blockIndex: number; block?: string; region: Record<string, number>; messages: import("./api").ApiChatMessage[] };
type RepairApplyResp = {
  blocks: BlockParseResp["blocks"];
  totalGain: number;
  gatePassed?: boolean;
  results: Array<{ appliedCount: number; rejectedCount: number; remeasured?: boolean }>;
};

/** Прошёл ли блок fidelity-гейт по последнему отчёту harness. */
function blockGatePassed(block: BlockParseResp["blocks"][number]): boolean {
  return block.fidelityReport?.gate?.passed === true;
}

const REPAIR_MAX_ROUNDS = 3;

async function repairSourceWithAi(
  response: BlockParseResp,
  provider: NodeProvider,
  viewport: string,
  setStatus: (id: number, text: string, kind?: "ok" | "err") => void,
  id: number,
  effort: NodeEffort = "high",
  guard: () => void = () => {},
  onWarning: (message: string) => void = () => {},
): Promise<BlockParseResp | null> {
  const desktop = window.designDNA;
  if (!desktop) return null;
  let current = response;
  let improved = false;
  let totalApplied = 0;
  let totalGain = 0;

  /* Раунды, а не один проход: одна правка открывает следующее расхождение —
   * восстановили свечение, и худшим регионом становится уже другой. Цикл
   * идёт, пока гейт не пройден, правки принимаются и раунды не кончились. */
  for (let round = 1; round <= REPAIR_MAX_ROUNDS; round += 1) {
    guard();
    if ((current.blocks || []).every(blockGatePassed)) break;
    const prepared = await api<{ tasks: RepairTask[] }>("/api/block-parse/repair", {
      blocks: current.blocks, viewport, prepareOnly: true,
    });
    const tasks = prepared?.tasks || [];
    guard();
    if (!tasks.length) break;

    const rawOutputs: Array<{ blockIndex: number; content: string }> = [];
    let providerError: unknown = null;
    for (const [index, task] of tasks.entries()) {
      guard();
      setStatus(id, `AI-починка ${round}/${REPAIR_MAX_ROUNDS}: диагностика ${index + 1}/${tasks.length}…`);
      try {
        const answer = await desktop.providers.chatRequest({
          ...chatRoute(provider, effort),
          messages: task.messages,
        });
        guard();
        rawOutputs.push({ blockIndex: task.blockIndex, content: answer.content });
      } catch (error) {
        guard();
        // Один неудачный диагноз не отменяет остальные. Но если не отвечает
        // сам аккаунт, дальше пойдут те же десятки отказов — выходим сразу.
        providerError = error;
        if (!rawOutputs.length) break;
      }
    }
    if (providerError) onWarning(`AI-починка: ${friendlyProviderError(providerError)}`);
    if (!rawOutputs.length) {
      if (providerError) {
        setStatus(id, `AI-починка пропущена: ${friendlyProviderError(providerError)}`);
      }
      break;
    }

    setStatus(id, `AI-починка ${round}/${REPAIR_MAX_ROUNDS}: перепроверяю сходство…`);
    guard();
    const applied = await api<RepairApplyResp>("/api/block-parse/repair", {
      blocks: current.blocks, viewport, rawOutputs,
    });
    guard();
    const acceptedCount = (applied?.results || []).reduce((sum, r) => sum + (r.appliedCount || 0), 0);
    if (!acceptedCount) {
      // Замер отверг все гипотезы раунда — следующий даст то же самое.
      break;
    }
    // Сервер отвечает только разобранными блоками (ошибочные он отбрасывает),
    // поэтому починенные вживляются по selector, а не заменяют весь список.
    const repaired = new Map((applied.blocks || []).map((block) => [block.selector, block]));
    current = {
      ...current,
      blocks: (current.blocks || []).map((block) => repaired.get(block.selector) || block),
    };
    improved = true;
    totalApplied += acceptedCount;
    totalGain = Math.round((totalGain + (applied.totalGain || 0)) * 100) / 100;
  }

  if (!improved) {
    setStatus(id, "AI-починка: улучшений не найдено — расхождения остаются на ревью");
    return null;
  }
  const left = (current.blocks || []).filter((block) => !blockGatePassed(block)).length;
  setStatus(
    id,
    left
      ? `AI-починка: +${totalGain}% сходства, ${totalApplied} правок · ${left} блок(ов) на ревью`
      : `AI-починка: +${totalGain}% сходства, ${totalApplied} правок · все блоки прошли гейт`,
    left ? undefined : "ok",
  );
  return current;
}

const DESIGN_SYSTEM_SECTION_TYPES = new Set([
  "navbar", "hero", "logo-cloud", "feature-grid", "feature-alternating", "stats", "steps",
  "gallery", "testimonials", "pricing", "comparison", "team", "blog-grid", "faq", "cta",
  "contact-form", "newsletter", "banner", "footer", "composition", "source-block",
]);

function renderableDesignSystemMaster(component: { templateIr?: IRObject; masterIr?: IRObject }): IRObject | null {
  if (!component.masterIr && component.templateIr) return deepClone(component.templateIr);
  const master = component.masterIr;
  const tree = Array.isArray(master?.tree) ? master.tree : [];
  const root = tree[0] as Record<string, any> | undefined;
  if (!master || !root) return null;
  if (DESIGN_SYSTEM_SECTION_TYPES.has(String(root.type || ""))) return deepClone(master);
  return componentMasterPreview(master);
}

/* Статусная строка ноды — runtime-поле, в сейв не попадает (как .n-status в legacy) */
export type NodeStatus = { text: string; kind?: "ok" | "err" };

export type PersistedEditorDraft = {
  baseRevision: number;
  draftRevision: number;
  ir: IRObject;
};

export interface FlowStoreState {
  /* состояние графа в типах RF (id строковые); конвертация в legacy — в serialize.ts */
  nodes: FlowNode[];
  edges: FlowEdge[];
  view: LegacyView;
  nextId: number;
  pages: FlowPage[];
  activePageId: string;
  channels: Record<string, IRObject | null>;
  designSystems: DesignSystemsRegistry;
  designSystemPicker: DesignSystemPickerConfig;
  projectHydrated: boolean;
  statuses: Record<number, NodeStatus>;
  /* run-based ноды в полёте запроса (спиннер на ноде); runtime-поле, в сейв не попадает */
  busy: Record<number, boolean>;
  progresses: Record<number, { startedAt: number; expectedMs: number; label: string; percent?: number; stage?: string }>;
  /* Undo/redo структуры графа (ноды, рёбра, позиции). Снимки держат ссылки на
   * иммутабельные массивы стора — память O(1) на шаг сверх самих изменений.
   * Правки полей нод (setNodeData) в стек не попадают: у инпутов свой undo. */
  graphHistory: GraphHistory;
  /* Журнал статусов ноды за сессию (вкладка «Логи» инспектора); runtime, в сейв не попадает */
  statusLog: Record<number, StatusLogEntry[]>;

  addNode: (
    type: NodeType,
    x: number,
    y: number,
  ) => { id: number; type: NodeType; x: number; y: number; data: AnyNodeData };
  moveNode: (id: number, x: number, y: number) => void;
  moveNodes: (updates: Array<{ id: number; x: number; y: number }>) => void;
  connect: (from: LegacyEdgeEndpoint, to: LegacyEdgeEndpoint) => boolean;
  deleteNode: (id: number) => void;
  deleteEdge: (edgeId: string) => void;
  disconnectNode: (id: number) => number;
  setNodeData: (id: number, patch: Record<string, unknown>) => void;
  getNodeIrRevision: (id: number) => number;
  persistEditorDraft: (id: number, draft: PersistedEditorDraft) => void;
  clearEditorDraft: (id: number) => void;
  commitTimeline: (id: number, expected: IRObject | null, irRevision: number, timeline: IRObject, change?: VideoRevisionChange) => boolean;
  commitEditorDraft: (id: number, expectedRevision: number, ir: IRObject) => boolean;
  setStatus: (id: number, text: string, kind?: "ok" | "err") => void;
  setBusy: (id: number, v: boolean) => void;
  setProgress: (id: number, progress: { expectedMs: number; label: string; percent?: number; stage?: string } | null) => void;
  /* Отмена идущего запроса ноды: в браузере — AbortController у fetch,
   * в десктопе — рестарт long-воркера через designDNA.api.cancel. */
  cancelRun: (id: number) => Promise<void>;
  undoGraph: () => boolean;
  redoGraph: () => boolean;
  propagate: (startId: number, visited?: Set<number>) => void;
  refreshInputs: (id: number, visited?: Set<number>) => void;
  runNode: (id: number) => void;
  runGenerator: (id: number) => Promise<void>;
  runMix: (id: number) => Promise<void>;
  runPage: (id: number) => void;
  refreshEdit: (id: number) => void;
  runSourceImport: (id: number) => Promise<void>;
  runDerive: (id: number) => Promise<void>;
  runReskin: (id: number) => Promise<void>;
  runImage: (id: number) => Promise<void>;
  runQualityPass: (id: number) => Promise<void>;
  runRecorder: (id: number) => Promise<void>;
  runLiveRecorder: (id: number, actions: InteractionLiveAction[]) => Promise<boolean>;
  runMotion: (id: number) => Promise<void>;
  planMotionDesign: (id: number) => Promise<string | null>;
  runMotionDesign: (id: number, confirmedPaid: boolean) => Promise<void>;
  refreshMotionDesign: (id: number) => Promise<void>;
  runTimeline: (id: number) => Promise<void>;
  runPageBridge: (id: number) => void;
  sendToNode: (id: number, targetType: "edit" | "reference") => void;
  addMixInput: (id: number) => void;
  addVideoInput: (id: number) => void;
  removeVideoInput: (id: number, name: string) => void;
  removeMixInput: (id: number, name: string) => void;
  addEditInput: (id: number) => void;
  removeEditInput: (id: number, name: string) => void;
  reorderEditInputs: (id: number, from: number, to: number) => void;
  addPageInput: (id: number) => void;
  removePageInput: (id: number, name: string) => void;
  reorderPageInputs: (id: number, from: number, to: number) => void;
  syncFromCanvas: (nodes: FlowNode[], edges: FlowEdge[], pageId?: string) => void;
  commitNodeDrag: (pageId: string, updates: { id: string; position: { x: number; y: number } }[], selectedIds: string[]) => void;
  loadGraph: (payload: LegacyGraphPayload) => void;
  clearGraph: () => void;
  setView: (v: LegacyView) => void;
  createPage: (name?: string) => void;
  addVideoChainPage: (options?: { url?: string; provider?: string }) => void;
  switchPage: (id: string) => void;
  renamePage: (id: string, name: string) => void;
  deletePage: (id: string) => void;
  loadPersistedProject: () => Promise<void>;
  /* Разрешение конфликта 409 «взять версию из БД»: безусловная замена
   * локального проекта серверным (в отличие от loadPersistedProject без гардов). */
  replaceProjectFromDb: () => Promise<boolean>;
  refreshDesignSystems: () => Promise<void>;
  createDesignSystemFromSource: (sourceId: number, options?: { name?: string }) => Promise<number | null>;
  /* «Загруженная» ДС: JSON-файл (документ DesignDNA / W3C-Tokens Studio / карта токенов) → черновик в этой ноде */
  importDesignSystemDocument: (nodeId: number, payload: unknown, fileName: string) => Promise<boolean>;
  promoteVariantToDesignSystem: (generatorId: number) => Promise<number | null>;
  recordVariantTaste: (generatorId: number, kind: "accepted" | "rejected") => Promise<boolean>;
  setDesignSystemPicker: (patch: Partial<DesignSystemPickerConfig>) => void;
  sendDesignSystemToGenerator: (nodeId: number) => number | null;
  publishDesignSystem: (nodeId: number) => Promise<boolean>;
  setDefaultDesignSystem: (nodeId: number) => Promise<boolean>;
  rebuildDesignSystemFromSource: (nodeId: number) => Promise<boolean>;
  saveDesignSystemDocument: (nodeId: number, document: Record<string, unknown>) => Promise<boolean>;
  runDesktopDesignSystemAi: typeof runDesktopDesignSystemAi;
  finishDesignSystem: (nodeId: number) => Promise<boolean>;
  runDesignSystemAi: (nodeId: number, operation: DesignSystemAiOperation, viewport?: string) => Promise<DesignSystemAiResult | null>;
  restorePublishedDesignSystem: (nodeId: number, ref?: { systemId?: string; revision?: number }) => Promise<boolean>;
  applyDesignSystemToEditor: (nodeId: number, componentKey: string) => { editNodeId: number; previousIr: IRObject | null } | null;
  copyDesignSystemComponentToEditor: (nodeId: number, componentKey: string, pool: "components" | "review" | "suggestions", variant: string) => number | null;
  restoreDesignSystemEditorApply: (editNodeId: number, previousIr: IRObject | null) => void;
}

/* Стартовое состояние — из сейва designai-flow-v1 (битый сейв → пустой граф) */
const emptyGraph = { nodes: [] as FlowNode[], edges: [] as FlowEdge[], view: { ...DEFAULT_VIEW }, nextId: 1 };
// Компактизация legacy-блоба (parse + stringify мегабайт) не нужна для
// первой отрисовки — уводим в idle-слот после boot, а не блокируем FCP.
if (typeof requestIdleCallback === "function") requestIdleCallback(() => compactLegacyLocalStorage(), { timeout: 8_000 });
else setTimeout(compactLegacyLocalStorage, 1_500);
const projectSaved = loadPagesProjectFromStorage();
if (projectSaved) {
  /* pages-проект полностью заменяет legacy-ключ: убираем мёртвый блоб,
   * который иначе занимает мегабайты квоты localStorage. */
  try {
    localStorage.removeItem(FLOW_LS_KEY);
  } catch {
    /* приватный режим и т.п. — не критично */
  }
}
const saved = projectSaved ? null : loadFromStorage();
const initialSingle = saved ? payloadToRf(saved) : emptyGraph;
const initialPages: FlowPage[] = projectSaved?.pages || [
  {
    id: "page-1",
    name: "Page 1",
    ...initialSingle,
  },
];
const initialActivePageId = projectSaved?.activePageId || initialPages[0].id;
const initialActiveGraph = initialPages.find((page) => page.id === initialActivePageId) || initialPages[0];
const initialChannels = projectSaved?.channels || {};
const initialDesignSystems: DesignSystemsRegistry =
  (projectSaved as unknown as { designSystems?: DesignSystemsRegistry } | null)?.designSystems
  || { systems: [], defaultSystemRef: null };

export interface DesignSystemsRegistry {
  systems: Array<Record<string, unknown> & { systemId: string; name: string; status: string; revision: number; contentHash?: string }>;
  defaultSystemRef: { systemId: string; revision: number; contentHash?: string } | null;
}

export interface DesignSystemPickerConfig {
  selection: "inherit" | "none" | string;
  usageMode: "strict" | "extend" | "style-only";
  fixtureProfile: string;
}

const emptyPicker: DesignSystemPickerConfig = {
  selection: "inherit",
  usageMode: "strict",
  fixtureProfile: "typical",
};

export function pinnedDesignSystemRef(
  data: Record<string, unknown>,
  registry: DesignSystemsRegistry,
  picker?: DesignSystemPickerConfig,
): Record<string, unknown> | null {
  const dsSelection = String(data.designSystemSelection || picker?.selection || "inherit");
  if (dsSelection === "none") return null;
  const usageMode = String(data.designSystemUsageMode || picker?.usageMode || "strict");
  const fixture = String(data.designSystemFixture || picker?.fixtureProfile || "typical");
  const target = dsSelection === "inherit" ? registry.defaultSystemRef?.systemId : dsSelection;
  const system = registry.systems?.find((sys) => sys.systemId === target && sys.status === "published");
  if (!system) return null;
  const inheritRef = registry.defaultSystemRef;
  const revision = dsSelection === "inherit" ? (inheritRef?.revision ?? system.revision) : system.revision;
  const contentHash = (dsSelection === "inherit" ? inheritRef?.contentHash : undefined) || system.contentHash || "";
  return {
    systemId: system.systemId,
    revision,
    contentHash,
    usageMode,
    mockFixtureProfile: fixture,
  };
}

async function fetchDesignSystemsList(): Promise<DesignSystemsRegistry> {
  try {
    const resp = await fetch("/api/design-system/list");
    if (!resp.ok) return { systems: [], defaultSystemRef: null };
    const data = await resp.json();
    return { systems: data.systems || [], defaultSystemRef: data.defaultSystemRef || null };
  } catch {
    return { systems: [], defaultSystemRef: null };
  }
}

function pageId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `page-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function currentPageSnapshot(st: {
  nodes: FlowNode[];
  edges: FlowEdge[];
  view: LegacyView;
  nextId: number;
}): Pick<FlowPage, "nodes" | "edges" | "view" | "nextId"> {
  return {
    nodes: st.nodes,
    edges: st.edges,
    view: st.view,
    nextId: st.nextId,
  };
}

function withCurrentPageSaved(st: FlowStoreState): FlowPage[] {
  const snapshot = currentPageSnapshot(st);
  return st.pages.map((page) => (page.id === st.activePageId ? { ...page, ...snapshot } : page));
}

function hydratePageBridgeNodes(nodes: FlowNode[], channels: Record<string, IRObject | null>): FlowNode[] {
  return nodes.map((node) => {
    if (node.type !== "pagebridge" || node.data.mode !== "receive") return node;
    const ir = channels[node.data.channel] || null;
    return { ...node, data: { ...node.data, ir: ir ? deepClone(ir) : null } } as FlowNode;
  });
}

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : null;
}

function uniqueValues(values: unknown[], limit = 12): string[] {
  const out: string[] = [];
  for (const v of values) {
    const s = typeof v === "string" || typeof v === "number" ? String(v).trim() : "";
    if (s && !out.includes(s)) out.push(s);
    if (out.length >= limit) break;
  }
  return out;
}

function extractStyleDna(irRaw: unknown, tokensRaw: unknown): { tokens: Record<string, unknown>; summary: string } {
  const ir = asRecord(irRaw);
  // A tokens wire is an intentional pass-through. For an IR wire the rendered
  // tree is authoritative: ir.tokens may have been inherited from a Header.
  const explicit = asRecord(tokensRaw);
  if (explicit) {
    return { tokens: deepClone(explicit), summary: summarizeStyleDna(explicit) };
  }
  const colors: unknown[] = [];
  const fonts: unknown[] = [];
  const radii: unknown[] = [];
  const spacing: unknown[] = [];
  const walk = (node: unknown) => {
    if (Array.isArray(node)) return node.forEach(walk);
    const r = asRecord(node);
    if (!r) return;
    const style = asRecord(r.style) || {};
    colors.push(style.color, style.background, style.borderColor);
    fonts.push(style.fontFamily);
    radii.push(style.borderRadius, asRecord(r.props)?.radius);
    const frame = asRecord(r.frame);
    spacing.push(frame?.x, frame?.y, frame?.w, frame?.h);
    walk(r.children);
  };
  walk(ir?.tree);
  const tokens: Record<string, unknown> = {
    color: { sampled: uniqueValues(colors) },
    font: { sampled: uniqueValues(fonts, 6) },
    radius: { sampled: uniqueValues(radii, 6) },
    spacing: { measured: uniqueValues(spacing, 10) },
  };
  if (!colors.some((value) => value != null) && !fonts.some((value) => value != null)) {
    const inherited = asRecord(ir?.tokens);
    if (inherited) return { tokens: deepClone(inherited), summary: summarizeStyleDna(inherited) };
  }
  return { tokens, summary: summarizeStyleDna(tokens) };
}

function summarizeStyleDna(tokens: Record<string, unknown>): string {
  const color = asRecord(tokens.color);
  const font = asRecord(tokens.font);
  const radius = asRecord(tokens.radius);
  const spacing = asRecord(tokens.spacing);
  const parts = [
    color ? `colors=${JSON.stringify(color).slice(0, 180)}` : "",
    font ? `fonts=${JSON.stringify(font).slice(0, 140)}` : "",
    radius ? `radius=${JSON.stringify(radius).slice(0, 100)}` : "",
    spacing ? `spacing=${JSON.stringify(spacing).slice(0, 120)}` : "",
  ].filter(Boolean);
  return parts.join("\n");
}

let localDirtySinceInit = false;

/* ---------- undo/redo графа ----------
 * Стек снимков {nodes, edges}: стор обновляет массивы иммутабельно, поэтому
 * снимок — две ссылки, а не копия проекта. Запись — ДО структурной мутации
 * (add/delete/connect/move); правки data нод не пишутся (у полей ввода свой
 * нативный undo, а смешивать их со структурой — терять текст по Ctrl+Z). */
export type GraphSnapshot = { nodes: FlowNode[]; edges: FlowEdge[] };
export type GraphHistory = { past: GraphSnapshot[]; future: GraphSnapshot[] };
export type StatusLogEntry = { at: number; text: string; kind?: "ok" | "err" };
const STATUS_LOG_LIMIT = 30;
const EMPTY_GRAPH_HISTORY: GraphHistory = { past: [], future: [] };
const GRAPH_HISTORY_LIMIT = 50;
let graphHistoryMuted = 0;

function recordGraphHistory(): void {
  if (graphHistoryMuted > 0) return;
  const st = useFlowStore.getState();
  const past = st.graphHistory.past.length >= GRAPH_HISTORY_LIMIT
    ? st.graphHistory.past.slice(1)
    : st.graphHistory.past;
  useFlowStore.setState({
    graphHistory: { past: [...past, { nodes: st.nodes, edges: st.edges }], future: [] },
  });
}

/* Составные операции (удаление с рёбрами, sync канваса) пишут один снимок,
 * внутренние deleteNode/deleteEdge — молчат. */
function withGraphHistoryMuted<T>(fn: () => T): T {
  graphHistoryMuted += 1;
  try {
    return fn();
  } finally {
    graphHistoryMuted -= 1;
  }
}

/* После восстановления снимка данные по восстановленным рёбрам нужно
 * протолкнуть заново (зеркало connect/deleteEdge), иначе downstream-ноды
 * остаются с устаревшим входом. */
function resyncAfterGraphRestore(before: FlowEdge[], after: FlowEdge[]): void {
  const beforeIds = new Set(before.map((edge) => edge.id));
  const afterIds = new Set(after.map((edge) => edge.id));
  withGraphHistoryMuted(() => {
    const st = useFlowStore.getState();
    for (const edge of after) {
      if (!beforeIds.has(edge.id)) st.propagate(Number(edge.source));
    }
    for (const edge of before) {
      if (afterIds.has(edge.id)) continue;
      const target = useFlowStore.getState().nodes.find((node) => node.id === edge.target);
      if (target) st.refreshInputs(Number(target.id));
    }
  });
}

/* AbortController идущих fetch-запросов нод (браузерный режим): отмена
 * обрывает ожидание на клиенте, сервер дорабатывает запрос в фоне. */
const runAborts = new Map<number, AbortController>();
let graphEpoch = 0;
const nodeLifetimes = new Map<number, number>();
function leaveGraph(): void {
  flushAllNodeText();
  graphEpoch += 1;
  for (const controller of runAborts.values()) controller.abort();
  runAborts.clear();
  for (const runId of runIds.values()) void api(`/api/runs/${runId}/cancel`, {}).catch(() => undefined);
  runIds.clear();
}

/** Numeric node IDs are local to a sheet. A task must never write into a new
 * sheet, a replacement graph, or a deleted/recreated node with the same ID. */
export function captureNodeScope(get: () => FlowStoreState, id: number) {
  const initial = get(), epoch = graphEpoch, lifetime = nodeLifetimes.get(id);
  const type = initial.nodes.find(node => Number(node.id) === id)?.type;
  const owns = () => graphEpoch === epoch && nodeLifetimes.get(id) === lifetime
    && get().activePageId === initial.activePageId
    && get().nodes.some(node => Number(node.id) === id && node.type === type);
  let inputCurrent = () => true;
  const check = () => {
    if (!owns()) throw new DOMException("Лист или нода изменились", "AbortError");
    if (!inputCurrent()) throw new DOMException("Входные данные изменились. Запустите ноду заново.", "AbortError");
  };
  return { owns, check, watchInputs(test: () => boolean) { inputCurrent = test; }, async wait<T>(promise: Promise<T>): Promise<T> {
    const value = await promise;
    check();
    return value;
  } };
}



// Compare only request inputs: progress, selection and saved results are not inputs.
// Recheck both the wire identity and its current value at every asynchronous boundary.
function watchNodeInputs(scope: ReturnType<typeof captureNodeScope>, get: () => FlowStoreState, id: number, fields: string[]) {
  const snapshot = () => {
    const state = get(), node = state.nodes.find(item => Number(item.id) === id);
    if (!node) return null;
    return inputFingerprint({
      data: Object.fromEntries(fields.map(key => [key, (node.data as Record<string, unknown>)[key]])),
      designSystem: node.type === "derive" || node.type === "reskin"
        ? pinnedDesignSystemRef(node.data as Record<string, unknown>, state.designSystems, state.designSystemPicker) : null,
      inputs: portsOfNode(node).in.map(port => ({
        port: port.name,
        edges: state.edges.filter(edge => edge.target === node.id && edge.targetHandle === port.name)
          .map(edge => [edge.source, edge.sourceHandle]),
        value: pullInput(state.nodes, state.edges, node, port.name),
      })),
    });
  };
  const initial = snapshot();
  scope.watchInputs(() => snapshot() === initial);
}


function beginRunAbort(id: number): AbortSignal {
  runAborts.get(id)?.abort();
  const controller = new AbortController();
  runAborts.set(id, controller);
  return controller.signal;
}

function endRunAbort(id: number, signal: AbortSignal): void {
  if (runAborts.get(id)?.signal === signal) runAborts.delete(id);
}

/* Для кнопки отмены на ноде: контроллер регистрируется до setBusy(true),
 * поэтому реактивного busy достаточно как триггера перепроверки. */
export function hasRunAbort(id: number): boolean {
  return runAborts.has(id);
}

/* Серверные стадии длинных запусков (app/run_registry.py): web слушает SSE,
 * polling включается только как fallback. Desktop получает собственные IPC-
 * события. Отмена web-запуска кооперативно закрывает LLM stream на дельте. */
const runIds = new Map<number, string>();

function newRunId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `run-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function watchRunStages(id: number, runId: string, expectedMs: number, label: string): () => void {
  runIds.set(id, runId);
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let fallbackTimer: ReturnType<typeof setTimeout> | null = null;
  let source: EventSource | null = null;
  type RunProgress = { status?: string; stageLabel?: string; percent?: number | null; receivedChars?: number };
  const applyRun = (run: RunProgress) => {
    if (runIds.get(id) !== runId || !run || run.status !== "running") return;
    const st = useFlowStore.getState();
    if (!st.busy[id]) return;
    const received = typeof run.receivedChars === "number" ? run.receivedChars : 0;
    const receivedLabel = received >= 1000
      ? `${(received / 1000).toFixed(received >= 10_000 ? 0 : 1)}k`
      : String(received);
    st.setProgress(id, {
      expectedMs,
      label,
      ...(run.stageLabel ? {
        stage: `${run.stageLabel}${received > 0 && run.status === "running" ? ` · получено ${receivedLabel} зн.` : ""}`,
      } : {}),
      ...(typeof run.percent === "number" ? { percent: run.percent } : {}),
    });
  };
  const startPolling = () => {
    if (pollTimer) return;
    pollTimer = setInterval(() => {
    void apiGet<RunProgress>(`/api/runs/${runId}`)
      .then(applyRun)
      .catch(() => undefined);
    }, 900);
  };
  if (!window.designDNA && typeof EventSource !== "undefined") {
    source = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events`);
    source.onmessage = (event) => {
      try {
        const run = JSON.parse(event.data) as RunProgress;
        if (fallbackTimer) { clearTimeout(fallbackTimer); fallbackTimer = null; }
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
        applyRun(run);
        if (run.status && run.status !== "running") source?.close();
      } catch { /* malformed event: fallback watchdog will poll */ }
    };
    source.onerror = startPolling;
    fallbackTimer = setTimeout(startPolling, 2_500);
  } else {
    startPolling();
  }
  return () => {
    source?.close();
    if (pollTimer) clearInterval(pollTimer);
    if (fallbackTimer) clearTimeout(fallbackTimer);
    if (runIds.get(id) === runId) runIds.delete(id);
  };
}

function isAbortError(error: unknown): boolean {
  return !!error && typeof error === "object" && (error as { name?: string }).name === "AbortError";
}

export const useFlowStore = createStore<FlowStoreState>()((set, get) => ({
  designSystems: initialDesignSystems,
  designSystemPicker: emptyPicker,
  // A clean desktop profile has no localStorage snapshot. Until SQLite has
  // answered, the empty canvas must not sync over the canonical project.
  projectHydrated: Boolean(projectSaved),
  nodes: hydratePageBridgeNodes(initialActiveGraph.nodes, initialChannels),
  edges: initialActiveGraph.edges,
  view: initialActiveGraph.view,
  nextId: initialActiveGraph.nextId,
  pages: initialPages,
  activePageId: initialActivePageId,
  channels: initialChannels,
  statuses: {},
  busy: {},
  /* Прогресс длинных операций (импорт/генерация): асимптотическая кривая в
   * UI, реальное завершение снимает прогресс и пишет итоговое время в статус */
  progresses: {},
  graphHistory: EMPTY_GRAPH_HISTORY,
  statusLog: {},

  /* Зеркало addNode (nodes.js:256-264): id из nextId, координаты Math.round */
  addNode: (type, x, y) => {
    const id = get().nextId;
    const rx = Math.round(x);
    const ry = Math.round(y);
    const data = defaultData(type);
    const node = {
      id: String(id),
      type,
      position: { x: rx, y: ry },
      // Svelte Flow keeps a custom node hidden until it has initial dimensions.
      // ResizeObserver replaces these bootstrap values with the real rendered size.
      initialWidth: 260,
      initialHeight: 120,
      data,
    } as FlowNode;
    recordGraphHistory();
    set({ nodes: [...get().nodes, node], nextId: id + 1 });
    return { id, type, x: rx, y: ry, data: node.data };
  },

  /* Позиция ноды в мировых px (legacy Math.round на dragend, nodes.js:336-337) */
  moveNode: (id, x, y) => {
    get().moveNodes([{ id, x, y }]);
  },

  /* Multi-select drag is one user action: publish one array and wake autosave once. */
  moveNodes: (updates) => {
    const positions = new Map(
      updates.map(({ id, x, y }) => [String(id), { x: Math.round(x), y: Math.round(y) }]),
    );
    const current = get().nodes;
    const moved = current.some((node) => {
      const position = positions.get(node.id);
      return !!position && (position.x !== node.position.x || position.y !== node.position.y);
    });
    if (!moved) return; // dragstop без смещения: ни снимка в историю, ни автосейва
    recordGraphHistory();
    set({
      nodes: current.map((node) => {
        const position = positions.get(node.id);
        return position ? { ...node, position } : node;
      }),
    });
  },

  // A drag owns geometry and selection, never the graph snapshot. Async node
  // creation, deletion, connections and generation results may finish mid-drag.
  commitNodeDrag: (pageId, updates, selectedIds) => {
    const state = get();
    if (state.activePageId !== pageId) return;
    const positions = new Map(updates
      .filter(({ position }) => Number.isFinite(position.x) && Number.isFinite(position.y))
      .map(({ id, position }) => [id, { x: Math.round(position.x), y: Math.round(position.y) }]));
    const selected = new Set(selectedIds);
    let moved = false;
    let changed = false;
    const nodes = state.nodes.map((node) => {
      const position = positions.get(node.id) ?? node.position;
      const positionChanged = position.x !== node.position.x || position.y !== node.position.y;
      moved ||= positionChanged;
      if (!positionChanged && Boolean(node.selected) === selected.has(node.id) && !node.dragging) return node;
      changed = true;
      return { ...node, position, selected: selected.has(node.id), dragging: false };
    });
    if (moved) recordGraphHistory();
    if (changed) set({ nodes });
  },

  /* Правила проводов — зеркало connect() (nodes.js:1049-1070), см. docs/ARCHITECTURE.md */
  connect: (from, to) => {
    const state = get();
    const fromNode = Number(from.node);
    const toNode = Number(to.node);
    const src = state.nodes.find((n) => Number(n.id) === fromNode);
    const dst = state.nodes.find((n) => Number(n.id) === toNode);
    // правило 1: ноды существуют и это разные ноды (самосоединение молча отклоняется)
    if (!src || !dst || src.id === dst.id) return false;
    const outP = portsOfNode(src).out.find((p) => p.name === from.port);
    const inP = portsOfNode(dst).in.find((p) => p.name === to.port);
    // правило 2: оба порта объявлены
    if (!outP || !inP) return false;
    // правило 3: kind выхода входит в набор kind входа
    if (!(inP.kinds || [inP.kind]).includes(outP.kind)) {
      toast(`Несовместимые порты: ${outP.kind} → ${inP.kind}`, "error");
      return false;
    }
    // правило 4: проверка циклов — DFS, путь to -> from уже существует?
    if (reachable(toNode, fromNode, state.edges)) {
      toast("Нельзя: соединение создаёт цикл", "error");
      return false;
    }
    // правило 5: один провод на вход — существующее ребро в тот же вход заменяется
    const sidTarget = String(toNode);
    const nextEdges = [
      ...state.edges.filter((e) => !(e.target === sidTarget && e.targetHandle === to.port)),
      makeRfEdge(state.nodes, { node: fromNode, port: from.port }, { node: toNode, port: to.port }),
    ];
    recordGraphHistory();
    set({ edges: nextEdges });
    // зеркало nodes.js:1067: propagate от источника
    get().propagate(fromNode);
    return true;
  },

  /* Зеркало removeNode (nodes.js:298-311): вместе с нодой снимаются её рёбра.
   * Без подтверждения: удаление обратимо через undoGraph, тост даёт «Вернуть». */
  deleteNode: (id) => {
    flushAllNodeText();
    nodeLifetimes.set(id, (nodeLifetimes.get(id) || 0) + 1);
    runAborts.get(id)?.abort();
    const sid = String(id);
    if (!get().nodes.some((node) => node.id === sid)) return;
    const targets = [...new Set(get().edges.filter((edge) => edge.source === sid).map((edge) => Number(edge.target)))];
    recordGraphHistory();
    if (graphHistoryMuted === 0) {
      toast("Нода удалена · Ctrl+Z вернёт", "info", {
        key: "graph-delete",
        action: { label: "Вернуть", run: () => void get().undoGraph() },
      });
    }
    set((state) => {
      const statuses = { ...state.statuses };
      delete statuses[id];
      const busy = { ...state.busy };
      delete busy[id];
      return {
        nodes: state.nodes.filter((n) => n.id !== sid),
        edges: state.edges.filter((e) => e.source !== sid && e.target !== sid),
        statuses,
        busy,
      };
    });
    for (const target of targets) get().refreshInputs(target);
  },

  deleteEdge: (edgeId) => {
    const removed = get().edges.find((edge) => edge.id === edgeId);
    if (!removed) return;
    recordGraphHistory();
    set({ edges: get().edges.filter((edge) => edge.id !== edgeId) });
    const target = get().nodes.find((node) => node.id === removed.target);
    if (target) get().refreshInputs(Number(target.id));
  },

  disconnectNode: (id) => {
    const sid = String(id);
    const connected = get().edges.filter((edge) => edge.source === sid || edge.target === sid);
    if (!connected.length) return 0;
    recordGraphHistory(); // один шаг undo на все рёбра ноды
    withGraphHistoryMuted(() => {
      for (const edge of connected) get().deleteEdge(edge.id);
    });
    get().setStatus(id, `Разорвано связей: ${connected.length}`, "ok");
    return connected.length;
  },

  /* Точечное обновление data ноды (аналог записи n.data.* в legacy + save()) */
  setNodeData: (id, patch) => {
    const sid = String(id);
    const before = get().nodes.find((n) => n.id === sid);
    if (!before) return;
    // No-op патч не будит стор: каждый set пересоздаёт массив nodes и будит
    // все подписки (автосейв-компаратор, канвас), а поля ввода шлют setNodeData
    // на каждое нажатие. Запись ir всегда считается изменением (бампается
    // _irRevision), равенство остальных ключей — по ссылке.
    const beforeData = before.data as Record<string, unknown>;
    const isNoop = !Object.prototype.hasOwnProperty.call(patch, "ir")
      && Object.keys(patch).every((key) => beforeData[key] === (patch as Record<string, unknown>)[key]);
    if (isNoop) return;
    const invalidatesVideo = (before.type === "motion" || before.type === "timeline")
      && ["ir", "interaction", "motion", "timeline", "layers", "composition", "settings", "sceneSettings", "renderSettings"]
        .some((key) => Object.prototype.hasOwnProperty.call(patch, key))
      && !Object.prototype.hasOwnProperty.call(patch, "renderJob");
    set((state) => ({
      nodes: state.nodes.map((n) =>
        n.id === sid ? (() => {
          const nextPatch = { ...patch } as Record<string, unknown>;
          if (invalidatesVideo) nextPatch.renderJob = null;
          if (Object.prototype.hasOwnProperty.call(nextPatch, "ir")) {
            const currentRevision = Number((n.data as Record<string, unknown>)._irRevision) || 0;
            nextPatch._irRevision = currentRevision + 1;
          }
          return ({ ...n, data: { ...n.data, ...nextPatch } }) as FlowNode;
        })() : n,
      ),
    }));
    const previousJob = beforeData.renderJob as { status?: string } | undefined;
    const explicitJob = (patch as Record<string, unknown>).renderJob as { status?: string } | null | undefined;
    if (previousJob?.status === "complete" && (invalidatesVideo
      || (Object.prototype.hasOwnProperty.call(patch, "renderJob") && explicitJob?.status !== "complete"))) get().propagate(id);
  },

  getNodeIrRevision: (id) => {
    const node = get().nodes.find((item) => Number(item.id) === id);
    return node ? Number((node.data as Record<string, unknown>)._irRevision) || 0 : -1;
  },

  persistEditorDraft: (id, draft) => {
    const sid = String(id);
    const persisted = deepClone(draft);
    set((state) => ({
      nodes: state.nodes.map((node) =>
        node.id === sid
          ? ({ ...node, data: { ...node.data, _editorDraft: persisted } } as unknown as FlowNode)
          : node,
      ),
    }));
  },

  clearEditorDraft: (id) => {
    const sid = String(id);
    set((state) => ({
      nodes: state.nodes.map((node) => {
        if (node.id !== sid) return node;
        const data = { ...node.data } as Record<string, unknown>;
        delete data._editorDraft;
        return { ...node, data } as FlowNode;
      }),
    }));
  },

  commitTimeline: (id, expected, irRevision, timeline, change) => {
    const node = get().nodes.find((item) => Number(item.id) === id);
    if (!node || node.type !== "timeline" || get().getNodeIrRevision(id) !== irRevision
      || JSON.stringify(node.data.timeline) !== JSON.stringify(expected)) return false;
    const composition = timeline.composition as TimelineNodeData["settings"];
    const history = videoHistoryPatch(node.data, timeline, change);
    get().setNodeData(id, { timeline: deepClone(timeline), settings: { ...node.data.settings, ...composition }, renderJob: null, ...history });
    get().propagate(id);
    return true;
  },

  commitEditorDraft: (id, expectedRevision, ir) => {
    const sid = String(id);
    const node = get().nodes.find((item) => item.id === sid);
    if (!node) return false;
    const currentRevision = Number((node.data as Record<string, unknown>)._irRevision) || 0;
    if (currentRevision !== expectedRevision) return false;
    set((state) => ({
      nodes: state.nodes.map((item) => {
        if (item.id !== sid) return item;
        const data = { ...item.data, ir: deepClone(ir), _irRevision: currentRevision + 1 } as Record<string, unknown>;
        delete data._editorDraft;
        return { ...item, data } as FlowNode;
      }),
    }));
    return true;
  },

  setStatus: (id, text, kind) => {
    set((state) => {
      const previous = state.statusLog[id] || [];
      const last = previous[previous.length - 1];
      // Дубли подряд (поллинг стадий) в журнал не пишем
      const entries = last && last.text === text && last.kind === kind
        ? previous
        : [...previous.slice(-(STATUS_LOG_LIMIT - 1)), { at: Date.now(), text, kind }];
      return {
        statuses: { ...state.statuses, [id]: { text, kind } },
        statusLog: entries === previous ? state.statusLog : { ...state.statusLog, [id]: entries },
      };
    });
  },

  setBusy: (id, v) => {
    set((state) => ({ busy: { ...state.busy, [id]: v } }));
  },

  /* Backend stages can supply a measured percent. Updates preserve startedAt so
   * elapsed time remains the duration of the whole operation. */
  setProgress: (id, progress) => {
    set((state) => ({
      progresses: progress
        ? { ...state.progresses, [id]: {
            startedAt: state.progresses[id]?.startedAt ?? Date.now(),
            expectedMs: Math.max(1_000, progress.expectedMs),
            label: progress.label,
            ...(progress.stage ? { stage: progress.stage } : {}),
            ...(Number.isFinite(progress.percent) ? { percent: Math.max(0, Math.min(100, Number(progress.percent))) } : {}),
          } }
        : Object.fromEntries(Object.entries(state.progresses).filter(([key]) => Number(key) !== id)),
    }));
  },

  cancelRun: async (id) => {
    const scope = captureNodeScope(get, id);
    // Сначала серверу: кооперативная отмена не даст начать следующую стадию
    // (следующий LLM-вызов), затем обрываем ожидание на клиенте.
    const runId = runIds.get(id);
    if (runId) void api(`/api/runs/${runId}/cancel`, {}).catch(() => undefined);
    const controller = runAborts.get(id);
    controller?.abort();
    const cancellingNode = get().nodes.find(node => Number(node.id) === id);
    if (["image", "removebackground", "generator", "qualitypass"].includes(cancellingNode?.type || "")) {
      // Image runs cancel their own provider request; never restart another worker.
      if (controller) get().setStatus(id, "Отменено", "err");
      return;
    }
    // Десктоп: с известным runId main.mjs шлёт воркеру адресный cancel
    // (cancel_token, кооперативно между стадиями); без него — прежний рестарт
    // long-воркера как последний рубеж.
    const desktopCancel = window.designDNA?.api?.cancel;
    if (desktopCancel) await desktopCancel("long", runId).catch(() => undefined);
    if (scope.owns() && (controller || desktopCancel)) get().setStatus(id, "Отменено", "err");
  },

  undoGraph: () => {
    const st = get();
    const prev = st.graphHistory.past[st.graphHistory.past.length - 1];
    if (!prev) return false;
    const current: GraphSnapshot = { nodes: st.nodes, edges: st.edges };
    set({
      nodes: prev.nodes,
      edges: prev.edges,
      graphHistory: { past: st.graphHistory.past.slice(0, -1), future: [...st.graphHistory.future, current] },
    });
    resyncAfterGraphRestore(current.edges, prev.edges);
    return true;
  },

  redoGraph: () => {
    const st = get();
    const next = st.graphHistory.future[st.graphHistory.future.length - 1];
    if (!next) return false;
    const current: GraphSnapshot = { nodes: st.nodes, edges: st.edges };
    set({
      nodes: next.nodes,
      edges: next.edges,
      graphHistory: { past: [...st.graphHistory.past, current], future: st.graphHistory.future.slice(0, -1) },
    });
    resyncAfterGraphRestore(current.edges, next.edges);
    return true;
  },

  /* Зеркало propagate (nodes.js:943-968): edit/reference получают КЛОН IR,
   * mix помечается stale; через generator/mix поток не идёт (run-based).
   * Защита от повторов — visited (nodes.js:944-946). */
  propagate: (startId, visited = new Set<number>()) => {
    if (visited.has(startId)) return;
    visited.add(startId);
    const targets = new Set(get().edges.filter((edge) => Number(edge.source) === startId).map((edge) => Number(edge.target)));
    // Each branch reads the current store. A shared descendant must see every
    // updated input in a diamond, not the snapshot from the first branch.
    for (const target of targets) get().refreshInputs(target, new Set(visited));
  },

  refreshInputs: (consId, visited = new Set<number>()) => {
    const { nodes, edges } = get();
    const cons = nodes.find((node) => Number(node.id) === consId);
    if (!cons || visited.has(consId)) return;
    if (cons.type === "edit") {
      get().refreshEdit(consId);
      get().propagate(consId, visited);
    } else if (cons.type === "reference") {
      const ir = pullInput(nodes, edges, cons, "ir");
      get().setNodeData(consId, { ir: ir ? deepClone(ir) : null });
      if (ir) {
        get().setNodeData(consId, { ir: deepClone(ir) });
        get().setStatus(consId, "IR получен — можно разбить на компоненты", "ok");
        get().propagate(consId, visited);
      }
    } else if (cons.type === "designui") {
      const artifact = pullInput(nodes, edges, cons, "artifact");
      if (!artifact) get().setNodeData(consId, { artifact: null, selectedComponent: 0 });
      if (artifact && typeof artifact === "object") {
        get().setNodeData(consId, { artifact: deepClone(artifact), selectedComponent: 0 });
        get().setStatus(consId, "Design UI synchronized", "ok");
        get().propagate(consId, visited);
      }
    } else if (cons.type === "designsystem") {
      const source = connectedDesignSystemSource(nodes, edges, cons);
      if (source) {
        const changed = cons.data._sourceFingerprint !== sourceKitFingerprint(source.data);
        get().setNodeData(consId, { sourceNodeId: Number(source.id), sourceUpdate: changed });
        if (changed) get().setStatus(consId, cons.data.systemId
          ? "Source changed — review and Sync before publishing"
          : "Source подключён — соберите UI Kit");
      } else {
        get().setNodeData(consId, { sourceNodeId: null, sourceUpdate: false });
      }
    } else if (cons.type === "page" || cons.type === "generator" || cons.type === "reskin") {
      get().setStatus(consId, "Входы изменены — запустите ноду для обновления результата");
    } else if (cons.type === "mix") {
      get().setStatus(consId, "Входы обновлены — нажмите «Смешать»");
    } else if (cons.type === "derive") {
      get().setStatus(consId, "Входы обновлены — нажмите Derive");
    } else if (cons.type === "qualitypass") {
      const ir = pullInput(nodes, edges, cons, "ir");
      if (!ir) get().setNodeData(consId, { ir: null, result: null });
      if (ir) {
        get().setNodeData(consId, { ir: deepClone(ir), result: null });
        get().setStatus(consId, "IR получен — запустите Quality Pass");
      }
    } else if (cons.type === "recorder") {
      const ir = pullInput(nodes, edges, cons, "ir");
      if (!ir) get().setNodeData(consId, { ir: null, interaction: null, recording: false, draftEvents: [] });
      if (ir) {
        get().setNodeData(consId, { ir: deepClone(ir), interaction: null, draftEvents: [], draftScenes: [{ id: "scene-0", viewport: "desktop", patch: [] }] });
        get().setStatus(consId, "Design IR ready for interaction recording", "ok");
      }
    } else if (cons.type === "motion") {
      const designIr = pullInput(nodes, edges, cons, "ir") as IRObject | null;
      const interaction = pullInput(nodes, edges, cons, "interaction") as IRObject | null;
      if (JSON.stringify(cons.data.ir) === JSON.stringify(designIr)
        && JSON.stringify(cons.data.interaction) === JSON.stringify(interaction)) return;
      get().setNodeData(consId, {
        renderJob: null,
        ir: designIr ? deepClone(designIr) : null,
        interaction: interaction ? deepClone(interaction) : null,
        motion: null,
        sceneIrs: [],
      });
      get().setStatus(consId, designIr ? "Design IR получен — соберите движение" : "Подключите Design IR");
      get().propagate(consId, visited);
    } else if (cons.type === "motiondesign") {
      const sourceMotion = pullInput(nodes, edges, cons, "motion") as IRObject | null;
      const sourceTimeline = pullInput(nodes, edges, cons, "timeline") as IRObject | null;
      const sourceVideo = pullInput(nodes, edges, cons, "video") as VideoArtifact | null;
      const connectedPrompt = pullInput(nodes, edges, cons, "prompt");
      get().setNodeData(consId, {
        sourceMotion: sourceMotion ? deepClone(sourceMotion) : null,
        sourceTimeline: sourceTimeline ? deepClone(sourceTimeline) : null,
        sourceVideo: sourceVideo ? deepClone(sourceVideo) : null,
        plannedPrompt: "",
      });
      get().setStatus(
        consId,
        sourceVideo
          ? "Готовое видео и параметры подключены — подготовьте Seedance prompt"
          : (sourceMotion || sourceTimeline || String(connectedPrompt || "").trim())
            ? "Параметры движения получены — подготовьте Seedance prompt"
            : "Подключите видео/IR или введите отдельный prompt",
      );
    } else if (cons.type === "timeline") {
      const sourcePages = videoPages(nodes, edges, cons);
      const designIr = sourcePages.find((page) => page.id === "ir")?.ir || null;
      if (JSON.stringify(cons.data.ir) === JSON.stringify(designIr) && JSON.stringify(cons.data.sourcePages || []) === JSON.stringify(sourcePages)) return;
      get().setNodeData(consId, { ir: designIr ? deepClone(designIr) : null, sourcePages: deepClone(sourcePages), timeline: null, renderJob: null, ...videoSourceCheckpoint(cons.data) });
      get().propagate(consId, visited);
      get().setStatus(consId, designIr ? `Подключено страниц: ${sourcePages.length}` : "Подключите начальную страницу");
    } else if (cons.type === "pagebridge") {
      get().runPageBridge(consId);
      get().propagate(consId, visited);
    }
  },

  /* Диспетчер run-based нод (кнопки ▶ и GraphDev.run) */
  runNode: (id) => {
    flushAllNodeText();
    const n = get().nodes.find((x) => Number(x.id) === id);
    if (!n) return;
    if (n.type === "generator") void get().runGenerator(id);
    else if (n.type === "mix") void get().runMix(id);
    else if (n.type === "page") get().runPage(id);
    else if (n.type === "sourceimport") void get().runSourceImport(id);
    else if (n.type === "derive") void get().runDerive(id);
    else if (n.type === "reskin") void get().runReskin(id);
    else if (n.type === "image" || n.type === "removebackground") void get().runImage(id);
    else if (n.type === "qualitypass") void get().runQualityPass(id);
    else if (n.type === "recorder") void get().runRecorder(id);
    else if (n.type === "motion") void get().runMotion(id);
    else if (n.type === "motiondesign") void get().planMotionDesign(id);
    else if (n.type === "timeline") void get().runTimeline(id);
    else if (n.type === "pagebridge") get().runPageBridge(id);
  },

  /* Зеркало runGenerator (nodes.js:498-518): бриф тянем из входа prompt (pull-based)
   * с fallback на ownPrompt, styleHint — из входа style, tokens — из входа style DNA; payload {brief, count,
   * provider, styleHint, tokens?}. Результат — variants + active=0,
   * propagate проталкивает clones[active] в edit/reference ниже по графу. */
  runGenerator: async (id) => {
    flushAllNodeText();
    const scope = captureNodeScope(get, id);
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "generator" || st.busy[id]) return;
    const data = n.data as GeneratorNodeData;
    let inputKey = generatorInputKey(st.nodes, st.edges, n, st.designSystemPicker);
    const nonDsKey = generatorInputKey(st.nodes, st.edges, n, st.designSystemPicker, true);
    let publishingDs = false;
    scope.watchInputs(() => {
      const state = get(), node = state.nodes.find(node => node.id === n.id);
      return !!node && generatorInputKey(state.nodes, state.edges, node, state.designSystemPicker, publishingDs) === (publishingDs ? nonDsKey : inputKey);
    });
    const brief = String(
      pullInput(st.nodes, st.edges, n, "prompt") || data.ownPrompt || "",
    ).trim();
    if (!brief) {
      if (scope.owns()) get().setStatus(id, "Нет промта: подключите провод или заполните поле", "err");
      return;
    }
    const designSystemInput = pullInput(st.nodes, st.edges, n, "designSystem");
    const tokens = designSystemInput && typeof designSystemInput === "object" && !(designSystemInput as { systemId?: unknown }).systemId
      ? (designSystemInput as Record<string, unknown>) : undefined;
    const referenceRaw = pullInput(st.nodes, st.edges, n, "reference");
    const referenceEdge = st.edges.find((edge) => edge.target === n.id && edge.targetHandle === "reference");
    const referenceNode = referenceEdge ? st.nodes.find((node) => node.id === referenceEdge.source) : null;
    const referenceMaster = referenceNode
      ? (referenceNode.data as Record<string, unknown>)._dsMaster as Record<string, unknown> | undefined
      : undefined;
    const styleHint = typeof referenceRaw === "string" && referenceRaw.trim() ? referenceRaw.trim() : undefined;
    const desktop = window.designDNA;
    const effort: "medium" | "high" | "max" = ["medium", "high", "max"].includes(data.effort)
      ? data.effort
      : "medium";
    const provider = nodeProvider(data.provider);
    const count = Math.max(1, Math.min(2, Number(data.count) || 1));
    const providerLabel = provider === "codex"
      ? PROVIDER_LABELS.codex
      : `${PROVIDER_LABELS[provider]} · ${effort}`;
    if (scope.owns()) get().setStatus(id, `Генерация (${providerLabel}, ${count})… 20–120 сек`);
    const signal = beginRunAbort(id);
    get().setNodeData(id, { qualityScores: [], qualityReviews: [] });
    let stopPoll: () => void = () => {};
    if (scope.owns()) get().setBusy(id, true);
    const startedAt = Date.now();
    const progressLabel = `Генерация · ${providerLabel}`;
    let designSystemRef: Record<string, unknown> | null = null;
    // Стадии честные: клиент знает только «ждём модель» и «Quality Pass»,
    // процента у синхронного POST нет — NodeShell показывает indeterminate.
    if (scope.owns()) get().setProgress(id, { expectedMs: 90_000, label: progressLabel, stage: "Готовлю промпт" });
    try {
      // ДС по проводу приоритетнее глобального выбора проекта: граф говорит,
      // от какой системы генерировать. Черновик не годится — strict-контекст
      // компилируется из опубликованной ревизии.
      let wiredDs = designSystemInput as
        { systemId?: string; revision?: number; contentHash?: string; status?: string; name?: string } | null;
      if (wiredDs && wiredDs.systemId) {
        if (wiredDs.status === "draft") {
          const dsId = Number((wiredDs as { nodeId?: number }).nodeId);
          const dsNode = get().nodes.find((node) => Number(node.id) === dsId);
          const dsData = dsNode?.data as DesignSystemNodeData | undefined;
          if (get().busy[dsId] || dsData?._dsFinishing) {
            get().setStatus(id, "Дизайн-система ещё обрабатывается. Дождитесь завершения проверки и повторите генерацию.", "err");
            return;
          }
          const needsReview = !!dsData?.sourceUpdate || Number(dsData?.summary?.reviewMasters || 0) > 0
            || Object.keys(dsData?.document?.reviewComponents || {}).length > 0;
          if (scope.owns()) get().setStatus(id, needsReview ? "Проверяю и дорабатываю ДС…" : "Публикую ДС…");
          publishingDs = true;
          const ready = !needsReview || await scope.wait(get().finishDesignSystem(dsId));
          const published = ready && ((get().nodes.find((node) => Number(node.id) === dsId)?.data as DesignSystemNodeData | undefined)?.status === "published"
            || await scope.wait(get().publishDesignSystem(dsId)));
          if (!published) {
            const dsNode = get().nodes.find((node) => Number(node.id) === Number((wiredDs as { nodeId?: number }).nodeId));
            const reason = String((dsNode?.data as DesignSystemNodeData | undefined)?.lastError || "публикация заблокирована");
            if (scope.owns()) get().setStatus(id, `Дизайн-система не готова: ${reason}. Откройте диагностику ноды UI Kit.`, "err");
            if (scope.owns()) get().setBusy(id, false);
            if (scope.owns()) get().setProgress(id, null);
            return;
          }
          const fresh = get();
          const freshGenerator = fresh.nodes.find((node) => Number(node.id) === id)!;
          wiredDs = pullInput(fresh.nodes, fresh.edges, freshGenerator, "designSystem") as typeof wiredDs;
          inputKey = generatorInputKey(fresh.nodes, fresh.edges, freshGenerator, fresh.designSystemPicker);
          publishingDs = false;
        }
        if (wiredDs?.status !== "published") {
          if (scope.owns()) get().setStatus(id, `ДС «${wiredDs?.name || wiredDs?.systemId}» не опубликована. Откройте ноду ДС → AI-ревью`, "err");
          if (scope.owns()) get().setBusy(id, false);
          if (scope.owns()) get().setProgress(id, null);
          return;
        }
        const picker = get().designSystemPicker;
        designSystemRef = {
          systemId: wiredDs.systemId,
          revision: wiredDs.revision,
          contentHash: wiredDs.contentHash || "",
          usageMode: String(data.designSystemUsageMode || picker?.usageMode || "strict"),
          mockFixtureProfile: String((data as Record<string, unknown>).designSystemFixture || picker?.fixtureProfile || "typical"),
        };
      } else {
        designSystemRef = pinnedDesignSystemRef(
          data as unknown as Record<string, unknown>,
          get().designSystems,
          get().designSystemPicker,
        );
      }
      const referenceIrs = referenceRaw && typeof referenceRaw === "object" && Array.isArray((referenceRaw as IRObject).tree)
        ? [{
            ...(referenceRaw as IRObject),
            ...(referenceMaster ? {
              meta: { ...(((referenceRaw as IRObject).meta || {}) as Record<string, unknown>), _dsMaster: referenceMaster },
            } : {}),
          } as IRObject]
        : undefined;
      const request = {
        brief,
        count,
        provider,
        effort,
        surface: data.surface || "auto",
        designStyle: data.designStyle || "auto",
        allowStrictFallback: false,
        styleHint,
        tokens,
        preset: data.preset || undefined,
        designSystem: designSystemRef,
        referenceIrs,
        // T1 may expose the staged contract under either name while old
        // servers simply ignore these extra Pydantic fields.
        selectedDirection: String((data as Record<string, unknown>).selectedDirection || "all"),
        direction: String((data as Record<string, unknown>).selectedDirection || "all"),
        allDirections: String((data as Record<string, unknown>).selectedDirection || "all") === "all",
      };
      let res: GenerateResp;
      if (!desktop) {
        const runId = newRunId();
        if (scope.owns()) get().setProgress(id, { expectedMs: 90_000, label: progressLabel, stage: "Модель генерирует IR" });
        stopPoll = watchRunStages(id, runId, 90_000, progressLabel);
        try {
          res = await scope.wait(api<GenerateResp>("/api/generate", { ...request, runId }, { signal, runId }));
        } finally {
          stopPoll();
        }
      } else {
        const prepareRequest = { ...request, prepareOnly: true, clientArtDirection: true };
        let prepared = await scope.wait(api<GenerateResp>("/api/generate", prepareRequest, { signal }));
        if (prepared.artDirection?.messages?.length) {
          // Арт-направления идут через транспорт Electron (регулятор, трасса,
          // GPT по подписке через Codex), а не из Python-воркера.
          if (scope.owns()) get().setProgress(id, { expectedMs: 60_000, label: progressLabel, stage: "Модель предлагает арт-направления" });
          const directionsAnswer = await scope.wait(cancellableChat({
            ...chatRoute(provider, "medium"),
            profile: "art_direction",
            messages: prepared.artDirection.messages,
          }, signal));
          if (signal.aborted) throw new DOMException("cancelled", "AbortError");
          prepared = await scope.wait(api<GenerateResp>("/api/generate", { ...prepareRequest, artDirectionRaw: directionsAnswer.content }, { signal }));
        }
        if (!prepared.prompts?.length && Array.isArray(prepared.variants) && prepared.variants.length) {
          // strict + пиннутый мастер, который не влезает в промпт: сервер уже
          // материализовал точную копию мастера, модель не нужна.
          res = prepared;
        } else {
          if (!prepared.prompts?.length) throw new Error("Не удалось подготовить запросы генератора");
          const rawOutputs: string[] = [];
          for (let i = 0; i < prepared.prompts.length; i += 1) {
            const many = prepared.prompts.length > 1 ? ` ${i + 1}/${prepared.prompts.length}` : "";
            if (scope.owns()) get().setProgress(id, { expectedMs: 90_000, label: progressLabel, stage: `Модель генерирует IR${many}` });
            const answer = await scope.wait(cancellableChat({
              ...chatRoute(provider, effort),
              messages: prepared.prompts[i].messages,
            }, signal));
            if (signal.aborted) throw new DOMException("cancelled", "AbortError");
            rawOutputs.push(answer.content);
          }
          if (scope.owns()) get().setProgress(id, { expectedMs: 90_000, label: progressLabel, stage: "Проверка схемы и автофиксы" });
          res = await scope.wait(api<GenerateResp>("/api/generate", { ...request, rawOutputs, preparedContextId: prepared.preparedContextId }, { signal }));
        }
      }
      const directionResponse = res as GenerateDirectionResp;
      const variants = Array.isArray(res.variants) ? [...res.variants] : [];
      const generationContext = { inputKey, pageId: st.activePageId, brief, startedAt };
      const directions = generatorDirections(directionResponse);
      const variantDirections = generatorVariantDirections(directionResponse, variants, directions);
      const directionPatch = { directions };
      const generationLog = (res as unknown as Record<string, unknown>).generationLog;
      const logPatch = generationLog && typeof generationLog === "object" ? { generationLog: generationLog as Record<string, unknown> } : {};
      if (scope.owns()) get().setNodeData(id, { variants, active: 0, qualityScores: [], qualityReviews: [], generationContext, variantDirections, ...directionPatch, ...logPatch } as unknown as Partial<GeneratorNodeData>);
      // Quality Pass встроен: судья + починка каждого варианта тем же
      // провайдером. Провал судьи не теряет вариант — он остаётся как есть
      // с прочерком в статусе.
      const qualityScores: (number | null)[] = [];
      const qualityReviews: GeneratorQualityReview[] = [];
      let repairedCount = 0;
      for (let i = 0; i < variants.length; i += 1) {
        const label = variants.length > 1 ? ` ${i + 1}/${variants.length}` : "";
        if (scope.owns()) get().setStatus(id, `Quality Pass${label}: судья…`);
        if (scope.owns()) get().setProgress(id, { expectedMs: 60_000, label: `Quality Pass${label}`, stage: "Судья оценивает" });
        const qpRunId = newRunId();
        const stopQpPoll = desktop ? () => {} : watchRunStages(id, qpRunId, 60_000, `Quality Pass${label}`);
        try {
          const qp = await scope.wait(qualityPassCycle(variants[i], brief, provider, effort, (stage) => {
            scope.check();
            if (scope.owns()) get().setStatus(id, `Quality Pass${label}: ${stage}…`);
            if (scope.owns()) get().setProgress(id, { expectedMs: 60_000, label: `Quality Pass${label}`, stage });
          }, { signal, runId: qpRunId, surface: res.designPolicy?.surface || data.surface || "auto", visualReview: true,
            designSystem: designSystemRef ? { ...designSystemRef, ...((res.designSystem?.ref || {}) as Record<string, unknown>) } : null }));
          if (qp.ir) variants[i] = qp.ir;
          const rawScore = qp.scorecard?.score;
          const score = rawScore == null || !Number.isFinite(Number(rawScore)) ? null : Number(rawScore);
          qualityScores.push(score);
          qualityReviews.push({
            score,
            passed: qp.acceptance?.status === "unverified" ? null : typeof qp.passed === "boolean" ? qp.passed : null,
            reasons: (qp.scorecard?.issues || []).map((issue) => {
              const problem = String(issue.problem || "").trim();
              return problem || String((issue as Record<string, unknown>).instruction || "").trim();
            }).filter(Boolean).slice(0, 5),
          });
          if (qp.repair?.applied) repairedCount += 1;
        } catch (qpError) {
      if (!scope.owns()) return;
          if (isAbortError(qpError) || signal.aborted) throw qpError;
          console.warn("Quality Pass: вариант оставлен без оценки", qpError);
          qualityScores.push(null);
          qualityReviews.push({ score: null, passed: null, reasons: [] });
        } finally {
          stopQpPoll();
        }
      }
      if (scope.owns()) get().setNodeData(id, { variants: [...variants], active: 0, qualityScores, qualityReviews, generationContext, variantDirections, ...directionPatch } as unknown as Partial<GeneratorNodeData>);
      const errNote = res.errors && res.errors.length ? `, ошибок: ${res.errors.length}` : "";
      const fixedCount = (res.qa || []).reduce((s, q) => s + (q.fixed || 0), 0);
      const qaNote = fixedCount ? `, автофиксов QA: ${fixedCount}` : "";
      const designNote = res.design?.label ? `, тип: ${res.design.label}` : "";
      const qpNote = qualityScores.length
        ? ` · QP ${qualityScores.map((score) => (score == null ? "—" : score)).join("/")}`
        + (repairedCount ? ` (починок: ${repairedCount})` : "")
        : "";
      const needsRevision = qualityReviews
        .map((review, index) => ({ review, index }))
        .filter(({ review }) => review.passed === false || (review.score != null && review.score < 80));
      const strictFallback = String((generationLog as Record<string, unknown> | undefined)?.strictFallback || "");
      if (strictFallback === "extend") {
        if (scope.owns()) get().setStatus(id, "strict: мастера не использованы, результат принят в режиме extend", "err");
      } else if (needsRevision.length) {
        const reasons = needsRevision.flatMap(({ review }) => review.reasons).slice(0, 3);
        const reasonNote = reasons.length ? `: ${reasons.join("; ")}` : "";
        if (scope.owns()) get().setStatus(id, `Нужна доработка${reasonNote}`, "err");
      } else if (!variants.length || qualityReviews.some((review) => review.passed == null)) {
        if (scope.owns()) get().setStatus(id, "Предпросмотр создан · проверка не завершена", "err");
      } else {
        if (scope.owns()) get().setStatus(id, `Предпросмотр проверен: вариантов ${variants.length}${errNote}${qaNote}${designNote}${qpNote} · ${((Date.now() - startedAt) / 1000).toFixed(0)}с`, "ok");
      }
      if (scope.owns()) get().propagate(id);
    } catch (e) {
      if (!scope.owns()) return;
      if (isAbortError(e) || signal.aborted) {
        if (scope.owns()) get().setStatus(id, e instanceof Error && e.message.startsWith("Входные") ? e.message : `Отменено · ${((Date.now() - startedAt) / 1000).toFixed(0)}с`, "err");
      } else {
        const msg = friendlyProviderError(e);
        const strictFailure = String(designSystemRef?.usageMode || "") === "strict"
          && /Design System Strict|Strict.*мастер|strict.*master/i.test(msg);
        if (scope.owns()) get().setStatus(id, strictFailure
          ? `Strict не смог использовать мастер: ${msg}. Проверьте референс или переключите режим ДС на extend.`
          : "Ошибка: " + msg, "err");
        toast("Генератор: " + msg, "error");
      }
    } finally {
      stopPoll();
      endRunAbort(id, signal);
      if (scope.owns()) get().setProgress(id, null);
      if (scope.owns()) get().setBusy(id, false);
    }
  },

  /* Зеркало runMix (nodes.js:815-836): IR тянем из подключённых входов (pull),
   * веса нормируются 0..1; payload {irs, weights}. */
  runMix: async (id) => {
    flushAllNodeText();
    const scope = captureNodeScope(get, id);
    watchNodeInputs(scope, get, id, ["inputs", "weights", "variants"]);
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "mix" || st.busy[id]) return;
    const data = n.data as MixNodeData;
    const irs: unknown[] = [];
    const weights: number[] = [];
    const labels: string[] = [];
    for (const name of data.inputs) {
      const ir = pullInput(st.nodes, st.edges, n, name);
      if (ir) {
        irs.push(ir);
        weights.push((data.weights[name] ?? 50) / 100);
        labels.push(`${name}:${data.weights[name] ?? 50}%`);
      }
    }
    if (irs.length < 2) {
      if (scope.owns()) get().setStatus(id, "Нужно минимум 2 подключённых IR-входа", "err");
      return;
    }
    if (scope.owns()) get().setStatus(id, "Смешиваю…");
    if (scope.owns()) get().setBusy(id, true);
    try {
      // Счётчик вариантов (хендофф): вариант 0 — точные веса, дальше акцент
      // детерминированно ротируется по входам (/api/mix даёт один результат за вызов).
      const count = Math.max(1, Math.min(8, Number(data.variants) || 1));
      const runs: number[][] = [];
      for (let k = 0; k < count; k++) {
        if (k === 0) {
          runs.push(weights);
          continue;
        }
        const boosted = weights.map((w, i) => (i === (k - 1) % weights.length ? w * 1.35 + 0.05 : w));
        const sum = boosted.reduce((s, w) => s + w, 0) || 1;
        runs.push(boosted.map((w) => w / sum));
      }
      const results = await scope.wait(Promise.all(
        runs.map((run) => api<MixResp>("/api/mix", { irs, weights: run })),
      ));
      const mixVariants = results.map((res) => res.ir).filter((ir): ir is IRObject => !!ir);
      if (scope.owns()) get().setNodeData(id, { mixVariants, mixActive: 0, ir: mixVariants[0] || null });
      if (scope.owns()) get().setStatus(id, `${irs.length} вх → ${mixVariants.length} вар · ` + labels.join(" + "), "ok");
      if (scope.owns()) get().propagate(id);
    } catch (e) {
      if (!scope.owns()) return;
      const msg = e instanceof Error ? e.message : String(e);
      if (scope.owns()) get().setStatus(id, "Ошибка: " + msg, "err");
      toast("Микс: " + msg, "error");
    } finally {
      if (scope.owns()) get().setBusy(id, false);
    }
  },

  /* Page: сборка страницы из подключённых блоков — детерминированно, без LLM.
   * Порядок inputs = порядок секций; tokens — style DNA с провода > первый блок. */
  refreshEdit: (id) => {
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "edit") return;
    const data = n.data as EditNodeData;
    const inputs = data.inputs || ["ir"];
    const blocks = inputs
      .map((name) => sourceInputForPort(st.nodes, st.edges, n, name))
      .filter((block): block is SourceInputBlock => block !== null);
    const fingerprint = inputFingerprint(blocks);
    if ((data as Record<string, unknown>)._inputFingerprint === fingerprint) return;
    if (!blocks.length) {
      get().setNodeData(id, { _inputFingerprint: fingerprint, ir: null, sourceRegistry: {}, nodeSources: {}, layoutEvidence: [] });
      get().setStatus(id, "Подключите хотя бы один компонент", "err");
      return;
    }
    const meta = blocks[0].ir.meta as Record<string, unknown> | undefined;
    const viewport = meta?.activeViewport === "mobile" || meta?.activeViewport === "tablet" ? meta.activeViewport : "desktop";
    const result = composeSourceInputs(blocks, null, viewport, blocks.length > 1);
    if (JSON.stringify(data.ir) !== JSON.stringify(result.ir)) get().setNodeData(id, { ...result, _inputFingerprint: fingerprint });
    else get().setNodeData(id, { _inputFingerprint: fingerprint });
    get().setStatus(id, `${blocks.length} компонент(а) · ${Object.keys(result.sourceRegistry).length} источн.`, "ok");
  },

  runPage: (id) => {
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "page") return;
    const data = n.data as PageNodeData;
    const blocks = data.inputs
      .map((name) => sourceInputForPort(st.nodes, st.edges, n, name))
      .filter((block): block is SourceInputBlock => block !== null);
    if (!blocks.length) {
      get().setStatus(id, "Подключите хотя бы один IR-вход", "err");
      return;
    }
    const tokensRaw = pullInput(st.nodes, st.edges, n, "tokens");
    const tokens = tokensRaw && typeof tokensRaw === "object" ? (tokensRaw as IRObject) : null;
    const result = composeSourceInputs(blocks, tokens, data.activeViewport || "desktop", true);
    get().setNodeData(id, result);
    get().setStatus(id, `Собрана: блоков ${blocks.length}`, "ok");
    get().propagate(id);
  },
  runSourceImport: async (id) => {
    flushAllNodeText();
    const scope = captureNodeScope(get, id);
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "sourceimport" || st.busy[id]) return;
    const data = n.data as SourceImportNodeData;
    const provider = nodeProvider(data.aiProvider);
    const effort = nodeEffort(data.aiEffort || "high");
    const signal = beginRunAbort(id);
    const sourceRun = newRunId();
    const sourceInput = (value: SourceImportNodeData) => inputFingerprint({
      mode: value.mode, url: value.url, image: value.image, mine: value.mine,
      authenticatedSession: value.authenticatedSession, kit: sourceKitFingerprint(value),
    });
    let inputAtStart = sourceInput(data);
    if (scope.owns()) get().setNodeData(id, { _sourceRun: sourceRun });
    const ownsRun = () => get().activePageId === st.activePageId && runAborts.get(id)?.signal === signal
      && get().nodes.some((node) => Number(node.id) === id && node.type === "sourceimport"
        && (node.data as unknown as Record<string, unknown>)._sourceRun === sourceRun);
    const guard = () => {
      const current = get().nodes.find((node) => Number(node.id) === id);
      if (signal.aborted || !ownsRun() || !current || sourceInput(current.data as SourceImportNodeData) !== inputAtStart)
        throw new DOMException("Source изменился или импорт отменён", "AbortError");
    };
    const stages: Record<string, AiPipelineStage> = {};
    const recordStage = (name: string, status: AiPipelineStage["status"], message: string) => {
      if (!ownsRun()) return;
      stages[name] = { status, message, provider, updatedAt: new Date().toISOString() };
      if (scope.owns()) get().setNodeData(id, { pipelineStatus: { ...stages } });
    };
    const warnings = () => Object.values(stages).filter((stage) => ["failed", "warning", "cancelled"].includes(stage.status)).map((stage) => stage.message);
    const finishStatus = (message: string, failed = false) => {
      const notes = warnings();
      if (scope.owns()) get().setStatus(id, `${message}${notes.length ? ` · ${notes.join("; ")}` : ""}`, failed || notes.length ? "err" : "ok");
    };
    if (scope.owns()) get().setBusy(id, true);
    const startedAt = Date.now();
    if (scope.owns()) get().setProgress(id, { expectedMs: 90_000, label: data.mode === "screenshot" ? "Скриншот → IR" : "Импорт Source" });
    try {
      if (data.mode === "screenshot") {
        if (!data.image) {
          if (scope.owns()) get().setStatus(id, "Загрузите скриншот элемента", "err");
          return;
        }
        // Сначала — сегментация компонентов агентом (Claude/GPT по выбору на
        // ноде): каждая рамка становится мастером для дизайн-системы. Если
        // сегментация недоступна (web-режим, отказ провайдера, ноль рамок) —
        // прежний путь: единый pixel-capture слепок.
        let segmented: SegmentResp | null = null;
        recordStage("import", "running", "Импорт скриншота…");
        if (window.designDNA) {
          try {
            recordStage("segmentation", "running", "AI-сегментация…");
            segmented = await scope.wait(segmentScreenshotWithAi(
              data.image, provider, get().setStatus, id, effort, guard));
            guard();
            recordStage("segmentation", segmented ? "success" : "warning", segmented ? "Компоненты размечены" : "AI-сегментация не вернула компоненты");
          } catch (error) {
      if (!scope.owns()) return;
            guard();
            recordStage("segmentation", "failed", `Сегментация: ${friendlyProviderError(error)}`);
          }
        }
        if (segmented?.block) {
          guard();
          const block = { ...segmented.block, lit: true };
          if (scope.owns()) get().setNodeData(id, {
            blocks: [block],
            tokens: (segmented.tokens || (block.ir as IRObject | undefined)?.tokens || null) as Record<string, unknown> | null,
            sourceArtifact: segmented.sourceArtifact || null,
          });
          const secs = ((Date.now() - startedAt) / 1000).toFixed(0);
          recordStage("import", "success", "Скриншот импортирован");
          finishStatus(`${segmented.regions.length} компонент(ов) из скриншота · ${secs}с`);
          if (scope.owns()) get().propagate(id);
          return;
        }
        if (scope.owns()) get().setStatus(id, "Скриншот → pixel capture через подключённый аккаунт…");
        guard();
        if (provider === "codex" || provider === "claude") throw new Error("AI-сегментация не завершена; API fallback для выбранного desktop-аккаунта отключён");
        const res = await scope.wait(api<ReproduceResp>("/api/reproduce", {
          image: data.image,
          url: "",
          provider,
        }));
        guard();
        const ir = res.ir || null;
        const dna = extractStyleDna(ir, null);
        const blocks = ir
          ? [{
              name: "capture",
              selector: "screenshot",
              ir,
              source: "vision" as const,
              parserContract: res.parserContract,
              lit: true,
            }]
          : [];
        if (scope.owns()) get().setNodeData(id, { blocks, tokens: dna.tokens, sourceArtifact: null });
        const secs = ((Date.now() - startedAt) / 1000).toFixed(0);
        recordStage("import", ir ? "success" : "failed", ir ? "Скриншот импортирован" : "Не удалось получить IR из скриншота");
        finishStatus(`capture + Style DNA · ${secs}с`, !ir);
      } else {
        const rawUrl = (data.url || "").trim();
        const url = rawUrl && !/^[a-z][a-z\d+.-]*:\/\//i.test(rawUrl)
          ? rawUrl.startsWith("//") ? `https:${rawUrl}` : `https://${rawUrl}`
          : rawUrl;
        if (!url) {
          if (scope.owns()) get().setStatus(id, "Введите URL сайта", "err");
          return;
        }
        if (!data.mine) {
          if (scope.owns()) get().setStatus(id, "Отметьте «это мой сайт/есть право»", "err");
          return;
        }
        if (data.importedUrl === url && data.blocks.length > 0) {
          Object.assign(stages, data.pipelineStatus || {});
          finishStatus(`Уже загружено локально · ${data.blocks.length} блоков`);
          return;
        }
        if (url !== data.url) if (scope.owns()) get().setNodeData(id, { url });
        inputAtStart = sourceInput(get().nodes.find((node) => Number(node.id) === id)!.data as SourceImportNodeData);
        recordStage("import", "running", "Source Import…");
        if (scope.owns()) get().setStatus(id, `Импортирую ${url.slice(0, 30)}…`);
        const desktop = window.designDNA;
        const initial = await scope.wait(api<BlockParseResp | BlockParseJobResp>("/api/block-parse", {
          url,
          asyncJob: true,
          fullResolutionEvidence: !!desktop,
          useAuthenticatedSession: !!data.authenticatedSession && !!window.designDNA?.sourceAuth,
          viewports: [
            { name: "desktop", width: 1440, height: 900 },
            { name: "tablet", width: 768, height: 1024 },
            { name: "mobile", width: 390, height: 844 },
          ],
        }));
        guard();
        let res: BlockParseResp;
        if ("jobId" in initial) {
          let job = initial;
          const started = Date.now();
          const deadline = started + 12 * 60_000;
          while (job.status === "queued" || job.status === "running") {
            guard();
            if (scope.owns()) get().setProgress(id, {
              expectedMs: 90_000,
              label: job.stageLabel || "Source Import",
              percent: job.progress,
            });
            if (scope.owns()) get().setStatus(id, `${job.stageLabel || "Source Import"} · ${Math.round(job.progress)}%`);
            if (Date.now() >= deadline) throw new Error("Source Import превысил лимит 12 минут");
            // Бэкофф: первые 10 с опрашиваем часто (стадии сменяются быстро),
            // дальше реже — импорт идёт минутами, а каждый опрос это полный
            // IPC → stdio → ASGI round-trip.
            const elapsed = Date.now() - started;
            const delay = elapsed < 10_000 ? 400 : elapsed < 60_000 ? 1_000 : 2_000;
            await scope.wait(new Promise((resolve) => setTimeout(resolve, delay)));
            guard();
            job = await scope.wait(apiGet<BlockParseJobResp>(`/api/block-parse/job/${encodeURIComponent(job.jobId)}`));
            guard();
          }
          if (job.status === "error") throw new Error(job.error || "Source Import завершился с ошибкой");
          if (!job.result) throw new Error("Source Import завершился без результата");
          res = job.result;
        } else {
          // Compatibility with web/dev servers and intercepted UI fixtures.
          res = initial;
        }
        // Source screenshots are comparison evidence. Persist them before the
        // large editable IR enters state; the generic autosave traversal is
        // intentionally time-boxed and may otherwise reach these fields too
        // late, leaving Compare empty after a restart.
        await scope.wait(offloadSourceEvidenceInPlace(res.blocks || []));
        guard();
        recordStage("import", "success", "Source захвачен");
        recordStage("refine", "skipped", "AI-уточнение не требуется или отключено");
        // AI-уточнение: детерминированный разбор перечислил, чего не смог
        // решить сам; модель переименовывает компоненты и уточняет роли блоков.
        // IR не меняется — fidelity-гейт этим путём обойти нельзя.
        if (data.aiRefine && res.ambiguities?.length && window.designDNA) {
          try {
            recordStage("refine", "running", "AI-уточнение…");
            const refined = await scope.wait(refineSourceWithAi(
              res, provider, get().setStatus, id, effort, guard,
            ));
            guard();
            if (refined) res = refined;
            recordStage("refine", "success", refined ? "AI-уточнение применено" : "AI-уточнение: без изменений");
          } catch (error) {
      if (!scope.owns()) return;
            guard();
            // Уточнение опционально: детерминированный результат остаётся в силе.
            recordStage("refine", "failed", `AI-уточнение: ${friendlyProviderError(error)}`);
          }
        }
        // AI-починка расхождений идёт всегда, без тумблера: пользователь должен
        // получить готовый кит, а не список «нужна проверка». Судья — тот же
        // fidelity-harness, правка принимается только при росте измеренного
        // сходства, поэтому автоматический прогон не может сделать хуже.
        const needsRepair = (res.blocks || []).some((block) => !blockGatePassed(block));
        if (window.designDNA && needsRepair) {
          try {
            recordStage("repair", "running", "AI-починка…");
            const repaired = await scope.wait(repairSourceWithAi(
              res, provider, data.activeViewport || "desktop",
              get().setStatus, id, effort, guard, (message) => recordStage("repair", "failed", message),
            ));
            guard();
            if (repaired) res = repaired;
            if (stages.repair.status !== "failed") recordStage("repair", repaired ? "success" : "warning", repaired ? "AI-починка применена" : "AI-починка: улучшений не найдено");
          } catch (error) {
      if (!scope.owns()) return;
            guard();
            recordStage("repair", "failed", `AI-починка: ${friendlyProviderError(error)}`);
          }
        } else recordStage("repair", "skipped", needsRepair
          ? "AI-починка не запущена: desktop недоступен"
          : "AI-починка не требуется: нет блоков с непройденной проверкой");
        guard();
        const fidelityFailures = (res.blocks || []).filter((block) => block.fidelityReport?.gate?.passed === false).length;
        recordStage("fidelity", fidelityFailures ? "warning" : (res.blocks || []).every(blockGatePassed) ? "success" : "skipped",
          fidelityFailures ? `Fidelity: ${fidelityFailures} блок(ов) требуют проверки` : (res.blocks || []).every(blockGatePassed) ? "Fidelity пройден" : "Fidelity не проверен");
        const quality = (res.sourceArtifact?.components || []).map((component) => component.quality);
        const qualityFailures = quality.filter((item) => item?.gate?.passed === false);
        recordStage("quality", qualityFailures.length ? "warning" : quality.length && quality.every((item) => item?.gate?.passed === true) ? "success" : "skipped",
          qualityFailures.length ? `Quality: ${qualityFailures.flatMap((item) => item.gate?.reasons || []).join("; ") || `${qualityFailures.length} компонент(ов) не прошли проверку`}`
            : quality.length && quality.every((item) => item?.gate?.passed === true) ? "Quality пройден" : "Quality не проверен");
        // Refine/repair responses may expand blob handles back to inline images.
        // Persist the final response too, before it becomes graph state.
        await scope.wait(offloadSourceEvidenceInPlace(res.blocks || []));
        guard();
        const currentSource = get().nodes.find((node) => Number(node.id) === id);
        if (!currentSource || currentSource.type !== "sourceimport") return;
        const litBefore = new Set(currentSource.data.blocks.filter((b) => b.lit).map((b) => b.name));
        const blocks = (res.blocks || []).map((b) => ({
          ...b,
          cached: !!res.cached || !!b.cached,
          lit: litBefore.has(b.name),
        }));
        const timingsMs = res.diagnostics?.timingsMs || {};
        const measuredTotalMs = Number(timingsMs.total);
        if (scope.owns()) get().setNodeData(id, {
          blocks,
          tokens: res.tokens || null,
          sourceArtifact: res.sourceArtifact || null,
          importedUrl: url,
          lastRun: {
            cached: !!res.cached,
            pipelineVersion: res.diagnostics?.pipelineVersion,
            totalMs: Number.isFinite(measuredTotalMs) ? measuredTotalMs : Date.now() - startedAt,
            timingsMs,
          },
        });
        const sid = String(id);
        const alive = new Set<string>(["artifact", "tokens", ...blocks.filter((b) => b.lit && !b.error).map((b) => b.name)]);
        const removedTargets = new Set(get().edges
          .filter((e) => e.source === sid && !alive.has(e.sourceHandle ?? ""))
          .map((e) => Number(e.target)));
        set((state) => ({
          edges: state.edges.filter((e) => e.source !== sid || alive.has(e.sourceHandle ?? "")),
        }));
        for (const target of removedTargets) get().refreshInputs(target);
        const errCount = blocks.filter((b) => b.error).length;
        const authNote = res.authWarning ? ` · ${res.authWarning}` : "";
        const cacheNote = res.cached ? " · локальный кэш" : "";
        const secs = ((Number.isFinite(measuredTotalMs) ? measuredTotalMs : Date.now() - startedAt) / 1000).toFixed(1);
        recordStage("import", errCount ? "warning" : "success", errCount ? `Source Import: ошибок ${errCount}` : "Source импортирован");
        finishStatus(`${blocks.length} блоков (${errCount} ошибок) · Source Import${cacheNote}${authNote} · ${secs}с`, !!errCount);
      }
      if (scope.owns()) get().propagate(id);
    } catch (e) {
      if (!scope.owns()) return;
      if (!ownsRun()) return;
      const msg = e instanceof Error ? e.message : String(e);
      for (const [name, stage] of Object.entries(stages)) if (stage.status === "running") recordStage(name, signal.aborted || (e instanceof DOMException && e.name === "AbortError") ? "cancelled" : "failed", msg);
      if (scope.owns()) get().setStatus(id, "Ошибка: " + msg, "err");
      toast("Source Import: " + msg, "error");
    } finally {
      if (ownsRun()) { if (scope.owns()) get().setProgress(id, null); if (scope.owns()) get().setBusy(id, false); if (scope.owns()) get().setNodeData(id, { _sourceRun: null }); }
      endRunAbort(id, signal);
    }
  },

  runDerive: async (id) => {
    flushAllNodeText();
    const scope = captureNodeScope(get, id);
    watchNodeInputs(scope, get, id, ["prompt", "count", "provider", "effort", "designSystem"]);
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "derive" || st.busy[id]) return;
    const data = n.data as DeriveNodeData;
    const provider = nodeProvider(data.provider);
    const effort = nodeEffort(data.effort);
    const prompt = String(pullInput(st.nodes, st.edges, n, "prompt") || data.prompt || "").trim();
    const reference = pullInput(st.nodes, st.edges, n, "reference");
    const tokens = pullInput(st.nodes, st.edges, n, "tokens");
    if (!prompt) {
      if (scope.owns()) get().setStatus(id, "Опишите, какой компонент получить", "err");
      return;
    }
    const styleHint = [
      tokens ? "Style DNA:\n" + JSON.stringify(tokens) : "",
      reference ? "Reference IR:\n" + JSON.stringify(reference).slice(0, 9000) : "",
    ].filter(Boolean).join("\n\n");
    if (scope.owns()) get().setStatus(id, `Derive: ${data.count} вариант(а) через подключённый аккаунт…`);
    if (scope.owns()) get().setBusy(id, true);
    try {
      const request = {
        brief: prompt,
        count: data.count,
        provider,
        effort,
        styleHint: styleHint || undefined,
        tokens: tokens && typeof tokens === "object" ? tokens : undefined,
        designSystem: pinnedDesignSystemRef(
          data as unknown as Record<string, unknown>,
          get().designSystems,
          get().designSystemPicker,
        ),
      };
      let res: GenerateResp;
      const desktop = window.designDNA;
      if (!desktop) {
        res = await scope.wait(api<GenerateResp>("/api/generate", request));
      } else {
        // тот же transport-контракт, что у Generator: сервер готовит промпты,
        // LLM отвечает через подключённый аккаунт, сервер валидирует и чинит
        const prepared = await scope.wait(api<GenerateResp>("/api/generate", { ...request, prepareOnly: true }));
        if (!prepared.prompts?.length) throw new Error("Не удалось подготовить запросы Derive");
        const rawOutputs: string[] = [];
        for (const p of prepared.prompts) {
          const answer = await scope.wait(desktop.providers.chatRequest({
            ...chatRoute(provider, effort),
            messages: p.messages,
          }));
          rawOutputs.push(answer.content);
        }
        res = await scope.wait(api<GenerateResp>("/api/generate", { ...request, rawOutputs, preparedContextId: prepared.preparedContextId }));
      }
      const variants = Array.isArray(res.variants) ? res.variants : [];
      if (scope.owns()) get().setNodeData(id, { variants, active: 0 });
      if (scope.owns()) get().setStatus(id, `Готово: вариантов ${variants.length}`, "ok");
      if (scope.owns()) get().propagate(id);
    } catch (e) {
      if (!scope.owns()) return;
      const msg = e instanceof Error ? e.message : String(e);
      if (scope.owns()) get().setStatus(id, "Ошибка: " + msg, "err");
      toast("Derive: " + msg, "error");
    } finally {
      if (scope.owns()) get().setBusy(id, false);
    }
  },

  /* Reskin: входы ir/tokens тянутся
   * проводами (pull-модель); payload {ir, prompt, tokens?, mask}; пустая маска
   * не запускается (бэкенд вернул бы IR без изменений). Ответ: {ir, log} —
   * log (журнал merge-back) показывается свёрнутым блоком в ноде. */
  runReskin: async (id) => {
    flushAllNodeText();
    const scope = captureNodeScope(get, id);
    watchNodeInputs(scope, get, id, ["prompt", "mask", "provider", "effort", "designSystem"]);
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "reskin" || st.busy[id]) return;
    const data = n.data as ReskinNodeData;
    if (!Object.values(data.mask).some(Boolean)) {
      if (scope.owns()) get().setStatus(id, "Пустая маска: отметьте, что разрешено менять", "err");
      return;
    }
    const ir = pullInput(st.nodes, st.edges, n, "ir") as IRObject | null;
    if (!ir) {
      if (scope.owns()) get().setStatus(id, "Подключите IR ко входу (например, из Source Import)", "err");
      return;
    }
    const tokensRaw = pullInput(st.nodes, st.edges, n, "tokens");
    if (scope.owns()) get().setStatus(id, "Рестайл: LLM + merge-back… 20–120 сек");
    if (scope.owns()) get().setBusy(id, true);
    try {
      const payload: Record<string, unknown> = {
        ir,
        prompt: data.prompt || "",
        provider: nodeProvider(data.provider),
        effort: ["medium", "high", "max"].includes(data.effort) ? data.effort : "medium",
        mask: data.mask,
        designSystem: pinnedDesignSystemRef(
          data as unknown as Record<string, unknown>,
          get().designSystems,
          get().designSystemPicker,
        ),
      };
      if (tokensRaw && typeof tokensRaw === "object") payload.tokens = tokensRaw;
      let res: ReskinResp;
      const desktop = window.designDNA;
      if (!desktop) {
        res = await scope.wait(api<ReskinResp>("/api/reskin", payload));
      } else {
        // desktop: сервер готовит reskin-промпт, аккаунт отвечает, сервер
        // делает merge-back/валидацию — креденшелы не покидают main-процесс
        const prepared = await scope.wait(api<{ prompts: Array<{ messages: import("./api").ApiChatMessage[] }> }>(
          "/api/reskin", { ...payload, prepareOnly: true },
        ));
        if (!prepared.prompts?.length) throw new Error("Не удалось подготовить промпт рестайла");
        const effort = ["medium", "high", "max"].includes(data.effort) ? data.effort : "medium";
        const answer = await scope.wait(desktop.providers.chatRequest({
          ...chatRoute(nodeProvider(data.provider), effort),
          messages: prepared.prompts[0].messages,
        }));
        res = await scope.wait(api<ReskinResp>("/api/reskin", { ...payload, rawOutput: answer.content }));
      }
      const log = Array.isArray(res.log) ? res.log : [];
      if (scope.owns()) get().setNodeData(id, { ir: res.ir || null, log });
      if (scope.owns()) get().setStatus(id, `Готово · журнал merge-back: ${log.length}`, "ok");
      if (scope.owns()) get().propagate(id);
    } catch (e) {
      if (!scope.owns()) return;
      const msg = e instanceof Error ? e.message : String(e);
      if (scope.owns()) get().setStatus(id, "Ошибка: " + msg, "err");
      toast("Reskin: " + msg, "error");
    } finally {
      if (scope.owns()) get().setBusy(id, false);
    }
  },

  /* Raster generation and background removal share cancellation, blob loading,
   * validated output and history. Legacy SVG nodes keep their original route. */
  runImage: async (id) => {
    flushAllNodeText();
    const scope = captureNodeScope(get, id);
    flushNodeText(`image:${id}:prompt`);
    flushNodeText(`removebackground:${id}:prompt`);
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || (n.type !== "image" && n.type !== "removebackground") || st.busy[id]) return;
    const removeBackground = n.type === "removebackground";
    const data = n.data;
    const imageOptions = n.data as ImageNodeData;
    const cutoutOptions = n.data as RemoveBackgroundNodeData;
    const wired = pullInput(st.nodes, st.edges, n, "prompt");
    const prompt = removeBackground ? (data.prompt.trim() || "Выделите главный объект полностью")
      : String((typeof wired === "string" && wired.trim()) || data.prompt || "").trim();
    if (!prompt) {
      if (scope.owns()) get().setStatus(id, "Опишите изображение в инспекторе или подключите ноду Промпт", "err");
      return;
    }
    const refRaw = pullInput(st.nodes, st.edges, n, removeBackground ? "image" : "reference")
      || (removeBackground ? cutoutOptions.image : null);
    if (removeBackground && !isImageSource(refRaw)) {
      if (scope.owns()) get().setStatus(id, "Подключите изображение или загрузите файл", "err");
      return;
    }
    const raster = removeBackground || imageOptions.engine === "raster";
    const signal = beginRunAbort(id);
    const requestId = `image-${id}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    const desktop = window.designDNA;
    const cancel = () => { void desktop?.providers?.cancel(requestId).catch(() => {}); };
    signal.addEventListener("abort", cancel, { once: true });
    const ownsRun = () => get().activePageId === st.activePageId && runAborts.get(id)?.signal === signal
      && get().nodes.some(node => node.id === n.id && node.type === n.type);
    const stillCurrent = () => {
      const current = get();
      const target = current.nodes.find(node => node.id === n.id);
      return ownsRun() && !signal.aborted && target?.data === data
        && pullInput(current.nodes, current.edges, target, "prompt") === wired
        && (pullInput(current.nodes, current.edges, target, removeBackground ? "image" : "reference")
          || (removeBackground ? cutoutOptions.image : null)) === refRaw;
    };
    if (scope.owns()) get().setStatus(id, removeBackground ? "GPT Image · удаляем фон…" : raster ? "GPT Image · создаём изображение…" : "SVG · создаём изображение…");
    if (scope.owns()) get().setBusy(id, true);
    try {
      const referenceImage = isImageSource(refRaw) ? await scope.wait(imageDataUrl(refRaw)) : null;
      if (!stillCurrent()) return;
      type ImageResp = Omit<ImageVariant, "createdAt">;
      let res: ImageResp;
      if (raster) {
        if (!desktop?.providers?.imageRequest) throw new Error("Для GPT Image нужен обновлённый десктоп и подключённый аккаунт Codex");
        const generated = await scope.wait(desktop.providers.imageRequest({ id: requestId, referenceImage, removeBackground,
          ...(!removeBackground && imageOptions.rasterModel ? { model: imageOptions.rasterModel } : {}),
          prompt: removeBackground ? prompt : `${prompt}\nRequested canvas: ${imageOptions.width}×${imageOptions.height}. ${imageOptions.tileable ? "Make a seamless tileable texture, opposite edges must match." : ""}` }));
        if (!stillCurrent()) return;
        res = removeBackground
          ? await scope.wait(api<ImageResp>("/api/image/remove-background", { image: referenceImage, mask: generated.image }, { signal, runId: requestId }))
          : await scope.wait(api<ImageResp>("/api/image/convert", { image: generated.image,
              outputFormat: imageOptions.outputFormat || "png" }, { signal, runId: requestId }));
      } else {
        const provider = nodeProvider(imageOptions.provider);
        const payload = { prompt, style: imageOptions.style || "vector", width: imageOptions.width, height: imageOptions.height,
          tileable: !!imageOptions.tileable, model: imageOptions.model || null, provider, effort: nodeEffort(imageOptions.effort), referenceImage };
        if (!desktop) {
          res = await scope.wait(api<ImageResp>("/api/image/generate", payload, { signal }));
        } else {
          const prepared = await scope.wait(api<{ prompts: Array<{ messages: import("./api").ApiChatMessage[] }> }>(
            "/api/image/generate", { ...payload, prepareOnly: true }, { signal, runId: requestId }));
          if (!stillCurrent()) return;
          if (!prepared.prompts?.length) throw new Error("Не удалось подготовить промпт изображения");
          const answer = await scope.wait(desktop.providers.chatRequest({ ...chatRoute(provider, payload.effort), id: requestId,
            ...(imageOptions.model ? { model: imageOptions.model } : {}),
            profile: "graphics", messages: prepared.prompts[0].messages }));
          if (!stillCurrent()) return;
          res = await scope.wait(api<ImageResp>("/api/image/generate", { ...payload, rawOutput: answer.content }, { signal, runId: requestId }));
        }
        if (!stillCurrent()) return;
        if (imageOptions.outputFormat === "jpeg") {
          const converted = await scope.wait(api<ImageResp>("/api/image/convert", { image: res.png, outputFormat: "jpeg" }, { signal, runId: requestId }));
          res = { ...res, ...converted };
        }
      }
      if (!stillCurrent()) return;
      const variant = { ...res, createdAt: Date.now() };
      const variants = [...(data.variants || []), variant].slice(-4);
      if (scope.owns()) get().setNodeData(id, { variants, active: variants.length - 1 });
      if (scope.owns()) get().setStatus(id, `Готово · ${res.width}×${res.height}${removeBackground ? " · прозрачный PNG" : ""}`, "ok");
      if (scope.owns()) get().propagate(id);
    } catch (e) {
      if (!scope.owns()) return;
      if (!ownsRun()) return;
      if (signal.aborted) { if (scope.owns()) get().setStatus(id, "Отменено", "err"); return; }
      const msg = friendlyProviderError(e);
      if (scope.owns()) get().setStatus(id, "Ошибка: " + msg, "err");
      toast("Изображение: " + msg, "error");
    } finally {
      if (ownsRun()) if (scope.owns()) get().setBusy(id, false);
      signal.removeEventListener("abort", cancel);
      endRunAbort(id, signal);
    }
  },

  /* Quality Pass: FastAPI prepares and validates every step. In desktop mode
   * judge/repair/rejudge run through whichever account is explicitly connected;
   * standalone web keeps the server-side provider compatibility path. */
  runQualityPass: async (id) => {
    flushAllNodeText();
    const scope = captureNodeScope(get, id);
    watchNodeInputs(scope, get, id, ["brief", "minScore", "repair", "provider", "ir"]);
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "qualitypass" || st.busy[id]) return;
    const data = n.data as QualityPassNodeData;
    const ir = (pullInput(st.nodes, st.edges, n, "ir") || data.ir) as IRObject | null;
    if (!ir) {
      if (scope.owns()) get().setStatus(id, "Подключите IR ко входу", "err");
      return;
    }
    if (scope.owns()) get().setStatus(id, "Quality Pass: judge + проверка правил… 30–120 сек");
    const signal = beginRunAbort(id);
    if (scope.owns()) get().setBusy(id, true);
    if (scope.owns()) get().setProgress(id, { expectedMs: 60_000, label: "Quality Pass", stage: "Судья оценивает" });
    const runId = newRunId();
    const stopPoll = window.designDNA ? () => {} : watchRunStages(id, runId, 60_000, "Quality Pass");
    try {
      // Общий цикл с генератором: судья/починка идут выбранным на ноде
      // провайдером (раньше нода была прибита к Sol).
      const provider = nodeProvider(data.provider);
      const res = await scope.wait(qualityPassCycle(ir, data.brief, provider, "high",
        (stage) => {
          if (scope.owns()) get().setStatus(id, `Quality Pass: ${stage} через подключённый аккаунт…`);
          if (scope.owns()) get().setProgress(id, { expectedMs: 60_000, label: "Quality Pass", stage });
        },
        { minScore: data.minScore, repair: data.repair, signal, runId }));
      const score = Number(res.scorecard?.score ?? 0);
      const passed = Boolean(res.passed);
      const repairNote = res.repair?.applied ? " · repair применён" : "";
      if (scope.owns()) get().setNodeData(id, { ir: res.ir || ir, result: res });
      if (scope.owns()) get().setStatus(id, `${passed ? "Готово" : "Нужна проверка"}: ${score}/100${repairNote}`, passed ? "ok" : "err");
      if (scope.owns()) get().propagate(id);
    } catch (e) {
      if (!scope.owns()) return;
      if (isAbortError(e) || signal.aborted) {
        if (scope.owns()) get().setStatus(id, "Отменено", "err");
      } else {
        const msg = e instanceof Error ? e.message : String(e);
        if (scope.owns()) get().setStatus(id, "Ошибка: " + msg, "err");
        toast("Quality Pass: " + msg, "error");
      }
    } finally {
      stopPoll();
      endRunAbort(id, signal);
      if (scope.owns()) get().setProgress(id, null);
      if (scope.owns()) get().setBusy(id, false);
    }
  },

  runRecorder: async (id) => {
    flushAllNodeText();
    const scope = captureNodeScope(get, id);
    watchNodeInputs(scope, get, id, ["ir", "draftScenes", "draftEvents"]);
    const st = get();
    const n = st.nodes.find((node) => Number(node.id) === id);
    if (!n || n.type !== "recorder" || st.busy[id]) return;
    const data = n.data as RecorderNodeData;
    const baseIr = (pullInput(st.nodes, st.edges, n, "ir") || data.ir) as IRObject | null;
    if (!baseIr) {
      if (scope.owns()) get().setStatus(id, "Connect Design IR before recording", "err");
      return;
    }
    if (scope.owns()) get().setBusy(id, true);
    if (scope.owns()) get().setStatus(id, "Sanitizing Interaction IR...");
    try {
      const response = await scope.wait(api<{ interaction?: IRObject }>("/api/interaction/build", {
        base_ir: baseIr,
        source: { kind: "design-ir", url: "" },
        scenes: data.draftScenes,
        events: data.draftEvents,
        variables: {},
      }));
      const interaction = response.interaction || null;
      if (scope.owns()) get().setNodeData(id, { ir: deepClone(baseIr), interaction, recording: false });
      const report = interaction?.privacyReport as Record<string, unknown> | undefined;
      if (scope.owns()) get().setStatus(id, `Interaction IR ready · ${data.draftEvents.length} events · ${Number(report?.sanitizedCount || 0)} redactions`, "ok");
      if (scope.owns()) get().propagate(id);
    } catch (error) {
      if (!scope.owns()) return;
      const message = error instanceof Error ? error.message : String(error);
      if (scope.owns()) get().setStatus(id, "Recorder: " + message, "err");
      toast("Recorder: " + message, "error");
    } finally {
      if (scope.owns()) get().setBusy(id, false);
    }
  },

  runLiveRecorder: async (id, actions) => {
    flushAllNodeText();
    const scope = captureNodeScope(get, id);
    watchNodeInputs(scope, get, id, ["ir", "liveUrl", "mine", "liveViewport"]);
    const st = get();
    const n = st.nodes.find((node) => Number(node.id) === id);
    if (!n || n.type !== "recorder" || st.busy[id]) return false;
    const data = n.data as RecorderNodeData;
    const baseIr = (pullInput(st.nodes, st.edges, n, "ir") || data.ir) as IRObject | null;
    if (!baseIr || !data.liveUrl.trim() || !data.mine || !actions.length) {
      if (scope.owns()) get().setStatus(id, "Live capture needs Design IR, URL, ownership confirmation and actions", "err");
      return false;
    }
    if (scope.owns()) get().setBusy(id, true);
    if (scope.owns()) get().setStatus(id, `Replaying ${actions.length} actions in Chromium...`);
    try {
      const response = await scope.wait(api<{ interaction?: IRObject }>("/api/interaction/capture", {
        base_ir: baseIr,
        url: data.liveUrl.trim(),
        mine: data.mine,
        viewport: data.liveViewport || "desktop",
        actions,
      }));
      const interaction = response.interaction || null;
      if (scope.owns()) get().setNodeData(id, { ir: deepClone(baseIr), interaction, recording: false });
      const report = interaction?.privacyReport as Record<string, unknown> | undefined;
      if (scope.owns()) get().setStatus(id, `Live Interaction IR ready · ${actions.length} actions · ${Number(report?.sanitizedCount || 0)} redactions`, "ok");
      if (scope.owns()) get().propagate(id);
      return true;
    } catch (error) {
      if (!scope.owns()) return false;
      const message = error instanceof Error ? error.message : String(error);
      if (scope.owns()) get().setStatus(id, "Live capture: " + message, "err");
      toast("Live capture: " + message, "error");
      return false;
    } finally {
      if (scope.owns()) get().setBusy(id, false);
    }
  },

  runMotion: async (id) => {
    flushAllNodeText();
    const scope = captureNodeScope(get, id);
    watchNodeInputs(scope, get, id, ["ir", "interaction", "scenes", "composition", "sceneSettings", "renderSettings"]);
    const st = get();
    const n = st.nodes.find((node) => Number(node.id) === id);
    if (!n || n.type !== "motion" || st.busy[id]) return;
    const data = n.data as MotionNodeData;
    const designIr = (pullInput(st.nodes, st.edges, n, "ir") || data.ir) as IRObject | null;
    let interaction = (pullInput(st.nodes, st.edges, n, "interaction") || data.interaction) as IRObject | null;
    if (!designIr) {
      if (scope.owns()) get().setStatus(id, "Подключите Design IR", "err");
      return;
    }
    const sourceRevision = get().getNodeIrRevision(id);
    const stillCurrent = () => get().activePageId === st.activePageId && get().getNodeIrRevision(id) === sourceRevision;
    if (scope.owns()) get().setBusy(id, true);
    if (scope.owns()) get().setStatus(id, "Building editable motion timeline...");
    try {
      if (!interaction) {
        // Recorder исключён из хендоффа: сцены композиции авторятся прямо в
        // Motion, а Interaction IR нода строит сама из Design IR.
        const draftScenes = Array.isArray(data.scenes) && data.scenes.length
          ? data.scenes
          : [{ id: "scene-0", viewport: "desktop", patch: [] }];
        const built = await scope.wait(api<{ interaction?: IRObject }>("/api/interaction/build", {
          base_ir: designIr,
          source: { kind: "design-ir", url: "" },
          scenes: draftScenes,
          events: [],
          variables: {},
        }));
        interaction = built.interaction || null;
        if (!interaction) throw new Error("Не удалось построить Interaction IR из Design IR");
      }
      const response = await scope.wait(api<{ motion?: IRObject; sceneIrs?: MotionNodeData["sceneIrs"] }>("/api/motion/build", {
        base_ir: designIr,
        interaction,
        composition: data.composition,
        scene_settings: data.sceneSettings,
        render_settings: data.renderSettings || { format: "mp4", quality: "high" },
      }));
      if (!stillCurrent()) return;
      const motion = response.motion || null;
      if (!motion || !Array.isArray(motion.scenes) || !motion.scenes.length) throw new Error("Сервер вернул пустое движение");
      const sceneIrs = response.sceneIrs || [];
      const scenes = Array.isArray(motion?.scenes) ? motion.scenes : [];
      if (scope.owns()) get().setNodeData(id, {
        ir: deepClone(designIr), interaction: deepClone(interaction), motion, sceneIrs, renderJob: null,
        selectedScene: Math.min(data.selectedScene || 0, Math.max(0, scenes.length - 1)),
      });
      const composition = motion?.composition as Record<string, unknown> | undefined;
      if (scope.owns()) get().setStatus(id, `Motion IR ready · ${scenes.length} scenes · ${(Number(composition?.duration || 0) / 1000).toFixed(1)}s`, "ok");
      if (scope.owns()) get().propagate(id);
    } catch (error) {
      if (!scope.owns()) return;
      if (!stillCurrent()) return;
      const message = error instanceof Error ? error.message : String(error);
      if (scope.owns()) get().setStatus(id, "Motion: " + message, "err");
      toast("Motion: " + message, "error");
    } finally {
      if (get().activePageId === st.activePageId) if (scope.owns()) get().setBusy(id, false);
    }
  },

  planMotionDesign: async (id) => {
    flushAllNodeText();
    const scope = captureNodeScope(get, id);
    watchNodeInputs(scope, get, id, ["prompt", "inputMode", "planner", "effort", "settings", "sourceVideo", "sourceMotion", "sourceTimeline"]);
    const st = get();
    const n = st.nodes.find((node) => Number(node.id) === id);
    if (!n || n.type !== "motiondesign" || st.busy[id]) return null;
    const data = n.data as MotionDesignNodeData;
    const connectedPrompt = String(pullInput(st.nodes, st.edges, n, "prompt") || "").trim();
    const brief = connectedPrompt || String(data.prompt || "").trim();
    const connectedMotion = pullInput(st.nodes, st.edges, n, "motion") as IRObject | null;
    const connectedTimeline = pullInput(st.nodes, st.edges, n, "timeline") as IRObject | null;
    const connectedVideo = pullInput(st.nodes, st.edges, n, "video") as VideoArtifact | null;
    const sourceMotion = connectedMotion || data.sourceMotion;
    const sourceTimeline = connectedTimeline || data.sourceTimeline;
    const sourceVideo = connectedVideo || data.sourceVideo;
    const useReference = data.inputMode !== "prompt";

    if (data.inputMode === "reference" && !sourceVideo) {
      if (scope.owns()) get().setStatus(id, "Режим reference требует готовое видео из Motion/Video Editor", "err");
      return null;
    }
    if (!brief && !sourceVideo && !sourceMotion && !sourceTimeline) {
      if (scope.owns()) get().setStatus(id, "Введите prompt или подключите Motion/Timeline/video", "err");
      return null;
    }

    if (scope.owns()) get().setBusy(id, true);
    if (scope.owns()) get().setStatus(id, data.planner === "direct" ? "Собираем Seedance prompt…" : `Планировщик ${PROVIDER_LABELS[data.planner]} готовит prompt…`);
    try {
      let planned = directMotionDesignPrompt(brief, useReference ? sourceVideo : null);
      if (!planned && (sourceMotion || sourceTimeline)) {
        planned = "Create a polished motion-design video that follows the supplied timing, scene order, keyframes, and composition metadata. Preserve UI legibility and visual identity; avoid invented text or layout drift.";
      }
      if (data.planner !== "direct") {
        const desktop = window.designDNA;
        if (!desktop) throw new Error("GPT/Claude planner доступен в desktop-приложении");
        const digest = motionDesignDigest(
          useReference ? sourceMotion : null,
          useReference ? sourceTimeline : null,
          useReference ? sourceVideo : null,
        );
        const answer = await scope.wait(desktop.providers.chatRequest({
          ...chatRoute(data.planner, data.effort),
          messages: [
            {
              role: "system",
              content: [
                "You are a prompt planner for ByteDance Seedance 2.5 video generation and editing.",
                "Return only one production-ready English prompt, no Markdown, maximum 1400 characters.",
                "You receive only compact timeline metadata, never the video pixels; do not claim that you watched the clip.",
                "When a source video exists, preserve its identity, UI text legibility, composition and motion continuity.",
                "Describe requested changes, camera, subject motion, timing, continuity, audio intent and explicit negative constraints.",
              ].join(" "),
            },
            {
              role: "user",
              content: JSON.stringify({
                brief: planned || brief,
                inputMode: data.inputMode,
                target: data.settings,
                source: digest,
              }),
            },
          ],
          maxOutputTokens: 700,
        }));
        planned = String(answer.content || "")
          .trim()
          .replace(/^```(?:text)?\s*/i, "")
          .replace(/\s*```$/, "")
          .replace(/^['\"]|['\"]$/g, "")
          .trim();
      }
      if (!planned) throw new Error("Планировщик вернул пустой prompt");
      if (planned.length > 5_000) planned = planned.slice(0, 5_000);
      if (scope.owns()) get().setNodeData(id, {
        plannedPrompt: planned,
        sourceMotion: sourceMotion ? deepClone(sourceMotion) : null,
        sourceTimeline: sourceTimeline ? deepClone(sourceTimeline) : null,
        sourceVideo: sourceVideo ? deepClone(sourceVideo) : null,
      });
      if (scope.owns()) get().setStatus(id, `${data.planner === "direct" ? "Direct" : PROVIDER_LABELS[data.planner]} prompt готов · ${planned.length} chars`, "ok");
      return planned;
    } catch (error) {
      if (!scope.owns()) return null;
      const message = friendlyProviderError(error);
      if (scope.owns()) get().setStatus(id, "Motion Design planner: " + message, "err");
      toast("Motion Design planner: " + message, "error");
      return null;
    } finally {
      if (scope.owns()) get().setBusy(id, false);
    }
  },

  runMotionDesign: async (id, confirmedPaid) => {
    flushAllNodeText();
    const scope = captureNodeScope(get, id);
    if (!confirmedPaid) {
      if (scope.owns()) get().setStatus(id, "Подтвердите платный запрос Seedance 2.5", "err");
      return;
    }
    let st = get();
    let n = st.nodes.find((node) => Number(node.id) === id);
    if (!n || n.type !== "motiondesign" || st.busy[id]) return;
    let data = n.data as MotionDesignNodeData;
    let planned = String(data.plannedPrompt || "").trim();
    if (!planned) {
      try { planned = String(await scope.wait(get().planMotionDesign(id)) || "").trim(); }
      catch (error) { if (isAbortError(error)) return; throw error; }
      if (!planned) return;
      st = get();
      n = st.nodes.find((node) => Number(node.id) === id);
      if (!n || n.type !== "motiondesign") return;
      data = n.data as MotionDesignNodeData;
    }

    const connectedVideo = pullInput(st.nodes, st.edges, n, "video") as VideoArtifact | null;
    const sourceVideo = connectedVideo || data.sourceVideo;
    if (data.inputMode === "reference" && !sourceVideo) {
      if (scope.owns()) get().setStatus(id, "Режим reference требует готовое видео", "err");
      return;
    }

    if (scope.owns()) get().setBusy(id, true);
    try {
      const config = await scope.wait(apiGet<{ configured?: boolean; model?: string }>("/api/video/seedance/config"));
      if (!config.configured) throw new Error("OpenRouter key не подключён. Откройте Agents → Connections.");
      const references: Array<Record<string, unknown>> = [];
      if (sourceVideo && data.inputMode !== "prompt") {
        if (scope.owns()) get().setStatus(id, "Подготавливаем готовое видео как Seedance reference…");
        references.push({
          type: "video_url",
          video_url: { url: await scope.wait(videoReferenceUrl(sourceVideo)) },
        });
      }
      if (scope.owns()) get().setStatus(id, `Отправляем подтверждённый запрос в ${config.model || "Seedance 2.5"}…`);
      const response = await scope.wait(api<SeedanceVideoJob>("/api/video/seedance/submit", {
        prompt: planned,
        duration: data.settings.duration,
        aspect_ratio: data.settings.aspectRatio,
        resolution: data.settings.resolution,
        generate_audio: data.settings.generateAudio,
        seed: data.settings.seed,
        input_references: references,
        confirmed_paid: true,
      }));
      const job = { ...response, model: "bytedance/seedance-2.5" as const };
      if (scope.owns()) get().setNodeData(id, { job, video: null, sourceVideo: sourceVideo ? deepClone(sourceVideo) : null });
      if (scope.owns()) get().setStatus(id, `Seedance job ${job.id} · ${job.status}`, "ok");
      const oldTimer = motionDesignPollTimers.get(id);
      if (oldTimer) clearTimeout(oldTimer);
      scheduleMotionDesignPoll(id, () => void get().refreshMotionDesign(id));
    } catch (error) {
      if (!scope.owns()) return;
      const message = error instanceof Error ? error.message : String(error);
      if (scope.owns()) get().setStatus(id, "Seedance: " + message, "err");
      toast("Seedance: " + message, "error");
    } finally {
      if (scope.owns()) get().setBusy(id, false);
    }
  },

  refreshMotionDesign: async (id) => {
    flushAllNodeText();
    const scope = captureNodeScope(get, id);
    const st = get();
    const n = st.nodes.find((node) => Number(node.id) === id);
    if (!n || n.type !== "motiondesign" || st.busy[id]) return;
    const data = n.data as MotionDesignNodeData;
    if (!data.job?.id || (MOTION_DESIGN_TERMINAL.has(data.job.status) && data.video)) return;
    if (scope.owns()) get().setBusy(id, true);
    try {
      const response = await scope.wait(apiGet<SeedanceVideoJob>(`/api/video/seedance/${encodeURIComponent(data.job.id)}`));
      const job = { ...data.job, ...response, id: data.job.id, model: "bytedance/seedance-2.5" as const };
      if (job.status === "completed") {
        const cost = Number(job.usage?.cost);
        const video: VideoArtifact = {
          version: "video-artifact/1.0",
          origin: "motion-design",
          jobId: job.id,
          downloadUrl: `/api/video/seedance/${encodeURIComponent(job.id)}/content`,
          filename: `seedance-${job.id.slice(0, 12)}.mp4`,
          mime: "video/mp4",
          parameters: {
            model: job.model,
            planner: data.planner,
            inputMode: data.inputMode,
            settings: data.settings,
            sourceOrigin: data.sourceVideo?.origin || null,
          },
        };
        if (scope.owns()) get().setNodeData(id, { job, video });
        if (scope.owns()) get().setStatus(id, `Seedance video готов${Number.isFinite(cost) ? ` · cost ${cost}` : ""}`, "ok");
        if (scope.owns()) get().propagate(id);
      } else if (MOTION_DESIGN_TERMINAL.has(job.status)) {
        if (scope.owns()) get().setNodeData(id, { job });
        if (scope.owns()) get().setStatus(id, `Seedance ${job.status}: ${String(job.error || "job завершён без видео")}`, "err");
      } else {
        if (scope.owns()) get().setNodeData(id, { job });
        if (scope.owns()) get().setStatus(id, `Seedance job ${job.id} · ${job.status}`);
        const oldTimer = motionDesignPollTimers.get(id);
        if (oldTimer) clearTimeout(oldTimer);
        scheduleMotionDesignPoll(id, () => void get().refreshMotionDesign(id));
      }
    } catch (error) {
      if (!scope.owns()) return;
      // A failed poll must never resubmit the paid generation. Keep the job id
      // and retry status later, as recommended by OpenRouter's async contract.
      const message = error instanceof Error ? error.message : String(error);
      if (scope.owns()) get().setStatus(id, `Seedance status: ${message} · job сохранён`, "err");
      const oldTimer = motionDesignPollTimers.get(id);
      if (oldTimer) clearTimeout(oldTimer);
      scheduleMotionDesignPoll(id, () => void get().refreshMotionDesign(id));
    } finally {
      if (scope.owns()) get().setBusy(id, false);
    }
  },

  runTimeline: async (id) => {
    flushAllNodeText();
    const scope = captureNodeScope(get, id);
    watchNodeInputs(scope, get, id, ["ir", "sourcePages", "inputs", "settings"]);
    const st = get();
    const n = st.nodes.find((node) => Number(node.id) === id);
    if (!n || n.type !== "timeline" || st.busy[id]) return;
    const data = n.data as TimelineNodeData;
    const sourcePages = videoPages(st.nodes, st.edges, n, true);
    const designIr = (pullInput(st.nodes, st.edges, n, "ir") || data.ir) as IRObject | null;
    if (!designIr) {
      if (scope.owns()) get().setStatus(id, "Подключите Design IR (страница или компонент)", "err");
      return;
    }
    if (sourcePages.length !== (data.inputs || ["ir"]).length) {
      if (scope.owns()) get().setStatus(id, "Подключите все страницы или удалите пустой вход", "err");
      return;
    }
    const sourceRevision = get().getNodeIrRevision(id);
    const stillCurrent = () => get().activePageId === st.activePageId && get().getNodeIrRevision(id) === sourceRevision;
    if (scope.owns()) get().setBusy(id, true);
    if (scope.owns()) get().setStatus(id, "Сборка таймлайна: слои и группы из компонентов...");
    try {
      const response = await scope.wait(api<{ timeline?: IRObject }>("/api/timeline/build", {
        ir: designIr,
        settings: data.settings,
        pages: sourcePages,
      }));
      if (!stillCurrent()) return;
      const timeline = response.timeline || null;
      if (!timeline || !Array.isArray(timeline.layers) || !timeline.layers.length) throw new Error("Сервер вернул пустой таймлайн");
      if (scope.owns()) get().setNodeData(id, { ir: deepClone(designIr), sourcePages: deepClone(sourcePages), timeline, renderJob: null });
      const layers = Array.isArray((timeline as { layers?: unknown[] } | null)?.layers)
        ? ((timeline as { layers: unknown[] }).layers).length : 0;
      const composition = (timeline as { composition?: { duration?: number } } | null)?.composition;
      if (scope.owns()) get().setStatus(id, `Таймлайн готов · ${layers} слоёв · ${((Number(composition?.duration || 0)) / 1000).toFixed(1)}s`, "ok");
      if (scope.owns()) get().propagate(id);
    } catch (error) {
      if (!scope.owns()) return;
      if (!stillCurrent()) return;
      const message = error instanceof Error ? error.message : String(error);
      if (scope.owns()) get().setStatus(id, "Timeline: " + message, "err");
      toast("Timeline: " + message, "error");
    } finally {
      if (get().activePageId === st.activePageId) if (scope.owns()) get().setBusy(id, false);
    }
  },

  runPageBridge: (id) => {
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n || n.type !== "pagebridge") return;
    const data = n.data as PageBridgeNodeData;
    const channel = (data.channel || "shared-component").trim() || "shared-component";
    if (data.mode === "send") {
      const ir = pullInput(st.nodes, st.edges, n, "ir") as IRObject | null;
      if (!ir) {
        get().setStatus(id, "Подключите компонент к входу", "err");
        return;
      }
      const cloned = deepClone(ir);
      set((state) => ({
        channels: { ...state.channels, [channel]: cloned },
        nodes: state.nodes.map((node) =>
          node.id === String(id)
            ? ({ ...node, data: { ...node.data, channel, ir: cloned } } as FlowNode)
            : node,
        ),
      }));
      get().setStatus(id, `Передано в канал: ${channel}`, "ok");
      return;
    }
    const ir = st.channels[channel] || null;
    if (!ir) {
      get().setNodeData(id, { channel, ir: null });
      get().setStatus(id, `Канал пустой: ${channel}`, "err");
      return;
    }
    get().setNodeData(id, { channel, ir: deepClone(ir) });
    get().setStatus(id, `Получено из канала: ${channel}`, "ok");
    get().propagate(id);
  },

  /* Зеркало sendToNode (nodes.js:522-545): создать ноду target справа от источника,
   * положить клон IR и соединить проводом ir->ir. */
  sendToNode: (id, targetType) => {
    const st = get();
    const n = st.nodes.find((x) => Number(x.id) === id);
    if (!n) return;
    const ir = outValue(n) as IRObject | null;
    if (!ir) {
      toast("Сначала запустите ноду и получите IR на выходе", "error");
      return;
    }
    const def = NODE_DEFS[n.type as NodeType];
    const target = get().addNode(targetType, n.position.x + (def ? def.w : 270) + 60, n.position.y);
    get().setNodeData(target.id, { ir: deepClone(ir) });
    if (targetType === "reference") get().setStatus(target.id, "IR получен от генератора", "ok");
    get().connect({ node: id, port: "ir" }, { node: target.id, port: targetType === "edit" ? "a" : "ir" });
    toast(`→ ${NODE_DEFS[targetType].title}`, "ok");
  },

  /* «+ вход» у mix: максимум 4, имя — первое свободное из a..d, вес 50 (nodes.js:403-412) */
  addVideoInput: (id) => {
    const node = get().nodes.find((n) => Number(n.id) === id);
    if (node?.type !== "timeline") return;
    const inputs = node.data.inputs || ["ir"];
    if (inputs.length >= 8) return;
    const name = Array.from({ length: 7 }, (_, i) => `page${i + 2}`).find((n) => !inputs.includes(n))!;
    recordGraphHistory();
    get().setNodeData(id, { inputs: [...inputs, name] });
  },
  removeVideoInput: (id, name) => {
    const node = get().nodes.find((n) => Number(n.id) === id);
    if (node?.type !== "timeline" || name === "ir") return;
    recordGraphHistory();
    get().setNodeData(id, { inputs: (node.data.inputs || ["ir"]).filter((n) => n !== name) });
    set((state) => ({ edges: state.edges.filter((e) => !(e.target === node.id && e.targetHandle === name)) }));
    get().refreshInputs(id);
  },
  addMixInput: (id) => {
    const sid = String(id);
    const n = get().nodes.find((x) => x.id === sid);
    if (!n || n.type !== "mix") return;
    const inputs = (n.data as MixNodeData).inputs;
    if (inputs.length >= 4) {
      toast("Максимум 4 входа", "error");
      return;
    }
    const name = ["a", "b", "c", "d"].find((c) => !inputs.includes(c));
    if (!name) return;
    set((state) => ({
      nodes: state.nodes.map((x) =>
        x.id === sid && x.type === "mix"
          ? ({
              ...x,
              data: {
                ...x.data,
                inputs: [...x.data.inputs, name],
                weights: { ...x.data.weights, [name]: 50 },
              },
            } as FlowNode)
          : x,
      ),
    }));
  },

  /* «✕» у входа mix: снять вход и его провода (nodes.js:800-808) */
  removeMixInput: (id, name) => {
    const sid = String(id);
    set((state) => {
      const nodes = state.nodes.map((x) => {
        if (x.id !== sid || x.type !== "mix") return x;
        const weights = { ...x.data.weights };
        delete weights[name];
        return {
          ...x,
          data: { ...x.data, inputs: x.data.inputs.filter((i) => i !== name), weights },
        } as FlowNode;
      });
      const edges = state.edges.filter((e) => !(e.target === sid && e.targetHandle === name));
      return { nodes, edges };
    });
  },

  /* Edit принимает компоненты напрямую: порядок входов становится порядком секций. */
  addEditInput: (id) => {
    const sid = String(id);
    const n = get().nodes.find((x) => x.id === sid);
    if (!n || n.type !== "edit") return;
    const inputs = (n.data as EditNodeData).inputs || ["ir"];
    const candidates = "abcdefghijkl".split("");
    if (inputs.length >= candidates.length) {
      toast("Максимум 12 компонентов", "error");
      return;
    }
    const name = candidates.find((candidate) => !inputs.includes(candidate));
    if (!name) return;
    set((state) => ({
      nodes: state.nodes.map((item) => item.id === sid && item.type === "edit"
        ? ({ ...item, data: { ...item.data, inputs: [...inputs, name] } } as FlowNode)
        : item),
    }));
  },

  removeEditInput: (id, name) => {
    const sid = String(id);
    const node = get().nodes.find((item) => item.id === sid);
    if (node?.type !== "edit" || !(node.data.inputs || ["ir"]).includes(name)) return;
    recordGraphHistory();
    set((state) => ({
      nodes: state.nodes.map((item) => {
        if (item.id !== sid || item.type !== "edit") return item;
        const inputs = (item.data.inputs || ["ir"]).filter((input) => input !== name);
        return { ...item, data: { ...item.data, inputs } } as FlowNode;
      }),
      edges: state.edges.filter((edge) => !(edge.target === sid && edge.targetHandle === name)),
    }));
    get().refreshEdit(id);
    get().propagate(id);
  },

  reorderEditInputs: (id, from, to) => {
    const sid = String(id);
    set((state) => ({
      nodes: state.nodes.map((item) => {
        if (item.id !== sid || item.type !== "edit") return item;
        const inputs = [...(item.data.inputs || ["ir"] )];
        if (from < 0 || from >= inputs.length || to < 0 || to >= inputs.length || from === to) return item;
        const [moved] = inputs.splice(from, 1);
        inputs.splice(to, 0, moved);
        return { ...item, data: { ...item.data, inputs } } as FlowNode;
      }),
    }));
    get().refreshEdit(id);
    get().propagate(id);
  },

  /* Page keeps existing port names stable when more source blocks are added. */
  addPageInput: (id) => {
    const sid = String(id);
    const n = get().nodes.find((x) => x.id === sid);
    if (!n || n.type !== "page") return;
    const inputs = (n.data as PageNodeData).inputs;
    if (inputs.length >= PAGE_INPUT_LIMIT) {
      toast(`Максимум ${PAGE_INPUT_LIMIT} блоков`, "error");
      return;
    }
    const name = PAGE_INPUT_NAMES.find((c) => !inputs.includes(c));
    if (!name) return;
    set((state) => ({
      nodes: state.nodes.map((x) =>
        x.id === sid && x.type === "page"
          ? ({ ...x, data: { ...x.data, inputs: [...x.data.inputs, name] } } as FlowNode)
          : x,
      ),
    }));
  },

  /* «✕» у входа Page: снять вход и его провода (паттерн removeMixInput) */
  removePageInput: (id, name) => {
    const sid = String(id);
    set((state) => {
      const nodes = state.nodes.map((x) => {
        if (x.id !== sid || x.type !== "page") return x;
        return {
          ...x,
          data: { ...x.data, inputs: x.data.inputs.filter((i) => i !== name) },
        } as FlowNode;
      });
      const edges = state.edges.filter((e) => !(e.target === sid && e.targetHandle === name));
      return { nodes, edges };
    });
  },

  /* drag-порядок блоков Page = порядок секций на странице */
  reorderPageInputs: (id, from, to) => {
    const sid = String(id);
    set((state) => ({
      nodes: state.nodes.map((x) => {
        if (x.id !== sid || x.type !== "page") return x;
        const inputs = [...x.data.inputs];
        if (from < 0 || from >= inputs.length || to < 0 || to >= inputs.length || from === to) return x;
        const [moved] = inputs.splice(from, 1);
        inputs.splice(to, 0, moved);
        return { ...x, data: { ...x.data, inputs } } as FlowNode;
      }),
    }));
  },
  /* Синхронизация из канваса Svelte Flow (bind:nodes/bind:edges — библиотека
   * сама применяет drag/select/remove к массивам). Удаления ведём через
   * deleteNode/deleteEdge — та же зачистка рёбер/статусов, что в legacy
   * onNodesChange; округление позиции на dragend — в moveNode из onnodedragstop. */
  syncFromCanvas: (nextNodes, nextEdges, pageId) => {
    if (pageId && pageId !== get().activePageId) return;
    const removedNodes = get().nodes.filter((n) => !nextNodes.some((x) => x.id === n.id));
    const removedEdges = get().edges.filter((e) => !nextEdges.some((x) => x.id === e.id));
    if (removedNodes.length || removedEdges.length) {
      // Del/Backspace на канвасе: одно нажатие — один шаг undo, сколько бы
      // нод и рёбер ни было выделено.
      recordGraphHistory();
      withGraphHistoryMuted(() => {
        for (const n of removedNodes) get().deleteNode(Number(n.id));
        for (const e of removedEdges) get().deleteEdge(e.id);
      });
      if (removedNodes.length) {
        toast(
          removedNodes.length === 1 ? "Нода удалена · Ctrl+Z вернёт" : `Удалено нод: ${removedNodes.length} · Ctrl+Z вернёт`,
          "info",
          { key: "graph-delete", action: { label: "Вернуть", run: () => void get().undoGraph() } },
        );
      }
    }
    const alive = new Set(get().edges.map((e) => e.id));
    const canonical = new Map(get().nodes.map((node) => [node.id, node]));
    set({ nodes: nextNodes.map((node) => ({ ...node, data: canonical.get(node.id)?.data ?? node.data }) as FlowNode),
      edges: nextEdges.filter((e) => alive.has(e.id)) });
  },

  /* Зеркало load() (nodes.js:1202-1219): полная замена графа из payload */
  loadGraph: (payload) => {
    leaveGraph();
    const graph = payloadToRf(payload);
    set((state) => ({
      ...graph,
      busy: {},
      pages: state.pages.map((page) =>
        page.id === state.activePageId ? { ...page, ...graph } : page,
      ),
      statuses: {},
      statusLog: {},
      progresses: {},
      graphHistory: EMPTY_GRAPH_HISTORY,
    }));
  },

  refreshDesignSystems: async () => {
    const list = await fetchDesignSystemsList();
    set({ designSystems: list });
  },

  /* Создание Design System из Source (ТЗ §7.1): нода рядом с Source,
   * сборка draft на сервере, карточка заполняется summary. */
  createDesignSystemFromSource: async (sourceId, options) => {
    const scope = captureNodeScope(get, sourceId);
    const st = get();
    const source = st.nodes.find((n) => Number(n.id) === Number(sourceId));
    if (!source || source.type !== "sourceimport") return null;
    const data = source.data as SourceImportNodeData;
    if (!data.blocks?.length) {
      if (scope.owns()) get().setStatus(sourceId, "Source не содержит блоков — сначала импорт", "err");
      return null;
    }
    const node = get().addNode("designsystem", source.position.x + 380, source.position.y);
    const dsId = Number(node.id);
    get().connect({ node: sourceId, port: "artifact" }, { node: dsId, port: "artifact" });
    if (scope.owns()) get().setStatus(dsId, "Собираю UI Kit из Source…");
    if (scope.owns()) get().setBusy(dsId, true);
    try {
      const resp = await scope.wait(fetch("/api/design-system/build", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sourceNodeId: String(sourceId), sourceUrl: data.url || "",
          blocks: data.blocks, tokens: data.tokens || {},
          sourceArtifact: data.sourceArtifact || null,
          name: options?.name || `UI Kit · ${data.url || "Source"}`,
          capturedAt: String((data as SourceImportNodeData & { capturedAt?: string }).capturedAt || ""),
        }),
      }));
      const result = await scope.wait(resp.json());
      if (!resp.ok || result.error || !result.document) {
        const detail = result.error || result.detail || `HTTP ${resp.status}`;
        const message = typeof detail === 'string' ? detail : String(detail.message || JSON.stringify(detail));
        if (scope.owns()) {
          get().setNodeData(dsId, { lastError: message });
          get().setStatus(dsId, "Не удалось собрать UI Kit: " + message, "err");
        }
        return null;
      }
      if (scope.owns()) get().setNodeData(dsId, {
        systemId: result.document.id, name: result.document.name, status: "draft",
        revision: 0, summary: result.summary, sourceNodeId: sourceId,
        defaultSet: false, sourceUpdate: false,
        document: result.document, autoPublish: true, _sourceFingerprint: sourceKitFingerprint(data),
        pipelineStatus: { build: { status: "success", message: "UI Kit собран из Source · компоненты доступны", updatedAt: new Date().toISOString() } },
      } as unknown as Partial<DesignSystemNodeData>);
      if (scope.owns()) {
        get().setBusy(dsId, false);
        get().setStatus(dsId, "UI Kit собран · откройте компоненты и стиль сайта", "ok");
        get().propagate(dsId);
      }
      return dsId;
    } catch (e) {
      if (!scope.owns()) return null;
      if (scope.owns()) get().setStatus(dsId, "Ошибка: " + (e instanceof Error ? e.message : String(e)), "err");
      return null;
    } finally {
      if (scope.owns()) get().setBusy(dsId, false);
    }
  },

  importDesignSystemDocument: async (nodeId, payload, fileName) => {
    const scope = captureNodeScope(get, nodeId);
    const node = get().nodes.find((n) => Number(n.id) === Number(nodeId));
    if (!node || node.type !== "designsystem") return false;
    if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
      if (scope.owns()) get().setStatus(nodeId, "Файл не JSON-объект: нужен документ DesignDNA, W3C/Tokens Studio JSON или карта токенов", "err");
      return false;
    }
    if (scope.owns()) get().setStatus(nodeId, `Загружаю дизайн-систему из ${fileName || "файла"}…`);
    if (scope.owns()) get().setBusy(nodeId, true);
    try {
      const resp = await scope.wait(fetch("/api/design-system/import", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payload, fileName, name: "" }),
      }));
      const result = await scope.wait(resp.json());
      if (!resp.ok || result.error || !result.document) throw new Error(result.error || `HTTP ${resp.status}`);
      if (scope.owns()) get().setNodeData(nodeId, {
        systemId: result.document.id, name: result.document.name, status: "draft",
        revision: 0, summary: result.summary, sourceNodeId: null,
        defaultSet: false, sourceUpdate: false, document: result.document, lastError: "",
      } as unknown as Partial<DesignSystemNodeData>);
      const count = Number(result.summary?.components || 0);
      const reviewMasters = Number(result.summary?.reviewMasters || 0);
      if (reviewMasters) {
        if (scope.owns()) get().setStatus(nodeId, `Черновик: ${reviewMasters} мастеров ждут ревью`, "ok");
      } else if ((get().nodes.find((x) => Number(x.id) === Number(nodeId))?.data as DesignSystemNodeData | undefined)?.autoPublish !== false) {
        await scope.wait(get().publishDesignSystem(nodeId));
      } else if (scope.owns()) get().setStatus(nodeId, `ДС загружена (${result.format}): ${count} компонентов`, "ok");
      await scope.wait(get().refreshDesignSystems());
      return true;
    } catch (e) {
      if (!scope.owns()) return false;
      const message = e instanceof Error ? e.message : String(e);
      if (scope.owns()) get().setNodeData(nodeId, { lastError: message });
      if (scope.owns()) get().setStatus(nodeId, "Ошибка импорта: " + message, "err");
      return false;
    } finally {
      if (scope.owns()) get().setBusy(nodeId, false);
    }
  },

  promoteVariantToDesignSystem: async (generatorId) => {
    const scope = captureNodeScope(get, generatorId);
    const source = get().nodes.find((node) => Number(node.id) === Number(generatorId));
    if (!source || source.type !== "generator") return null;
    const data = source.data as GeneratorNodeData;
    const active = data.variants?.[data.active];
    if (!active) {
      if (scope.owns()) get().setStatus(generatorId, "Нет активного варианта для закрепления", "err");
      return null;
    }
    if (scope.owns()) get().setBusy(generatorId, true);
    if (scope.owns()) get().setStatus(generatorId, "Закрепляю identity как Design System…");
    let createdId: number | null = null;
    try {
      const resp = await scope.wait(fetch("/api/design-system/identity/promote", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: `Style · ${String(data.ownPrompt || "Generator").trim().slice(0, 48)}`,
          sourceNodeId: String(generatorId), ir: active, visualReferences: [],
        }),
      }));
      const result = await scope.wait(resp.json());
      if (!resp.ok || result.error || !result.document) throw new Error(result.error || `HTTP ${resp.status}`);
      const node = get().addNode("designsystem", source.position.x + 380, source.position.y + 120);
      createdId = Number(node.id);
      if (scope.owns()) get().setNodeData(createdId, {
        systemId: result.document.id, name: result.document.name, status: "draft",
        revision: 0, summary: result.summary, sourceNodeId: generatorId,
        defaultSet: false, sourceUpdate: false, document: result.document,
      } as unknown as Partial<DesignSystemNodeData>);
      if (scope.owns()) get().setStatus(createdId, `Identity закреплена · ${result.summary.identitySignatures || 0} signatures · ${result.summary.identityTests || 0} tests`, "ok");
      const meta = (active as Record<string, any>).meta || {};
      await scope.wait(fetch("/api/project/taste/outcome", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: "promoted", payload: {
          systemId: result.document.id,
          compiledContextHash: meta.compiledContextHash || "",
          archetypeId: meta.archetypeId || "",
          ruleIds: (result.document.identity?.signatures || []).map((item: any) => item.id),
        }}),
      }));
      if (scope.owns()) get().setStatus(generatorId, "Стиль закреплён в черновик Design System", "ok");
      return createdId;
    } catch (error) {
      if (!scope.owns()) return null;
      if (createdId != null) get().deleteNode(createdId);
      const message = error instanceof Error ? error.message : String(error);
      if (scope.owns()) get().setStatus(generatorId, "Не удалось закрепить стиль: " + message, "err");
      toast("Design Identity: " + message, "error");
      return null;
    } finally {
      if (scope.owns()) get().setBusy(generatorId, false);
    }
  },

  recordVariantTaste: async (generatorId, kind) => {
    const source = get().nodes.find((node) => Number(node.id) === Number(generatorId));
    if (!source || source.type !== "generator") return false;
    const data = source.data as GeneratorNodeData;
    const active = data.variants?.[data.active] as Record<string, any> | undefined;
    if (!active) return false;
    const meta = active.meta || {};
    try {
      const resp = await fetch("/api/project/taste/outcome", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, payload: {
          systemId: meta.designSystemRef?.systemId || "",
          compiledContextHash: meta.compiledContextHash || "",
          archetypeId: meta.archetypeId || "",
          ruleIds: (meta.identityReport?.results || []).filter((item: any) => item.passed).map((item: any) => item.id),
        }}),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      get().setStatus(generatorId, kind === "accepted" ? "Вариант принят в Taste Memory" : "Вариант отклонён в Taste Memory", "ok");
      return true;
    } catch (error) {
      get().setStatus(generatorId, "Taste Memory: " + (error instanceof Error ? error.message : String(error)), "err");
      return false;
    }
  },

  setDesignSystemPicker: (patch) => {
    set((state) => ({ designSystemPicker: { ...state.designSystemPicker, ...patch } }));
  },

  publishDesignSystem: async (nodeId) => {
    const scope = captureNodeScope(get, nodeId);
    const n = get().nodes.find((x) => Number(x.id) === Number(nodeId));
    if (!n || n.type !== "designsystem") return false;
    const data = n.data as DesignSystemNodeData;
    if (scope.owns()) get().setBusy(nodeId, true);
    if (scope.owns()) get().setNodeData(nodeId, { busyAction: "publish", lastError: "" });
    if (scope.owns()) get().setStatus(nodeId, "Публикация ревизии…");
    try {
      let document = (data.document || null) as Record<string, unknown> | null;
      if (!document && data.systemId) {
        const resp = await scope.wait(fetch("/api/design-system/get", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ systemId: data.systemId, revision: 0 }),
        }));
        const got = await scope.wait(resp.json());
        document = got.document || null;
      }
      if (!document) {
        if (scope.owns()) get().setStatus(nodeId, "Нет документа для публикации", "err");
        if (scope.owns()) get().setNodeData(nodeId, { lastError: "Нет документа для публикации" });
        return false;
      }
      const pub = await scope.wait(fetch("/api/design-system/publish", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document }),
      }));
      const result = await scope.wait(pub.json());
      if (result.errors?.length || result.error) {
        const message = result.errors?.[0]?.message || result.error || "публикация блокирована";
        if (scope.owns()) get().setStatus(nodeId, `Публикация блокирована: ${message}`, "err");
        if (scope.owns()) get().setNodeData(nodeId, { lastError: message });
        return false;
      }
      if (scope.owns()) get().setNodeData(nodeId, {
        status: "published",
        revision: result.document.revision,
        summary: result.summary,
        contentHash: result.document.contentHash || "",
        resolvedTokens: outValue({ ...n, data: { ...data, document: result.document } } as FlowNode, "tokens"),
        // опубликованная копия не хранится в ноде: ревизия живёт на сервере
        // (design_system_revisions), документ подтянется по ссылке
        // systemId@revision при следующем открытии редактора — автосейв
        // графа не таскает мегабайтные снимки
        document: null,
        lastError: "",
      });
      if (scope.owns()) get().setStatus(nodeId, `Опубликовано v${result.document.revision}${result.duplicate ? " (без изменений)" : ""}`, "ok");
      if (scope.owns()) get().propagate(nodeId);
      await scope.wait(get().refreshDesignSystems());
      return true;
    } catch (e) {
      if (!scope.owns()) return false;
      const message = e instanceof Error ? e.message : String(e);
      if (scope.owns()) get().setStatus(nodeId, "Ошибка: " + message, "err");
      if (scope.owns()) get().setNodeData(nodeId, { lastError: message });
      return false;
    } finally {
      if (scope.owns()) get().setBusy(nodeId, false);
      if (scope.owns()) get().setNodeData(nodeId, { busyAction: "" });
    }
  },

  setDefaultDesignSystem: async (nodeId) => {
    const scope = captureNodeScope(get, nodeId);
    const n = get().nodes.find((x) => Number(x.id) === Number(nodeId));
    if (!n || n.type !== "designsystem") return false;
    const data = n.data as DesignSystemNodeData;
    if (!data.systemId) return false;
    if (scope.owns()) get().setBusy(nodeId, true);
    if (scope.owns()) get().setNodeData(nodeId, { busyAction: "default", lastError: "" });
    if (scope.owns()) get().setStatus(nodeId, "Назначаю системой проекта…");
    try {
      const resp = await scope.wait(fetch("/api/design-system/default", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ systemId: data.systemId }),
      }));
      const result = await scope.wait(resp.json());
      if (result.error) {
        if (scope.owns()) get().setStatus(nodeId, "Ошибка: " + result.error, "err");
        if (scope.owns()) get().setNodeData(nodeId, { lastError: result.error });
        return false;
      }
      const selectedId = Number(nodeId);
      set((state) => ({
        nodes: state.nodes.map((node) => {
          if (node.type !== "designsystem") return node;
          const isSelected = Number(node.id) === selectedId;
          return {
            ...node,
            data: {
              ...node.data,
              defaultSet: isSelected,
              ...(isSelected ? { lastError: "" } : {}),
            },
          } as FlowNode;
        }),
      }));
      await scope.wait(get().refreshDesignSystems());
      if (scope.owns()) get().setStatus(nodeId, "Назначена системой проекта по умолчанию", "ok");
      return true;
    } catch (e) {
      if (!scope.owns()) return false;
      const message = e instanceof Error ? e.message : String(e);
      if (scope.owns()) get().setStatus(nodeId, "Ошибка: " + message, "err");
      if (scope.owns()) get().setNodeData(nodeId, { lastError: message });
      return false;
    } finally {
      if (scope.owns()) get().setBusy(nodeId, false);
      if (scope.owns()) get().setNodeData(nodeId, { busyAction: "" });
    }
  },

  rebuildDesignSystemFromSource: async (nodeId) => {
    const n = get().nodes.find((x) => Number(x.id) === Number(nodeId));
    if (!n || n.type !== "designsystem" || get().busy[nodeId]) return false;
    const data = n.data as DesignSystemNodeData;
    const pageId = get().activePageId;
    const signal = beginRunAbort(nodeId);
    const ownsBuild = () => get().activePageId === pageId && runAborts.get(nodeId)?.signal === signal
      && get().nodes.some((x) => Number(x.id) === Number(nodeId) && x.type === "designsystem");
    const buildStage = (status: AiPipelineStage["status"], message: string, fresh = false) => {
      if (!ownsBuild()) return;
      const current = get().nodes.find((x) => Number(x.id) === Number(nodeId))!.data as DesignSystemNodeData;
      const stages = { ...current.pipelineStatus };
      const updatedAt = new Date().toISOString();
      if (fresh) for (const operation of ["organize", "style-review", "master-review"]) {
        stages[operation] = { status: "skipped", message: "Не запускалось для пересобранного документа; прежний результат устарел", updatedAt };
      }
      stages.build = { status, message, updatedAt };
      get().setNodeData(nodeId, { pipelineStatus: stages });
      get().setStatus(nodeId, message, status === "success" ? "ok" : status === "running" ? undefined : "err");
    };
    const sourceNode = connectedDesignSystemSource(get().nodes, get().edges, n);
    if (!sourceNode) {
      buildStage("failed", "Source-нода не найдена");
      get().setNodeData(nodeId, { lastError: "Source-нода не найдена" });
      return false;
    }
    const fingerprint = sourceKitFingerprint(sourceNode.data);
    get().setBusy(nodeId, true);
    get().setNodeData(nodeId, { busyAction: "sync", lastError: "" });
    buildStage("running", "Синхронизация с Source…");
    try {
      const resp = await fetch("/api/design-system/build", {
        method: "POST", headers: { "Content-Type": "application/json" }, signal,
        body: JSON.stringify({
          sourceNodeId: sourceNode.id, sourceUrl: sourceNode.data.importedUrl || sourceNode.data.url || "",
          systemId: data.systemId || undefined,
          blocks: (sourceNode.data as SourceImportNodeData).blocks || [],
          tokens: (sourceNode.data as SourceImportNodeData).tokens || {},
          sourceArtifact: (sourceNode.data as SourceImportNodeData).sourceArtifact || null,
          name: data.name,
          capturedAt: String((sourceNode.data as SourceImportNodeData & { capturedAt?: string }).capturedAt || ""),
        }),
      });
      const result = await resp.json();
      if (!ownsBuild()) return false;
      if (signal.aborted) throw new DOMException("Сборка отменена", "AbortError");
      if (!resp.ok || result.error || !result.document) {
        const detail = result.detail || result.error;
        const first = typeof detail === "object" && Array.isArray(detail?.errors) ? detail.errors[0] : null;
        const message = detail && typeof detail === "object"
          ? [detail.message || detail.code || `HTTP ${resp.status}`, first?.message, first?.path,
            detail.errors?.length > 1 ? `Ошибок: ${detail.errors.length}` : ""].filter(Boolean).join(" · ")
          : String(detail || `HTTP ${resp.status}`);
        buildStage("failed", "Ошибка: " + message);
        get().setNodeData(nodeId, { lastError: message });
        return false;
      }
      const current = get().nodes.find((x) => Number(x.id) === Number(nodeId));
      if (!current || current.type !== "designsystem") return false;
      const currentSource = connectedDesignSystemSource(get().nodes, get().edges, current);
      if (currentSource?.id !== sourceNode.id || sourceKitFingerprint(currentSource.data) !== fingerprint
        || current.data.systemId !== data.systemId || current.data.revision !== data.revision
        || inputFingerprint(current.data.document ?? null) !== inputFingerprint(data.document ?? null)) {
        buildStage("cancelled", "Source или документ изменился во время сборки — повторите Sync");
        get().setNodeData(nodeId, { sourceUpdate: true, lastError: "Source изменился во время сборки — повторите Sync" });
        return false;
      }
      get().setNodeData(nodeId, {
        systemId: result.document.id,
        name: result.document.name,
        status: "draft",
        revision: 0,
        contentHash: "",
        defaultSet: false,
        sourceNodeId: Number(sourceNode.id),
        _sourceFingerprint: fingerprint,
        summary: result.summary,
        sourceUpdate: false,
        document: result.document,
        lastError: "",
      });
      buildStage("success", "UI Kit обновлён из Source · компоненты доступны", true);
      get().propagate(nodeId);
      return true;
    } catch (e) {
      if (!ownsBuild()) return false;
      const message = e instanceof Error ? e.message : String(e);
      buildStage(signal.aborted || (e instanceof Error && e.name === "AbortError") ? "cancelled" : "failed", message);
      get().setNodeData(nodeId, { lastError: message });
      return false;
    } finally {
      if (ownsBuild()) {
        get().setBusy(nodeId, false);
        get().setNodeData(nodeId, { busyAction: "" });
      }
    }
  },

  finishDesignSystem: async (nodeId) => {
    let initial = get();
    let node = initial.nodes.find((n) => Number(n.id) === nodeId);
    if (!node || node.type !== "designsystem" || initial.busy[nodeId] || node.data._dsFinishing) return false;
    if (node.data.sourceUpdate) {
      if (!await get().rebuildDesignSystemFromSource(nodeId)) return false;
      initial = get();
      node = initial.nodes.find((n) => Number(n.id) === nodeId);
      if (!node || node.type !== "designsystem" || node.data.sourceUpdate || initial.busy[nodeId] || node.data._dsFinishing) return false;
    }
    const selectedProvider = resolveDesignSystemAiProvider(initial.nodes, initial.edges, node);
    const pageId = initial.activePageId;
    const systemId = node.data.systemId;
    const source = connectedDesignSystemSource(initial.nodes, initial.edges, node);
    const fingerprint = source ? sourceKitFingerprint(source.data) : null;
    const token = newRunId();
    const current = () => get().nodes.find((n) => Number(n.id) === nodeId && n.type === "designsystem") as typeof node | undefined;
    const owns = () => get().activePageId === pageId && current()?.data._dsFinishing === token;
    const fresh = () => {
      const live = current();
      if (!owns() || !live || live.data.systemId !== systemId || live.data.sourceUpdate
        || resolveDesignSystemAiProvider(get().nodes, get().edges, live) !== selectedProvider) return false;
      const connected = connectedDesignSystemSource(get().nodes, get().edges, live);
      return connected?.id === source?.id && (connected ? sourceKitFingerprint(connected.data) : null) === fingerprint;
    };
    get().setNodeData(nodeId, { _dsFinishing: token });
    try {
      for (const operation of ["organize", "style-review", "master-review"] as const) {
        if (!fresh()) return false;
        if (operation !== "master-review" && current()?.data.pipelineStatus?.[operation]?.status === "success") continue;
        // runDesignSystemAi already performs review -> safe repair -> verification.
        // Rejected candidates are NOT committed. Another pass would judge the
        // same masters again. Only a retryable response-format error may resume.
        const attempts = 2;
        for (let attempt = 0; attempt < attempts; attempt++) {
          const result = await get().runDesignSystemAi(nodeId, operation);
          if (!fresh()) return false;
          if (!result) {
            if (current()?.data._dsAiRetryable && attempt + 1 < attempts) continue;
            return false;
          }
          if (current()?.data.pipelineStatus?.[operation]?.status === "success") break;
          return false;
        }
        if (current()?.data.pipelineStatus?.[operation]?.status !== "success") return false;
      }
      if (!fresh()) return false;
      const data = current()!.data;
      if (Number(data.summary?.reviewMasters || 0) || Object.keys(data.document?.reviewComponents || {}).length) return false;
      if (data.autoPublish !== false) return await get().publishDesignSystem(nodeId);
      get().setStatus(nodeId, "UI Kit готов · проверки пройдены", "ok");
      return true;
    } finally {
      if (owns()) get().setNodeData(nodeId, { _dsFinishing: null });
    }
  },

  runDesktopDesignSystemAi,
  runDesignSystemAi: (nodeId, operation, viewport) => runDesktopDesignSystemAi(nodeId, operation, { viewport }),

  saveDesignSystemDocument: async (nodeId, document) => {
    const n = get().nodes.find((x) => Number(x.id) === Number(nodeId));
    if (!n || n.type !== "designsystem" || get().busy[nodeId]) return false;
    const pageId = get().activePageId;
    const original = inputFingerprint(n.data.document ?? null);
    const source = connectedDesignSystemSource(get().nodes, get().edges, n);
    const sourceFingerprint = source ? sourceKitFingerprint(source.data) : null;
    const saveToken = newRunId();
    get().setNodeData(nodeId, { _dsSave: saveToken });
    const currentSave = () => {
      const current = get().nodes.find((x) => Number(x.id) === Number(nodeId));
      if (!current || current.type !== "designsystem" || current.data._dsSave !== saveToken || get().activePageId !== pageId) return false;
      const currentSource = connectedDesignSystemSource(get().nodes, get().edges, current);
      return inputFingerprint(current.data.document ?? null) === original && currentSource?.id === source?.id
        && (currentSource ? sourceKitFingerprint(currentSource.data) : null) === sourceFingerprint;
    };
    try {
      if (!currentSave()) return false;
      const resp = await fetch("/api/design-system/save-draft", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document }),
      });
      const result = await resp.json();
      if (!currentSave()) return false;
      if (!resp.ok || result.error) {
        result.error ||= result.detail || `HTTP ${resp.status}`;
        get().setNodeData(nodeId, { lastError: result.error });
        get().setStatus(nodeId, "Ошибка: " + result.error, "err");
        return false;
      }
      get().setNodeData(nodeId, {
        document: result.document || document,
        summary: result.summary,
        status: "draft",
        lastError: "",
      });
      return true;
    } catch (e) {
      if (!currentSave()) return false;
      const message = e instanceof Error ? e.message : String(e);
      get().setNodeData(nodeId, { lastError: message });
      get().setStatus(nodeId, "Ошибка: " + message, "err");
      return false;
    }
  },

  restorePublishedDesignSystem: async (nodeId, ref) => {
    const scope = captureNodeScope(get, nodeId);
    const n = get().nodes.find((x) => Number(x.id) === Number(nodeId));
    if (!n || n.type !== "designsystem") return false;
    const data = n.data as DesignSystemNodeData;
    const systemId = String(ref?.systemId || data.systemId || "");
    const revision = Number(ref?.revision || data.revision || 0);
    if (!systemId) {
      if (scope.owns()) get().setNodeData(nodeId, { lastError: "Нет опубликованной ревизии для восстановления" });
      return false;
    }
    try {
      const resp = await scope.wait(fetch("/api/design-system/restore-published", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ systemId, revision }),
      }));
      const result = await scope.wait(resp.json());
      if (result.error || !result.document) {
        if (scope.owns()) get().setNodeData(nodeId, { lastError: result.error || "Не удалось восстановить опубликованную ревизию" });
        if (scope.owns()) get().setStatus(nodeId, "Ошибка: " + (result.error || "restore failed"), "err");
        return false;
      }
      if (scope.owns()) get().setNodeData(nodeId, {
        document: null,
        resolvedTokens: outValue({ ...n, data: { ...data, document: result.document } } as FlowNode, "tokens"),
        contentHash: result.document.contentHash || "",
        summary: result.summary,
        status: "published",
        revision: result.document.revision,
        lastError: "",
      });
      if (scope.owns()) get().propagate(nodeId);
      await scope.wait(get().refreshDesignSystems());
      return true;
    } catch (e) {
      if (!scope.owns()) return false;
      const message = e instanceof Error ? e.message : String(e);
      if (scope.owns()) get().setNodeData(nodeId, { lastError: message });
      if (scope.owns()) get().setStatus(nodeId, "Ошибка: " + message, "err");
      return false;
    }
  },

  sendDesignSystemToGenerator: (nodeId) => {
    const state = get();
    const source = state.nodes.find(n => Number(n.id) === nodeId && n.type === 'designsystem');
    if (!source || source.type !== 'designsystem' || !source.data.systemId) return null;
    // The exact graph node is authoritative, including drafts and duplicate registry references.
    const existing = state.nodes.find(n => n.type === 'generator' && state.edges.some(e =>
      e.source === source.id && e.sourceHandle === 'system' && e.target === n.id && e.targetHandle === 'designSystem'));
    const target = existing || get().addNode('generator', source.position.x + 390, source.position.y);
    const targetId = Number(target.id);
    if (!existing) {
      get().setNodeData(targetId, { provider: resolveDesignSystemAiProvider(state.nodes, state.edges, source) });
      if (!get().connect({ node: nodeId, port: 'system' }, { node: targetId, port: 'designSystem' })) {
        get().deleteNode(targetId);
        return null;
      }
      get().setStatus(targetId, 'UI Kit подключён · задайте промпт и запустите генерацию');
    }
    set({ nodes: get().nodes.map(n => ({ ...n, selected: n.id === String(target.id) })) });
    const scope = captureNodeScope(get, targetId);
    void focusFlowNode(String(target.id), scope.owns);
    return targetId;
  },

  copyDesignSystemComponentToEditor: (nodeId, componentKey, pool, variant) => {
    const node = get().nodes.find(n => Number(n.id) === nodeId && n.type === 'designsystem');
    if (!node) return null;
    const document = (node.data as DesignSystemNodeData).document as Record<string, any> | null;
    const component = document?.[pool === 'review' ? 'reviewComponents' : pool]?.[componentKey];
    if (!component?.masterIr || component.origin !== 'observed') return null;
    const masterIr = selectedComponentMaster(component, variant);
    if (!masterIr) return null;
    const ir = renderableDesignSystemMaster({ masterIr });
    if (!ir) return null;
    const edit = get().addNode('edit', node.position.x + 360, node.position.y);
    // A working copy has no registry pin and cannot promote a review master.
    get().setNodeData(Number(edit.id), { ir, label: `Копия · ${component.name || componentKey}` });
    window.dispatchEvent(new Event('designdna:ensure-editor'));
    return Number(edit.id);
  },

  applyDesignSystemToEditor: (nodeId, componentKey) => {
    const st = get();
    const dsNode = st.nodes.find((x) => Number(x.id) === Number(nodeId));
    if (!dsNode || dsNode.type !== "designsystem") return null;
    const data = dsNode.data as DesignSystemNodeData;
    const document = (data.document || {}) as { components?: Record<string, { templateIr?: IRObject; masterIr?: IRObject; componentKey?: string }> };
    const comp = document.components?.[componentKey];
    const templateIr = comp ? renderableDesignSystemMaster(comp) : null;
    if (!templateIr) {
      get().setStatus(nodeId, "Нет template IR у выбранного компонента", "err");
      return null;
    }
    const existing = st.nodes.find((x) => {
      if (x.type !== "edit") return false;
      const master = (x.data as Record<string, unknown>)._dsMaster as { systemId?: string; componentKey?: string } | undefined;
      return master?.systemId === data.systemId && master?.componentKey === componentKey;
    });
    const created = existing || get().addNode("edit", dsNode.position.x + 360, dsNode.position.y);
    const editNodeId = Number(created.id);
    const current = get().nodes.find((x) => Number(x.id) === editNodeId);
    const previousIr = ((current?.data as { ir?: IRObject | null } | undefined)?.ir || null) as IRObject | null;
    get().setNodeData(editNodeId, {
      ir: deepClone(templateIr),
      _dsMaster: { systemId: data.systemId, componentKey, nodeId },
      _dsPreviousIr: previousIr,
    });
    window.dispatchEvent(new Event("designdna:ensure-editor"));
    get().setStatus(nodeId, `Мастер «${componentKey}» открыт в DNA Editor`, "ok");
    return { editNodeId, previousIr };
  },

  restoreDesignSystemEditorApply: (editNodeId, previousIr) => {
    const n = get().nodes.find((x) => Number(x.id) === Number(editNodeId));
    if (!n || n.type !== "edit") return;
    if (previousIr) get().setNodeData(editNodeId, { ir: deepClone(previousIr) });
    else get().setNodeData(editNodeId, { ir: null });
  },

  clearGraph: () => {
    get().loadGraph({ nodes: [], edges: [], view: { ...DEFAULT_VIEW }, nextId: 1 });
  },

  setView: (v) => {
    set({ view: v });
  },

  createPage: (name) => {
    leaveGraph();
    const st = get();
    const id = pageId();
    const nextIndex = st.pages.length + 1;
    const page: FlowPage = {
      id,
      name: (name || `Page ${nextIndex}`).trim() || `Page ${nextIndex}`,
      nodes: [],
      edges: [],
      view: { ...DEFAULT_VIEW },
      nextId: 1,
    };
    set((state) => ({
      pages: [...withCurrentPageSaved(state), page],
      activePageId: id,
      nodes: page.nodes,
      edges: page.edges,
      view: page.view,
      nextId: page.nextId,
      statuses: {},
      statusLog: {},
      busy: {},
      progresses: {},
      graphHistory: EMPTY_GRAPH_HISTORY,
    }));
  },

  /* Start an isolated video workspace from the selected assembled page.
   * A snapshot preserves the original graph; no import, generation or paid job starts. */
  addVideoChainPage: (options) => {
    leaveGraph();
    const assembled = get().nodes.filter((node) => node.type === "page" && node.data.ir);
    const selected = assembled.filter((node) => node.selected);
    const source = selected.length === 1 ? selected[0] : assembled.length === 1 ? assembled[0] : null;
    const sourceIr = source?.type === "page" && source.data.ir ? deepClone(source.data.ir) : null;
    const provider = options?.provider === "claude" ? "claude" : "codex";
    let nextId = 1;
    const mkNode = (type: NodeType, x: number, y: number, patch: Record<string, unknown> = {}) => ({
      id: String(nextId++), type, position: { x, y },
      initialWidth: NODE_DEFS[type].w, initialHeight: 120,
      data: { ...defaultData(type), ...patch },
    }) as FlowNode;
    const sourcePage = mkNode("page", 40, 120, { ir: sourceIr });
    const video = mkNode("timeline", 480, 120, { ir: sourceIr ? deepClone(sourceIr) : null, provider });
    const nodes = [sourcePage, video];
    const edges = [makeRfEdge(nodes, { node: Number(sourcePage.id), port: "ir" }, { node: Number(video.id), port: "ir" })];
    const id = pageId();
    const page: FlowPage = {
      id,
      name: "Видео",
      nodes,
      edges,
      view: { ...DEFAULT_VIEW },
      nextId,
    };
    set((state) => ({
      pages: [...withCurrentPageSaved(state), page],
      activePageId: id,
      nodes: page.nodes,
      edges: page.edges,
      view: page.view,
      nextId: page.nextId,
      statuses: {},
      statusLog: {},
      busy: {},
      progresses: {},
      graphHistory: EMPTY_GRAPH_HISTORY,
    }));
    // вписать цепочку в экран: ноды измеряются асинхронно, поэтому дважды
    setTimeout(fitFlowView, 80);
    setTimeout(fitFlowView, 450);
  },

  switchPage: (id) => {
    const st = get();
    if (id === st.activePageId || !st.pages.some(page => page.id === id)) return;
    leaveGraph();
    const pages = withCurrentPageSaved(get());
    const page = pages.find((p) => p.id === id);
    if (!page) return;
    set({
      pages,
      activePageId: id,
      nodes: hydratePageBridgeNodes(page.nodes, st.channels),
      edges: page.edges,
      view: page.view,
      nextId: page.nextId,
      statuses: {},
      statusLog: {},
      busy: {},
      progresses: {},
      graphHistory: EMPTY_GRAPH_HISTORY,
    });
    // каждая страница начинается с полного вида: без ручного зума
    setTimeout(fitFlowView, 80);
    setTimeout(fitFlowView, 450);
  },

  renamePage: (id, name) => {
    const nextName = name.trim();
    if (!nextName) return;
    set((state) => ({
      pages: withCurrentPageSaved(state).map((page) =>
        page.id === id ? { ...page, name: nextName } : page,
      ),
    }));
  },

  deletePage: (id) => {
    const st = get();
    if (st.pages.length <= 1 || !st.pages.some(page => page.id === id)) return;
    leaveGraph();
    const pages = withCurrentPageSaved(get()).filter((page) => page.id !== id);
    const next = pages.find((page) => page.id === st.activePageId) || pages[0];
    set({
      pages,
      activePageId: next.id,
      nodes: hydratePageBridgeNodes(next.nodes, st.channels),
      edges: next.edges,
      view: next.view,
      nextId: next.nextId,
      statuses: {},
      statusLog: {},
      busy: {},
      progresses: {},
      graphHistory: EMPTY_GRAPH_HISTORY,
    });
  },

  loadPersistedProject: async () => {
    void get().refreshDesignSystems(); // registry не блокирует загрузку проекта
    const project = await loadPagesProjectFromDb();
    if (!project) {
      set({ projectHydrated: true });
      return;
    }
    // Гонка гидратации: пока шёл fetch, локальный граф мог измениться (пользователь
    // или GraphDev.add в тестах уже добавил ноды) — применять загруженный проект
    // поверх нельзя, он затёр бы локальные правки пустым/устаревшим состоянием.
    if (localDirtySinceInit) {
      set({ projectHydrated: true });
      return;
    }
    const current = get();
    const dbNodeCount = project.pages.reduce((sum, page) => sum + page.nodes.length, 0);
    if (dbNodeCount === 0 && (current.nodes.length > 0 || current.edges.length > 0)) {
      set({ projectHydrated: true });
      return;
    }
    const activePage = project.pages.find((page) => page.id === project.activePageId) || project.pages[0];
    if (!activePage) {
      set({ projectHydrated: true });
      return;
    }
    set({
      pages: project.pages,
      activePageId: activePage.id,
      nodes: hydratePageBridgeNodes(activePage.nodes, project.channels),
      edges: activePage.edges,
      view: activePage.view,
      nextId: activePage.nextId,
      channels: project.channels,
      statuses: {},
      statusLog: {},
      busy: {},
      progresses: {},
      graphHistory: EMPTY_GRAPH_HISTORY,
    });
    // Keep the canvas->store mirror closed for one task after publishing the
    // loaded arrays. Svelte effects may otherwise observe `projectHydrated`
    // before their local bound nodes receive the same snapshot and mirror the
    // temporary empty canvas back over the freshly loaded project.
    setTimeout(() => {
      set({ projectHydrated: true });
      fitFlowView();
      setTimeout(fitFlowView, 350);
    }, 0);
  },

  replaceProjectFromDb: async () => {
    const project = await loadPagesProjectFromDb();
    if (!project) return false;
    const activePage = project.pages.find((page) => page.id === project.activePageId) || project.pages[0];
    if (!activePage) return false;
    const current = get();
    const preserved = new Set<number>();
    const nodes = activePage.nodes.map((incoming) => {
      if (current.activePageId !== activePage.id) return incoming;
      const live = current.nodes.find((node) => node.id === incoming.id && node.type === incoming.type);
      if (!live) return incoming;
      if (live.type === "designsystem" && incoming.type === "designsystem") {
        const a = live.data, b = incoming.data;
        const liveSource = connectedDesignSystemSource(current.nodes, current.edges, live);
        const nextSource = connectedDesignSystemSource(activePage.nodes, activePage.edges, incoming);
        if (a.systemId !== b.systemId || a.revision !== b.revision
          || (a.document?.contentHash || a.contentHash || "") !== (b.document?.contentHash || b.contentHash || "")
          || liveSource?.id !== nextSource?.id
          || (liveSource ? sourceKitFingerprint(liveSource.data) : null) !== (nextSource ? sourceKitFingerprint(nextSource.data) : null)
          || (b.document != null && inputFingerprint(b.document) !== inputFingerprint(a.document ?? null))) return incoming;
        // A persisted reference is not an instruction to evict the live cache.
        // Preserve runtime ownership only for this exact DS revision and Source.
        preserved.add(Number(incoming.id));
        return { ...incoming, data: { ...b, document: a.document ?? b.document,
          _dsAiRun: a._dsAiRun, _dsAiRetryable: a._dsAiRetryable, _dsSave: a._dsSave, _dsFinishing: a._dsFinishing, busyAction: a.busyAction,
          pipelineStatus: a.pipelineStatus, lastError: a.lastError, sourceUpdate: a.sourceUpdate } } as FlowNode;
      }
      if (live.type === "sourceimport" && incoming.type === "sourceimport"
        && sourceKitFingerprint(live.data) === sourceKitFingerprint(incoming.data)
        && live.data.url === incoming.data.url && live.data.image === incoming.data.image && live.data.mode === incoming.data.mode) {
        preserved.add(Number(incoming.id));
        return { ...incoming, data: { ...incoming.data, _sourceRun: (live.data as unknown as Record<string, unknown>)._sourceRun,
          pipelineStatus: live.data.pipelineStatus } } as FlowNode;
      }
      return incoming;
    });
    for (const node of current.nodes) {
      const id = Number(node.id);
      if (!preserved.has(id)) {
        nodeLifetimes.set(id, (nodeLifetimes.get(id) || 0) + 1);
        runAborts.get(id)?.abort();
      }
    }
    const keepRuntime = <T>(values: Record<number, T>) => Object.fromEntries(Object.entries(values).filter(([id]) => preserved.has(Number(id))));
    set({
      pages: project.pages.map((page) => page.id === activePage.id ? { ...page, nodes } : page),
      activePageId: activePage.id,
      nodes: hydratePageBridgeNodes(nodes, project.channels),
      edges: activePage.edges,
      view: activePage.view,
      nextId: activePage.nextId,
      channels: project.channels,
      statuses: keepRuntime(current.statuses),
      statusLog: keepRuntime(current.statusLog),
      busy: keepRuntime(current.busy),
      progresses: keepRuntime(current.progresses),
      graphHistory: EMPTY_GRAPH_HISTORY,
      projectHydrated: true,
    });
    setTimeout(fitFlowView, 0);
    return true;
  },
}));

function samePersistedNodes(a: FlowNode[], b: FlowNode[]): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  return a.every((node, index) => {
    const other = b[index];
    return !!other
      && node.id === other.id
      && node.type === other.type
      && node.position.x === other.position.x
      && node.position.y === other.position.y
      && node.data === other.data;
  });
}

function samePersistedEdges(a: FlowEdge[], b: FlowEdge[]): boolean {
  if (a === b) return true;
  if (a.length !== b.length) return false;
  return a.every((edge, index) => {
    const other = b[index];
    return !!other
      && edge.id === other.id
      && edge.source === other.source
      && edge.sourceHandle === other.sourceHandle
      && edge.target === other.target
      && edge.targetHandle === other.targetHandle;
  });
}

/* Автосейв: selection/measurement changes from Svelte Flow are runtime-only.
 * Serializing three Source Import payloads for every click can freeze the renderer.
 * view намеренно не будит автосейв: pan/zoom не сериализуют проект — вью
 * уезжает в сейв при следующем реальном изменении либо во flush на unload. */
useFlowStore.subscribe((state, prev) => {
  const nodesChanged = !samePersistedNodes(state.nodes, prev.nodes);
  const edgesChanged = !samePersistedEdges(state.edges, prev.edges);
  if (
    !nodesChanged &&
    !edgesChanged &&
    state.nextId === prev.nextId &&
    state.pages === prev.pages &&
    state.activePageId === prev.activePageId &&
    state.channels === prev.channels
  )
    return;
  localDirtySinceInit = true;
  scheduleProjectSave(() => buildPagesProjectPayload(useFlowStore.getState()));
});

// AI-ассист редактора читает registry дизайн-систем отсюда (§16.2)
if (typeof window !== "undefined") (window as unknown as { __flowStore?: unknown }).__flowStore = useFlowStore;

// FileReader callbacks outlive inspectors and sheets. Capture the target at selection
// time and let the most recently selected file win even if reads finish out of order.
const nodeUploadTokens = new Map<number, symbol>();
export function captureNodeUpload(id: number) {
  const scope = captureNodeScope(useFlowStore.getState, id);
  const token = Symbol('node-upload');
  nodeUploadTokens.set(id, token);
  return (patch: Record<string, unknown>) => {
    if (!scope.owns() || nodeUploadTokens.get(id) !== token) return false;
    nodeUploadTokens.delete(id);
    useFlowStore.getState().setNodeData(id, patch);
    useFlowStore.getState().propagate(id);
    return true;
  };
}
