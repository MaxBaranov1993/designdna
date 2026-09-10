<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import ResultAssets from "../components/ResultAssets.svelte";
  import { flow, flowBusy } from "../flow/state";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
import DesignSystemPicker from "../components/DesignSystemPicker.svelte";
  import ProviderPicker from "../components/ProviderPicker.svelte";
  import type { ReskinFlowNode, ReskinMask } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";

  /* Подписи чекбоксов маски — что модели разрешено менять (остальное merge-back
   * принудительно вернёт из входного IR, server.py _MASK_LABELS) */
  const MASK_FIELDS: { key: keyof ReskinMask; label: string }[] = [
    { key: "colors", label: "цвета" },
    { key: "fonts", label: "шрифты" },
    { key: "radii", label: "радиусы" },
    { key: "shadows", label: "тени" },
    { key: "texts", label: "тексты" },
    { key: "images", label: "изображения" },
  ];

  /* «Reskin» — controlled AI-нода (см. docs/NODES.md): вход ir
   * (обязателен) и tokens (опционально) приходят проводами (pull-модель),
   * POST /api/reskin {ir, prompt, tokens?, mask}. Пустая маска запуск блокирует.
   * Результат: превью IR + свёрнутый журнал merge-back со счётчиком записей. */
  let { id, data, selected }: NodeProps<ReskinFlowNode> = $props();

  let busy = $derived(!!$flowBusy[Number(id)]);
  let maskAny = $derived(MASK_FIELDS.some((f) => data.mask[f.key]));
</script>

<NodeShell {id} type="reskin" {selected}>
  <InPorts type="reskin" />
  <textarea
    class="f-prompt nodrag nowheel"
    placeholder="Пожелания по новому стилю"
    value={data.prompt}
    oninput={(e) => {
      const value = e.currentTarget.value;
      commitNodeText(`reskin:${id}:prompt`, () => $flow.setNodeData(Number(id), { prompt: value }));
    }}
    onblur={() => flushNodeText(`reskin:${id}:prompt`)}
  ></textarea>
  <div class="rs-mask">
    {#each MASK_FIELDS as f (f.key)}
      <label class="nodrag" title={"Разрешить менять: " + f.label}>
        <input
          type="checkbox"
          class={"f-mask-" + f.key}
          checked={data.mask[f.key]}
          onchange={(e) =>
            $flow.setNodeData(Number(id), { mask: { ...data.mask, [f.key]: e.currentTarget.checked } })
          }
        />
        {f.label}
      </label>
    {/each}
  </div>
  <DesignSystemPicker selection={(data as any).designSystemSelection || "inherit"} usageMode={(data as any).designSystemUsageMode || "strict"} fixtureProfile={(data as any).designSystemFixture || "typical"} onChange={(v, meta) => $flow.setNodeData(Number(id), { designSystemSelection: v, designSystemUsageMode: meta?.usageMode, designSystemFixture: meta?.fixtureProfile } as any)} />
  <div class="ctl-row">
    <ProviderPicker
      provider={data.provider || "openai"}
      effort={data.effort || "medium"}
      onChange={(next) => $flow.setNodeData(Number(id), next)}
    />
    <button
      class="btn-node primary small f-run nodrag"
      style="margin-left: auto"
      disabled={busy || !maskAny}
      title={!maskAny ? "Пустая маска: отметьте, что разрешено менять" : undefined}
      onclick={() => $flow.runNode(Number(id))}
    >
      {#if busy}<span class="spinner"></span>{/if} ✦ Reskin
    </button>
  </div>
  {#if !maskAny}
    <div class="rs-hint">Пустая маска: запуск заблокирован (IR вернулся бы без изменений)</div>
  {/if}
  <IrPreview class="f-preview" ir={data.ir} height={160} empty="Результат появится после запуска" />
  {#if data.log.length}
    <details class="rs-log f-log">
      <summary>журнал merge-back · {data.log.length}</summary>
      <div class="rs-log-lines">
        {#each data.log.slice(-8) as line, i (i)}
          <div>{line}</div>
        {/each}
      </div>
    </details>
  {/if}
  <NodeStatus {id} />
  <ResultAssets {id} type="reskin" {data} />
  <OutPorts type="reskin" />
</NodeShell>
