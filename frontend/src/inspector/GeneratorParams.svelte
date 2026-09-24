<script lang="ts">
  import ProviderPicker from "../components/ProviderPicker.svelte";
  import { flow, flowBusy, flowDesignSystemPicker, flowDesignSystems, flowEdges, flowNodes } from "../flow/state";
  import { pullInput } from "../flow/dataflow";
  import { pinnedDesignSystemRef } from "../flow/store";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import type { FlowNode, GeneratorNodeData } from "../flow/types";

  /* Generator settings: prompt, model, surface, direction. Design system comes
   * from the purple wire on the node — no duplicate picker here. */
  let { id, data }: { id: number; data: GeneratorNodeData & Record<string, any> } = $props();

  let busy = $derived(!!$flowBusy[id]);
  let effort = $derived(["medium", "high", "max"].includes(data.effort) ? data.effort : "medium");
  let count = $derived(Math.max(1, Math.min(2, Number(data.count) || 1)));
  let activeIr = $derived(data.variants?.length ? data.variants[data.active] || null : null);

  let selfNode = $derived(($flowNodes.find((n) => Number(n.id) === id) || null) as FlowNode | null);
  let wiredDs = $derived.by(() => {
    if (!selfNode) return null;
    const raw = pullInput($flowNodes, $flowEdges, selfNode, "designSystem") as
      { systemId?: string; status?: string; name?: string } | null;
    return raw && raw.systemId ? raw : null;
  });
  let pinnedRef = $derived(pinnedDesignSystemRef(data as Record<string, unknown>, $flowDesignSystems, $flowDesignSystemPicker));
  let hasDesignSystem = $derived(!!wiredDs || (!!pinnedRef && String(data.designSystemSelection || "") !== "none"));
  let usageMode = $derived(String(data.designSystemUsageMode || $flowDesignSystemPicker?.usageMode || "strict"));

  const surfaceOptions = [
    ["auto", "Infer from task"], ["landing", "Landing page"], ["catalog", "Search and catalog"],
    ["detail", "Detail page"], ["checkout", "Booking and checkout"], ["dashboard", "Dashboard and analytics"],
    ["form", "Form and settings"], ["editor", "Editor"], ["ai-workspace", "AI interface"],
    ["article", "Article and journal"], ["feed", "Feed"], ["component", "Single component"], ["diagram", "Diagram and infographic"],
  ];
  const styleOptions = [
    ["auto", "From task and design system"], ["minimal", "Quiet minimalism"], ["enterprise", "Information-focused"],
    ["marketplace", "Search-first"], ["editorial", "Editorial"], ["swiss", "Strict grid"],
    ["product-led", "Product showcase"], ["luxury", "Restrained and tangible"], ["organic", "Material"],
    ["playful", "Illustrative"], ["brutal", "Poster"], ["industrial", "Technical"],
    ["soft-pastel", "Soft palette"], ["bento", "Modular"], ["glass", "Layered"],
    ["immersive", "Immersive"], ["retro", "Retro"],
  ];
</script>
<div class="dna-insp-fields">
  <div class="dna-field">
    <div class="dna-field-cap">Custom prompt</div>
    <textarea
      rows="4"
      placeholder="Used when nothing is connected to the Prompt input"
      value={data.ownPrompt}
      oninput={(e) => {
        const value = e.currentTarget.value;
        commitNodeText(`generator:${id}:ownPrompt`, () => $flow.setNodeData(id, { ownPrompt: value }));
      }}
      onblur={() => flushNodeText(`generator:${id}:ownPrompt`)}
    ></textarea>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Model and effort</div>
    <ProviderPicker provider={data.provider || "openai"} {effort} onChange={(next) => $flow.setNodeData(id, next)} />
  </div>
  <div class="dna-insp-row">
    <div class="dna-field">
      <div class="dna-field-cap">Variants</div>
      <select value={String(count)} onchange={(e) => $flow.setNodeData(id, { count: Number(e.currentTarget.value) })}>
        <option value="1">1</option>
        <option value="2">2</option>
      </select>
    </div>
    <div class="dna-field">
      <div class="dna-field-cap">Screen type</div>
      <select disabled={busy} value={data.surface || "auto"} onchange={(e) => $flow.setNodeData(id, { surface: e.currentTarget.value, selectedDirection: "all", directions: [] })}>
        {#each surfaceOptions as option}<option value={option[0]}>{option[1]}</option>{/each}
      </select>
    </div>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Visual direction</div>
    <select disabled={busy || hasDesignSystem} value={data.designStyle || "auto"} onchange={(e) => $flow.setNodeData(id, { designStyle: e.currentTarget.value, selectedDirection: "all" })}>
      {#each styleOptions as option}<option value={option[0]}>{option[1]}</option>{/each}
    </select>
    <div class="dna-field-hint">{hasDesignSystem ? "Style comes from the Design system wire on the node." : "Connect UI Kit → Design system on the node, or pick a visual direction here."}</div>
  </div>
  
  {#if hasDesignSystem}
    <div class="dna-field">
      <div class="dna-field-cap">DS usage</div>
      <select value={usageMode} onchange={(e) => $flow.setNodeData(id, { designSystemUsageMode: e.currentTarget.value })}>
        <option value="strict">strict — masters and tokens only</option>
        <option value="extend">extend — masters + new content</option>
        <option value="style-only">style-only — tokens and character</option>
      </select>
      <div class="dna-field-hint">Design system is connected on the graph. This only sets how strictly to follow it.</div>
    </div>
  {/if}

  <div class="dna-field">
    <div class="dna-field-cap">Images in the layout</div>
    <select disabled={busy} value={data.assetMode || "auto"} onchange={(e) => $flow.setNodeData(id, { assetMode: e.currentTarget.value as "auto" | "codex" | "off" })}>
      <option value="auto">Through node provider</option>
      <option value="codex">GPT Image · Codex account</option>
      <option value="off">I will add images manually</option>
    </select>
    <div class="dna-field-hint">GPT Image creates separate images; text remains editable. With Claude, you can select Codex separately for images.</div>
  </div>
  <div class="dna-field">
    <div class="dna-field-cap">Reference image role</div>
    <select disabled={busy} value={data.referenceRole || "inherit"} onchange={(e) => $flow.setNodeData(id, { referenceRole: e.currentTarget.value === "inherit" ? undefined : e.currentTarget.value as NonNullable<GeneratorNodeData["referenceRole"]> })}>
      <option value="inherit">From Reference node</option>
      <option value="style">Style</option><option value="composition">Composition</option><option value="reproduce">Reproduction</option>
    </select>
    <div class="dna-field-hint">Images without a role default to style. IR and text references work as before.</div>
  </div>
  <label class="dna-insp-check">
    <input type="checkbox" disabled={busy || data.assetMode === "off"} checked={data.conceptMode === "on"} onchange={(e) => $flow.setNodeData(id, { conceptMode: e.currentTarget.checked ? "on" : "off" })} />
    <span>Create a visual sketch before building</span>
  </label>
  <div class="dna-field-hint">A separate GPT Image request. Reproduction stays anchored to the original. The sketch is saved in history.</div>
  <label class="dna-insp-check">
    <input type="checkbox" disabled={busy || data.assetMode === "off"} checked={data.assetConsistency !== "independent"} onchange={(e) => $flow.setNodeData(id, { assetConsistency: e.currentTarget.checked ? "series" : "independent" })} />
    <span>Shared reference for an image series</span>
  </label>
  <div class="dna-field">
    <div class="dna-field-cap">Active variant</div>
    <div class="dna-insp-row">
      <button class="dna-btn-ghost" disabled={!activeIr} onclick={() => $flow.sendToNode(id, "edit")}>→ Editor</button>
      <button class="dna-btn-ghost" disabled={!activeIr} onclick={() => $flow.sendToNode(id, "reference")}>→ Reference</button>
      <button class="dna-btn-ghost" disabled={busy || !activeIr} title="Remember as successful" onclick={() => void $flow.recordVariantTaste(id, "accepted")}>✓ Accept</button>
      <button class="dna-btn-ghost" disabled={busy || !activeIr} title="Remember as unsuccessful" onclick={() => void $flow.recordVariantTaste(id, "rejected")}>× Reject</button>
    </div>
    <button class="dna-btn-ghost" disabled={busy || !activeIr} title="Turn this variant into a design system" onclick={() => void $flow.promoteVariantToDesignSystem(id)}>◈ Pin style as DS</button>
  </div>
</div>
