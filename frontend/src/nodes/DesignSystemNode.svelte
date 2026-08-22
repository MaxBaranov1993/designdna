<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import { flow } from "../flow/state";
    import type { DesignSystemFlowNode } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";

  /* Design System-нода (ТЗ §11): карточка системы + действия. Портов нет —
   * использование через registry и DesignSystemPicker, не через провода. */
  let { id, data, selected }: NodeProps<DesignSystemFlowNode> = $props();

  let busy = $derived(!!$flow.busy[Number(id)]);
  const summary = $derived((data.summary || {}) as Record<string, any>);
  const originLabel = $derived((summary.origins || {}) as Record<string, number>);

  const run = (action: "publish" | "default" | "sync") => {
    $flow.setBusy(Number(id), true);
    $flow.setStatus(Number(id), action === "publish" ? "Публикация ревизии…" : action === "default" ? "Назначаю системой проекта…" : "Синхронизация с Source…");
    void (async () => {
      try {
        if (action === "publish") {
          const resp = await fetch("/api/design-system/get", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ systemId: data.systemId, revision: 0 }) });
          const got = await resp.json();
          let document = got.document;
          if (!document) {
            // черновик ещё не публиковался — берём из данных ноды (кэш билда)
            document = (data as any).document;
          }
          const pub = await fetch("/api/design-system/publish", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ document }) });
          const result = await pub.json();
          if (result.errors?.length) {
            $flow.setStatus(Number(id), `Публикация блокирована: ${result.errors[0].message}`, "err");
            return;
          }
          $flow.setNodeData(Number(id), { status: "published", revision: result.document.revision, summary: result.summary });
          $flow.setStatus(Number(id), `Опубликовано v${result.document.revision}${result.duplicate ? " (без изменений)" : ""}`, "ok");
          $flow.refreshDesignSystems();
        } else if (action === "default") {
          const resp = await fetch("/api/design-system/default", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ systemId: data.systemId }) });
          const result = await resp.json();
          if (result.error) { $flow.setStatus(Number(id), "Ошибка: " + result.error, "err"); return; }
          $flow.setNodeData(Number(id), { defaultSet: true });
          $flow.refreshDesignSystems();
          $flow.setStatus(Number(id), "Назначена системой проекта по умолчанию", "ok");
        } else {
          const sourceNode = $flow.nodes.find((n) => Number(n.id) === Number(data.sourceNodeId));
          if (!sourceNode) { $flow.setStatus(Number(id), "Source-нода не найдена", "err"); return; }
          const resp = await fetch("/api/design-system/build", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sourceNodeId: data.sourceNodeId, sourceUrl: (sourceNode.data as any).url || "",
              blocks: (sourceNode.data as any).blocks || [], tokens: (sourceNode.data as any).tokens || {},
              name: data.name }) });
          const result = await resp.json();
          if (result.error) { $flow.setStatus(Number(id), "Ошибка: " + result.error, "err"); return; }
          $flow.setNodeData(Number(id), { status: "draft", summary: result.summary, sourceUpdate: false, document: result.document } as any);
          $flow.setStatus(Number(id), "Черновик пересобран из Source — проверьте и опубликуйте", "ok");
        }
      } catch (e) {
        $flow.setStatus(Number(id), "Ошибка: " + (e instanceof Error ? e.message : String(e)), "err");
      } finally {
        $flow.setBusy(Number(id), false);
      }
    })();
  };
</script>

<NodeShell {id} type="designsystem" {selected}>
  <div class="ds-head">
    <span class="ds-icon">◈</span>
    <div class="ds-title">
      <strong>{data.name || "Design System"}</strong>
      <small>{data.status === "published" ? `Published · v${data.revision}` : data.status === "draft" ? "Draft" : data.status}{data.defaultSet ? " · проект по умолчанию" : ""}</small>
    </div>
  </div>
  {#if data.systemId && summary.components}
    <div class="ds-stats">
      <span>{summary.components} компонентов</span>
      <span>{summary.variants} вариантов</span>
      <span>{Math.round(summary.stateCoverage || 0)}% states</span>
      <span>{summary.mockSchemas} mock-схем</span>
      <span>Quality {Math.round(summary.qualityScore || 0)}/100</span>
      <span class="ds-origins" title="observed / inferred / generated">
        {originLabel.observed || 0}⬤ {originLabel.inferred || 0}◐ {originLabel.generated || 0}◇
      </span>
    </div>
  {:else if !data.systemId}
    <div class="ds-empty">Создайте из Source-ноды: «UI Kit & Design System»</div>
  {/if}
  {#if data.sourceUpdate}
    <div class="ds-update">Source изменился — доступна синхронизация</div>
  {/if}
  <div class="ds-actions">
      <button class="btn-node primary small nodrag" disabled={!data.systemId} onclick={() => {
        window.dispatchEvent(new CustomEvent("designdna:open-ds-editor", { detail: { nodeId: Number(id) } }));
      }}>Открыть</button>
    {#if data.systemId}
      <button class="btn-node small nodrag" onclick={() => run("publish")} disabled={busy || data.status === "published"}>
        {busy ? "…" : "Опубликовать"}
      </button>
      <button class="btn-node small nodrag" onclick={() => run("default")} disabled={busy || data.defaultSet || data.status !== "published"}>
        По умолчанию
      </button>
      {#if data.sourceNodeId}
        <button class="btn-node small nodrag" onclick={() => run("sync")} disabled={busy}>Sync</button>
      {/if}
    {/if}
  </div>
  <NodeStatus {id} />
</NodeShell>

<style>
  .ds-head { display: flex; gap: 10px; align-items: center; }
  .ds-icon { font-size: 18px; color: #7c6cf0; }
  .ds-title { display: flex; flex-direction: column; min-width: 0; }
  .ds-title strong { font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ds-title small { font-size: 10px; color: #8b8fa3; }
  .ds-stats { display: flex; flex-wrap: wrap; gap: 4px 10px; font-size: 10.5px; color: #aab0c0; margin-top: 8px; }
  .ds-origins { margin-left: auto; letter-spacing: 1px; }
  .ds-empty { font-size: 11px; color: #8b8fa3; padding: 8px 0; }
  .ds-update { font-size: 10.5px; color: #d9a441; margin-top: 6px; }
  .ds-actions { display: flex; gap: 6px; margin-top: 8px; flex-wrap: wrap; }
</style>
