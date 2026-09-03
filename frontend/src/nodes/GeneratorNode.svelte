<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import ProviderPicker from "../components/ProviderPicker.svelte";
  import { flow, flowBusy, flowDesignSystemPicker, flowDesignSystems } from "../flow/state";
  import { pinnedDesignSystemRef } from "../flow/store";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import type { GeneratorFlowNode, GeneratorNodeData } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";

  /* «Генератор» — run-based: бриф тянет из входов prompt/style (pull-based,
   * fallback ownPrompt), POST /api/generate (payload — зеркало runGenerator,
   * nodes.js:498-518). Варианты — миниатюрами, активный — в IrPreview и на
   * выход ir (outValue). Пресеты стиля сняты по хендоффу: стиль приходит
   * из style DNA источника. */
  let { id, data, selected }: NodeProps<GeneratorFlowNode> = $props();

  let busy = $derived(!!$flowBusy[Number(id)]);
  /* ДС, которую генерация реально получит (узел мог унаследовать её от
   * глобального пикера) — иначе strict-ошибки выглядят беспричинными. */
  let dsRef = $derived(pinnedDesignSystemRef(
    data as unknown as Record<string, unknown>,
    $flowDesignSystems,
    $flowDesignSystemPicker,
  ));
  let dsId = $derived(dsRef ? String(dsRef.systemId || "") : "");
  let dsName = $derived(
    dsId ? ($flowDesignSystems.systems?.find((s) => s.systemId === dsId)?.name || dsId) : "",
  );
  let dsOptedOut = $derived(String((data as Record<string, unknown>).designSystemSelection || "") === "none");
  let activeIr = $derived(data.variants.length ? data.variants[data.active] || null : null);
  let effort = $derived(["medium", "high", "max"].includes(data.effort) ? data.effort : "medium");
  let count = $derived(Math.max(1, Math.min(2, Number(data.count) || 1)));
  type Direction = { id: string; label: string; motivation: string; tradeoff: string };
  type QualityReview = { score: number | null; passed: boolean | null; reasons: string[] };
  let generatorData = $derived(data as unknown as GeneratorNodeData & {
    directions?: Direction[];
    selectedDirection?: string;
    variantDirections?: string[];
    qualityReviews?: QualityReview[];
  });
  let directions = $derived(Array.isArray(generatorData.directions) ? generatorData.directions.slice(0, 3) : []);
  let selectedDirection = $derived(generatorData.selectedDirection || "all");
  let activeReview = $derived(generatorData.qualityReviews?.[data.active] || null);

  async function selectDirection(direction: string) {
    if (busy || direction === selectedDirection) return;
    $flow.setNodeData(Number(id), { selectedDirection: direction } as unknown as Partial<GeneratorNodeData>);
    try {
      await fetch("/api/project/taste/outcome", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: "accepted",
          payload: { style: { tags: [`art-direction:${direction}`] } },
        }),
      });
    } catch {
      // Выбор уже сохранён в проекте; недоступная Taste Memory не блокирует UI.
    }
  }
</script>

<NodeShell {id} type="generator" {selected}>
  <InPorts type="generator" />
  <textarea
    class="f-own nodrag nowheel"
    placeholder="Свой промпт (если нет провода)"
    value={data.ownPrompt}
    oninput={(e) => {
      const value = e.currentTarget.value;
      commitNodeText(`generator:${id}:ownPrompt`, () => $flow.setNodeData(Number(id), { ownPrompt: value }));
    }}
    onblur={() => flushNodeText(`generator:${id}:ownPrompt`)}
  ></textarea>
  <div class="generator-model-row">
    <ProviderPicker
      provider={data.provider || "openai"}
      {effort}
      onChange={(next) => $flow.setNodeData(Number(id), next)}
    />
  </div>
  {#if dsRef}
    <div class="gen-ds-row nodrag" title="Дизайн-система придёт в генерацию из глобального выбора проекта">
      <span class="gen-ds-label">◈ ДС: {dsName} · {String(dsRef.usageMode || "strict")}</span>
      <button
        class="gen-ds-off"
        title="Генерировать без дизайн-системы"
        onclick={() => $flow.setNodeData(Number(id), { designSystemSelection: "none" })}
      >×</button>
    </div>
  {:else if dsOptedOut}
    <div class="gen-ds-row nodrag">
      <span class="gen-ds-label">ДС отключена для этой ноды</span>
      <button
        class="gen-ds-off"
        title="Вернуть дизайн-систему проекта"
        onclick={() => $flow.setNodeData(Number(id), { designSystemSelection: "inherit" })}
      >↺</button>
    </div>
  {/if}
  {#if directions.length}
    <section class="direction-picker nodrag" aria-label="Направление арт-дирекции">
      <div class="direction-heading">
        <span>Арт-дирекция</span>
        <button
          class:active={selectedDirection === "all"}
          class="direction-all"
          type="button"
          disabled={busy}
          onclick={() => void selectDirection("all")}
        >Все три</button>
      </div>
      <div class="direction-chips">
        {#each directions as direction (direction.id)}
          <button
            type="button"
            class:active={selectedDirection === direction.id}
            class="direction-chip"
            data-direction-id={direction.id}
            disabled={busy}
            aria-pressed={selectedDirection === direction.id}
            onclick={() => void selectDirection(direction.id)}
          >
            <strong>{direction.label}</strong>
            {#if direction.motivation}<span>{direction.motivation}</span>{/if}
            {#if direction.tradeoff}<small>Компромисс: {direction.tradeoff}</small>{/if}
          </button>
        {/each}
      </div>
    </section>
  {/if}
  <div class="ctl-row">
    <select
      class="f-count nodrag"
      value={String(count)}
      onchange={(e) => $flow.setNodeData(Number(id), { count: Number(e.currentTarget.value) })}
    >
      <option value="1">1</option>
      <option value="2">2</option>
    </select>
    <button
      class="btn-node primary small f-run nodrag"
      disabled={busy}
      onclick={() => $flow.runNode(Number(id))}
    >
      {#if busy}<span class="spinner"></span>{:else}<span>▶</span>{/if} Сгенерировать
    </button>
  </div>
  {#if data.variants.length}
    <div class="thumbs">
      {#each data.variants as v, i (i)}
        <div
          class={"thumb nodrag" + (i === data.active ? " active" : "")}
          title={generatorData.variantDirections?.[i] || directions[i]?.label || `Направление ${i + 1}`}
          role="button"
          tabindex="0"
          onkeydown={(event) => {
            if (event.key !== "Enter" && event.key !== " ") return;
            event.preventDefault();
            if (busy) return;
            $flow.setNodeData(Number(id), { active: i });
            $flow.propagate(Number(id));
          }}
          onclick={() => {
            if (busy) return;
            $flow.setNodeData(Number(id), { active: i });
            $flow.propagate(Number(id));
          }}
        >
          <span class="tbadge">{generatorData.variantDirections?.[i] || directions[i]?.label || `Направление ${i + 1}`}</span>
          <IrPreview ir={v} height={96} empty="" />
        </div>
      {/each}
    </div>
  {/if}
  {#if activeReview && activeReview.passed === false}
    <div class="revision-status nodrag" role="status">
      <strong>Нужна доработка{activeReview.score == null ? "" : ` · ${activeReview.score}/100`}</strong>
      {#if activeReview.reasons.length}
        <ul>
          {#each activeReview.reasons as reason}
            <li>{reason}</li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}
  <IrPreview class="f-preview" ir={activeIr} height={180} empty="Варианты появятся после запуска" />
  <div class="gen-actions">
    <button class="btn-node small f-to-editor nodrag" onclick={() => $flow.sendToNode(Number(id), "edit")}>
      → Editor
    </button>
    <button class="btn-node small f-to-reference nodrag" onclick={() => $flow.sendToNode(Number(id), "reference")}>
      → Reference
    </button>
    <button class="btn-node small nodrag" title="Запомнить как удачный вариант" disabled={busy || !activeIr} onclick={() => void $flow.recordVariantTaste(Number(id), "accepted")}>
      ✓ Принять
    </button>
    <button class="btn-node small nodrag" title="Запомнить как неудачный вариант" disabled={busy || !activeIr} onclick={() => void $flow.recordVariantTaste(Number(id), "rejected")}>
      × Отклонить
    </button>
    <button class="btn-node small primary nodrag" title="Сделать этот вариант дизайн-системой" disabled={busy || !activeIr} onclick={() => void $flow.promoteVariantToDesignSystem(Number(id))}>
      ◈ Закрепить стиль
    </button>
  </div>
  <NodeStatus {id} />
  <OutPorts type="generator" />
</NodeShell>

<style>
  .direction-picker { display: grid; gap: 6px; }
  .direction-heading { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: var(--dna-muted); font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; }
  .direction-all, .direction-chip { border: 1px solid var(--dna-border); background: var(--dna-sunken); color: inherit; cursor: pointer; }
  .direction-all { border-radius: 999px; padding: 3px 8px; font-size: 10px; text-transform: none; letter-spacing: 0; }
  .direction-chips { display: grid; gap: 5px; }
  .direction-chip { display: grid; gap: 2px; width: 100%; border-radius: 8px; padding: 7px 8px; text-align: left; }
  .direction-chip strong { font-size: 11px; }
  .direction-chip span, .direction-chip small { color: var(--dna-muted); font-size: 10px; line-height: 1.3; }
  .direction-chip.active, .direction-all.active { border-color: var(--dna-violet-l); background: rgba(155, 92, 255, .1); box-shadow: 0 0 0 2px rgba(155, 92, 255, .12); }
  .direction-chip:disabled, .direction-all:disabled { cursor: default; opacity: .65; }
  .revision-status { border: 1px solid rgba(239, 68, 68, .35); border-radius: 8px; background: rgba(239, 68, 68, .08); padding: 8px; color: #b91c1c; font-size: 10px; line-height: 1.35; }
  .revision-status ul { margin: 4px 0 0; padding-left: 16px; }
  .tbadge { max-width: calc(100% - 8px); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
