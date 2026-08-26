<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import { flow, flowBusy } from "../flow/state";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
import DesignSystemPicker from "../components/DesignSystemPicker.svelte";
  import type { GeneratorFlowNode } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";

  /* «Генератор» — run-based: бриф тянет из входов prompt/style (pull-based,
   * fallback ownPrompt), POST /api/generate (payload — зеркало runGenerator,
   * nodes.js:498-518). Варианты — миниатюрами, активный — в IrPreview и на
   * выход ir (outValue) для нод ниже по графу. */
  const PRESETS: { id: string; label: string }[] = [
    { id: "minimal", label: "Minimal" },
    { id: "bento", label: "Bento" },
    { id: "editorial", label: "Editorial" },
    { id: "brutal", label: "Brutal" },
    { id: "glass", label: "Glass" },
  ];

  let { id, data, selected }: NodeProps<GeneratorFlowNode> = $props();

  let busy = $derived(!!$flowBusy[Number(id)]);
  let activeIr = $derived(data.variants.length ? data.variants[data.active] || null : null);
  const desktop = typeof window !== "undefined" && !!window.designDNA;
  let provider = $derived(
    desktop
      ? ["auto", "codex", "kimi", "openai", "glm", "zai", "grok"].includes(data.provider) ? data.provider : "codex"
      : ["kimi", "openai", "glm", "zai", "grok"].includes(data.provider) ? data.provider : "auto",
  );
  let count = $derived(Math.max(1, Math.min(2, Number(data.count) || 1)));
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
    <select
      class="f-provider-select nodrag"
      value={provider}
      onchange={(e) => $flow.setNodeData(Number(id), { provider: e.currentTarget.value })}
      aria-label="Модель генератора"
    >
      {#if desktop}
        <option value="auto">Auto · connected account</option>
        <option value="codex">GPT Codex · ChatGPT</option>
      {:else}
        <option value="auto">Auto · server routing</option>
      {/if}
      <option value="kimi">Kimi K3 · аккаунт</option>
      <option value="openai">GPT-5.6-sol · OpenAI API</option>
      <option value="glm">GLM-5.3 · Zhipu API</option>
      <option value="zai">GLM-5.3 · Z.AI API</option>
      <option value="grok">Grok 4.6 · xAI API</option>
      <option value="zcode">GLM · ZCode (явный ZCODE_CLI)</option>
    </select>
  </div>
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
  <div class="f-presets nodrag">
    {#each PRESETS as p (p.id)}
      <button
        class={"f-preset" + (data.preset === p.id ? " on" : "")}
        title={"Стилевое направление: " + p.label}
        onclick={() => $flow.setNodeData(Number(id), { preset: data.preset === p.id ? "" : p.id })}
      >
        {p.label}
      </button>
    {/each}
  </div>
  {#if data.variants.length}
    <div class="thumbs">
      {#each data.variants as v, i (i)}
        <div
          class={"thumb nodrag" + (i === data.active ? " active" : "")}
          title={"Вариант " + (i + 1)}
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
          <span class="tbadge">{i + 1}</span>
          <IrPreview ir={v} height={96} empty="" />
        </div>
      {/each}
    </div>
  {/if}
  <IrPreview class="f-preview" ir={activeIr} height={180} empty="Варианты появятся после запуска" />
  <DesignSystemPicker selection={(data as any).designSystemSelection || "inherit"} usageMode={(data as any).designSystemUsageMode || "strict"} fixtureProfile={(data as any).designSystemFixture || "typical"} onChange={(v, meta) => $flow.setNodeData(Number(id), { designSystemSelection: v, designSystemUsageMode: meta?.usageMode, designSystemFixture: meta?.fixtureProfile } as any)} />
  <div class="gen-actions">
    <button class="btn-node small f-to-editor nodrag" onclick={() => $flow.sendToNode(Number(id), "edit")}>
      → Editor
    </button>
    <button class="btn-node small f-to-reference nodrag" onclick={() => $flow.sendToNode(Number(id), "reference")}>
      → Reference
    </button>
    <button class="btn-node small nodrag" disabled={busy || !activeIr} onclick={() => void $flow.recordVariantTaste(Number(id), "accepted")}>
      ✓ Принять
    </button>
    <button class="btn-node small nodrag" disabled={busy || !activeIr} onclick={() => void $flow.recordVariantTaste(Number(id), "rejected")}>
      × Отклонить
    </button>
    <button class="btn-node small primary nodrag" disabled={busy || !activeIr} onclick={() => void $flow.promoteVariantToDesignSystem(Number(id))}>
      ◈ Закрепить как стиль
    </button>
  </div>
  <NodeStatus {id} />
  <OutPorts type="generator" />
</NodeShell>
