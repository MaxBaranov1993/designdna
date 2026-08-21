<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import IrPreview from "../components/IrPreview.svelte";
  import { flow } from "../flow/state";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
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

  let busy = $derived(!!$flow.busy[Number(id)]);
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
  <div class="ctl-row">
    <select
      class="f-provider-select nodrag"
      value={data.provider || "auto"}
      onchange={(e) => $flow.setNodeData(Number(id), { provider: e.currentTarget.value })}
      aria-label="Модель рестайла"
    >
      <option value="auto">Auto · аккаунт</option>
      <option value="kimi">Kimi K3</option>
      <option value="openai">GPT-5.6-sol</option>
      <option value="glm">GLM-5.3</option>
    </select>
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
  <OutPorts type="reskin" />
</NodeShell>
