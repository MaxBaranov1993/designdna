<script lang="ts">
  import type { AssetRun } from "../flow/generator-assets";
  let { runs = [], busy = false, onRetry, generationStartedAt, currentResult = true }: { runs?: AssetRun[]; busy?: boolean; onRetry?: (id?: string) => void; generationStartedAt?: number; currentResult?: boolean } = $props();
  let latest = $derived(runs.at(-1));
  let current = $derived(currentResult && (!generationStartedAt || !latest?.generationStartedAt || latest.generationStartedAt === generationStartedAt));
  const labels = { planned: "Pending", running: "Creating", complete: "Done", failed: "Retry needed" };
</script>

{#if latest}
  <details class="asset-history nodrag" data-asset-history>
    <summary>{current ? `Images · ${latest.plan.slots.filter(slot => slot.status === "complete").length}/${latest.plan.slots.length}` : `Image history · ${runs.length}`}</summary>
    {#if current && latest.status !== "complete" && onRetry}
      <button class="dna-btn-ghost" disabled={busy} onclick={() => onRetry?.()}>{latest.verificationError && latest.plan.slots.every(slot => slot.status === "complete") ? "Retry image verification" : "Continue creating images"}</button>
    {/if}
    {#each [...runs].reverse() as run (run.id)}
      <details class="asset-run" open={run.id === latest.id}>
        <summary>{new Date(run.startedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · {run.status === "complete" ? "Done" : run.status === "running" && busy ? "Running" : "Incomplete"}</summary>
        {#if run.verificationError}<p>Completed images are saved. Verification did not finish: {run.verificationError}</p>{/if}
        {#each run.plan.slots as slot (slot.id)}
          <div class="asset-slot" data-asset-id={slot.id} data-asset-status={slot.status}>
            {#if slot.result}<img src={slot.result.src} alt={slot.subject} />{/if}
            <div><strong>{slot.subject}</strong><small>{labels[slot.status]} · variant {slot.variant + 1}{slot.result ? ` · ${slot.result.width}×${slot.result.height}` : ""}</small>
              {#if slot.error}<p>{slot.error}</p>{/if}
              {#if current && run.id === latest.id && slot.status !== "complete" && onRetry}<button class="dna-btn-ghost" disabled={busy} onclick={() => onRetry?.(slot.id)}>Retry image</button>{/if}
            </div>
          </div>
        {/each}
        {#if run.quality?.length}
          <details><summary>Asset verification</summary>
            {#each run.quality as evidence, index}
              <p>Variant {index + 1}: {evidence?.status === "pass" ? "files verified" : evidence?.status === "fail" ? "errors found" : "not verified"}{evidence ? ` · text fields in IR: ${evidence.nativeTextCount}` : ""}</p>
              {#each [...(evidence?.errors || []), ...(evidence?.warnings || [])] as issue}<p>{issue.problem}</p>{/each}
            {/each}
          </details>
        {/if}
      </details>
    {/each}
  </details>
{/if}

<style>
  .asset-history { margin: 8px 12px; font-size: 12px; }
  summary { cursor: pointer; padding: 6px 0; }
  .asset-run { margin-top: 8px; }
  .asset-slot { display: flex; align-items: flex-start; gap: 8px; padding: 8px 0; border-top: 1px solid var(--border, #ffffff18); }
  .asset-slot img { width: 48px; height: 48px; object-fit: contain; border-radius: 4px; }
  .asset-slot > div { min-width: 0; }
  strong { display: block; font-weight: 500; overflow-wrap: anywhere; }
  small { display: block; opacity: .7; margin-top: 4px; }
  p { font-size: 11px; margin: 4px 0; overflow-wrap: anywhere; }
</style>
