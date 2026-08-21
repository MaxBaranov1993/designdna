<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import { flow } from "../flow/state";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import type { QualityPassFlowNode } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";

  /* Premium Quality Pass: независимый judge выдаёт scorecard, а backend при
   * необходимости выполняет адресный repair и повторно оценивает IR. */
  let { id, data, selected }: NodeProps<QualityPassFlowNode> = $props();

  let busy = $derived(!!$flow.busy[Number(id)]);
  let result = $derived(
    data.result as {
      passed?: boolean;
      scorecard?: { score?: number; verdict?: string; summary?: string; issues?: Array<{ severity?: string; problem?: string }> };
      repair?: { applied?: boolean; error?: string | null };
    } | null,
  );
  let score = $derived(result?.scorecard?.score);
  let issues = $derived(result?.scorecard?.issues || []);
</script>

<NodeShell {id} type="qualitypass" {selected}>
  <InPorts type="qualitypass" />
  <textarea
    class="f-prompt nodrag nowheel"
    placeholder="Бриф для оценки (необязательно, но повышает точность)"
    value={data.brief}
    oninput={(e) => {
      const value = e.currentTarget.value;
      commitNodeText(`qualitypass:${id}:brief`, () => $flow.setNodeData(Number(id), { brief: value }));
    }}
    onblur={() => flushNodeText(`qualitypass:${id}:brief`)}
  ></textarea>
  <div class="ctl-row qp-controls">
    <label class="qp-label nodrag"
      >порог
      <select
        class="f-count"
        value={String(data.minScore)}
        onchange={(e) => $flow.setNodeData(Number(id), { minScore: Number(e.currentTarget.value), result: null })}
      >
        <option value="75">75</option><option value="85">85</option><option value="95">95</option>
      </select>
    </label>
    <label class="qp-label nodrag" title="Исправить замечания судьи и проверить результат повторно">
      <input
        type="checkbox"
        checked={data.repair}
        onchange={(e) => $flow.setNodeData(Number(id), { repair: e.currentTarget.checked, result: null })}
      />
      repair
    </label>
    <button
      class="btn-node primary small f-run nodrag"
      style="margin-left: auto"
      disabled={busy}
      onclick={() => $flow.runNode(Number(id))}
    >
      {#if busy}<span class="spinner"></span>{/if} ✓ Проверить
    </button>
  </div>
  {#if result}
    <div class={"qp-score " + (result.passed ? "pass" : "warn")}>
      <strong>{score ?? "?"}/100</strong> · {result.passed ? "готово" : "нужна правка"}{result.repair?.applied ? " · repair применён" : ""}
    </div>
  {/if}
  {#if result?.scorecard?.summary}
    <div class="qp-summary">{result.scorecard.summary}</div>
  {/if}
  {#if issues.length}
    <details class="rs-log f-log">
      <summary>замечания · {issues.length}</summary>
      <div class="rs-log-lines">
        {#each issues.slice(0, 6) as issue, i (i)}
          <div><b>{issue.severity || "minor"}</b>: {issue.problem || "без описания"}</div>
        {/each}
      </div>
    </details>
  {/if}
  {#if result?.repair?.error}
    <div class="qp-error">repair: {result.repair.error}</div>
  {/if}
  <IrPreview class="f-preview" ir={data.ir} height={160} empty="Подключите IR и запустите проверку" />
  <NodeStatus {id} />
  <OutPorts type="qualitypass" />
</NodeShell>
