<script lang="ts">
  import type { NodeProps } from "@xyflow/svelte";
  import { flow } from "../flow/state";
  import { toast } from "../flow/toast";
  import type { ReferenceFlowNode } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";

  /* «Референс» — живая нода: изображение + описание стиля (уходит в текстовый провод).
   * Контролы — зеркало bodyHtml/wireNodeEvents (nodes.js:169-177, 371-388). */
  let { id, data, selected }: NodeProps<ReferenceFlowNode> = $props();

  const onFile = (e: Event) => {
    const input = e.currentTarget as HTMLInputElement;
    const f = input.files && input.files[0];
    if (!f) return;
    const rd = new FileReader();
    rd.onload = () => $flow.setNodeData(Number(id), { image: String(rd.result), fileName: f.name });
    rd.readAsDataURL(f);
    input.value = "";
  };

  const onDecompose = (e: Event) => {
    if ((e.currentTarget as HTMLInputElement).checked) {
      // разбор на компоненты требует vision-API (runDecompose) — подключается в Фазе B2
      toast("Разбор референса на компоненты появится в Фазе B2");
      return;
    }
    $flow.setNodeData(Number(id), { decomposed: false });
  };
</script>

<NodeShell {id} type="reference" {selected}>
  <InPorts type="reference" />
  {#if data.image}
    <img class="ref-img" alt="референс" src={data.image} />
  {/if}
  <label class="ref-drop nodrag">
    {data.fileName || "Кликните, чтобы выбрать скриншот/изображение"}
    <input type="file" accept="image/*" class="f-file" hidden onchange={onFile} />
  </label>
  <textarea
    class="f-brief nodrag nowheel"
    placeholder="Описание стиля / что взять из референса (уходит в провод)"
    value={data.brief}
    oninput={(e) => {
      $flow.setNodeData(Number(id), { brief: e.currentTarget.value });
      $flow.propagate(Number(id));
    }}
  ></textarea>
  <label class="ref-decompose nodrag">
    <input type="checkbox" class="f-decompose" checked={!!data.decomposed} onchange={onDecompose} />
    <span>Разбить на компоненты</span>
  </label>
  <NodeStatus {id} />
  <OutPorts type="reference" />
</NodeShell>
