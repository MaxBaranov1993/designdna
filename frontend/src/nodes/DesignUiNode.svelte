<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import { flow } from "../flow/state";
  import type { DesignUiFlowNode } from "../flow/types";
  import InPorts from "./InPorts.svelte";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import OutPorts from "./OutPorts.svelte";

  let { id, data, selected }: NodeProps<DesignUiFlowNode> = $props();

  let components = $derived(data.artifact?.components || []);
  let screens = $derived(data.artifact?.screens || []);
  let foundationGroups = $derived(data.artifact?.foundations?.groups || []);
  let selectedIndex = $derived(Math.min(Math.max(0, data.selectedComponent || 0), Math.max(0, components.length - 1)));
  let component = $derived(components[selectedIndex] || null);
  let stateCount = $derived(component ? Object.keys(component.states || {}).length : 0);
  let viewports = $derived(component ? Object.entries(component.responsive || {}) : []);

  const chooseComponent = (index: number) => {
    $flow.setNodeData(Number(id), { selectedComponent: index });
  };

  const percent = (value: unknown) => {
    const score = Number(value);
    return Number.isFinite(score) ? `${Math.round(score * 100)}%` : "—";
  };

  const dimension = (value: unknown) => {
    const size = Number(value);
    return Number.isFinite(size) ? Math.round(size).toLocaleString() : "—";
  };
</script>

<NodeShell {id} type="designui" {selected}>
  <InPorts type="designui" />
  {#if data.artifact}
    <div class="du-summary" title={data.artifact.version}>
      <div><span>Screens</span><strong>{data.artifact.summary.screenCount ?? screens.length}</strong></div>
      <div><span>Component sets</span><strong>{data.artifact.summary.componentSetCount ?? data.artifact.summary.componentCount}</strong></div>
      <div><span>Variants</span><strong>{data.artifact.summary.variantCount ?? data.artifact.summary.observedStateCount}</strong></div>
      <div><span>Viewports</span><strong>{data.artifact.summary.viewportCount}</strong></div>
    </div>

    <div class="du-section-label">Foundations</div>
    <div class="du-foundations">
      {#if foundationGroups.length}
        {#each foundationGroups as group (group.key)}
          <span title={group.key}>{group.name}<strong>{group.tokenCount}</strong></span>
        {/each}
      {:else}
        <span>Raw token groups<strong>{Object.keys(data.artifact.foundations.tokens || {}).length}</strong></span>
      {/if}
    </div>

    <div class="du-section-label">Screens</div>
    <div class="du-screens">
      {#each screens as screen (screen.screenKey)}
        <article>
          <header>
            <div>
              <strong>{screen.name}</strong>
              <span>{screen.viewport}{screen.theme ? ` · ${screen.theme}` : ""}</span>
            </div>
            <code>{dimension(screen.size?.width)} × {dimension(screen.size?.height)}</code>
          </header>
          <div class="du-screen-metrics">
            <span>{screen.componentKeys.length} instances</span>
            <span>{screen.metrics.editableLayers ?? screen.metrics.layers ?? 0} layers</span>
            <span>mean {percent(screen.metrics.fidelityMean)}</span>
            <span>min {percent(screen.metrics.fidelityMin)}</span>
          </div>
          <div class="du-hierarchy" title={screen.hierarchy.map((item) => item.name).join(" → ")}>
            {screen.hierarchy.slice(0, 4).map((item) => item.name).join(" → ")}{screen.hierarchy.length > 4 ? " …" : ""}
          </div>
        </article>
      {:else}
        <div class="du-legacy">Reconnect Source to build the screen registry.</div>
      {/each}
    </div>

    <div class="du-section-label">Component Library</div>
    <div class="du-components nodrag" role="tablist" aria-label="Imported components">
      {#each components as item, index (item.componentKey)}
        <button
          type="button"
          role="tab"
          aria-selected={index === selectedIndex}
          class:active={index === selectedIndex}
          onclick={() => chooseComponent(index)}
        >
          <span>{item.name}</span>
          <small>{item.role}</small>
        </button>
      {/each}
    </div>

    {#if component}
      <div class="du-inspector">
        <div class="du-master">
          <div>
            <span class="du-kicker">Master component</span>
            <strong>{component.name}</strong>
          </div>
          <code>{component.master.selector || component.componentKey}</code>
        </div>

        <div class="du-section-label">States · {stateCount}</div>
        <div class="du-states">
          {#each Object.entries(component.states || {}) as [name, state] (name)}
            <span class:measured={state.basis === "measured"}>
              {name}<small>{state.observed ? "observed" : state.basis}</small>
            </span>
          {/each}
        </div>

        <div class="du-section-label">Responsive structure</div>
        <div class="du-viewports">
          {#each viewports as [name, viewport] (name)}
            <div>
              <strong>{name}</strong>
              <span>{dimension(viewport.size?.width)} × {dimension(viewport.size?.height)}</span>
              <span>{viewport.editableLayers ?? viewport.layers ?? 0} layers</span>
              <span>fidelity {percent(viewport.fidelity)}</span>
            </div>
          {/each}
        </div>

        <div class="du-section-label">Quality &amp; Provenance</div>
        <div class="du-provenance">
          <span>{component.quality.gate?.passed === false ? "Quality gate failed" : "Measured source"}</span>
          <code>{component.provenance.parserContractVersion || data.artifact.source.pipelineVersion}</code>
          <span>{component.provenance.nodeStateCount} source nodes</span>
        </div>
        {#if component.quality.warnings.length}
          <div class="du-warning">{component.quality.warnings.join(" · ")}</div>
        {/if}
      </div>
    {/if}
  {:else}
    <div class="du-empty">
      <strong>Connect Source Artifact</strong>
      <span>Foundations → Screens → Component Library → States → Responsive → Provenance</span>
    </div>
  {/if}
  <NodeStatus {id} />
  <OutPorts type="designui" data={data} />
</NodeShell>

<style>
  .du-summary {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 6px;
  }
  .du-summary div,
  .du-viewports > div,
  .du-screens article {
    border: 1px solid var(--flow-border);
    border-radius: 8px;
    background: color-mix(in srgb, var(--flow-surface-2), transparent 10%);
    padding: 7px;
  }
  .du-summary span,
  .du-summary strong,
  .du-viewports span,
  .du-viewports strong,
  .du-screens span,
  .du-screens strong,
  .du-kicker,
  .du-provenance span {
    display: block;
  }
  .du-summary span,
  .du-viewports span,
  .du-screens span,
  .du-kicker,
  .du-provenance span {
    color: var(--flow-muted);
    font-size: 9px;
  }
  .du-summary strong {
    margin-top: 2px;
    color: var(--flow-text);
    font-size: 14px;
  }
  .du-section-label {
    margin: 11px 0 5px;
    color: var(--flow-muted);
    font-size: 9px;
    font-weight: 700;
    letter-spacing: .08em;
    text-transform: uppercase;
  }
  .du-foundations,
  .du-screen-metrics,
  .du-states {
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
  }
  .du-foundations > span,
  .du-states > span {
    border: 1px solid var(--flow-border);
    border-radius: 999px;
    padding: 3px 7px;
    color: var(--flow-text);
    font-size: 9px;
  }
  .du-foundations strong {
    display: inline;
    margin-left: 5px;
    color: #35b8a0;
  }
  .du-screens {
    display: grid;
    gap: 6px;
    max-height: 184px;
    overflow-y: auto;
  }
  .du-screens header,
  .du-master,
  .du-provenance {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .du-screens header strong {
    color: var(--flow-text);
    font-size: 10px;
  }
  .du-screen-metrics {
    margin-top: 6px;
  }
  .du-screen-metrics span {
    border-radius: 999px;
    background: color-mix(in srgb, #35b8a0, transparent 90%);
    padding: 2px 5px;
  }
  .du-hierarchy,
  .du-legacy {
    margin-top: 6px;
    overflow: hidden;
    color: var(--flow-muted);
    font-size: 9px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .du-legacy {
    border: 1px dashed var(--flow-border);
    border-radius: 8px;
    padding: 8px;
  }
  .du-components {
    display: flex;
    gap: 6px;
    overflow-x: auto;
    padding-bottom: 3px;
  }
  .du-components button {
    min-width: 104px;
    border: 1px solid var(--flow-border);
    border-radius: 8px;
    background: var(--flow-surface-2);
    color: var(--flow-text);
    padding: 7px 8px;
    text-align: left;
  }
  .du-components button.active {
    border-color: #35b8a0;
    box-shadow: inset 0 0 0 1px #35b8a0;
  }
  .du-components span,
  .du-components small {
    display: block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .du-components small {
    margin-top: 2px;
    color: var(--flow-muted);
    font-size: 9px;
  }
  .du-inspector {
    margin-top: 7px;
    border: 1px solid var(--flow-border);
    border-radius: 10px;
    padding: 9px;
  }
  .du-master strong,
  .du-kicker {
    display: block;
  }
  code {
    max-width: 150px;
    overflow: hidden;
    color: #35b8a0;
    font-size: 9px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .du-states > span.measured {
    border-color: color-mix(in srgb, #35b8a0, transparent 35%);
  }
  .du-states small {
    margin-left: 4px;
    color: var(--flow-muted);
  }
  .du-viewports {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 5px;
  }
  .du-viewports strong {
    margin-bottom: 3px;
    color: var(--flow-text);
    font-size: 10px;
    text-transform: capitalize;
  }
  .du-provenance {
    border-top: 1px solid var(--flow-border);
    padding-top: 8px;
  }
  .du-warning {
    margin-top: 7px;
    border-radius: 6px;
    background: color-mix(in srgb, #d6a13b, transparent 86%);
    color: #d6a13b;
    padding: 6px;
    font-size: 9px;
  }
  .du-empty {
    display: grid;
    gap: 5px;
    border: 1px dashed #35b8a0;
    border-radius: 10px;
    padding: 16px 12px;
    text-align: center;
  }
  .du-empty span {
    color: var(--flow-muted);
    font-size: 10px;
  }
</style>
