<script lang="ts">
  import { captureNodeUpload } from "../flow/store";
  import type { NodeProps } from "@xyflow/svelte";
  import { flow, flowEdges, flowNodes } from "../flow/state";
  import { pullInput } from "../flow/dataflow";
  import { isImageSource } from "../flow/image-assets";
  import { commitNodeText, flushNodeText } from "../flow/textcommit";
  import type { ReferenceFlowNode } from "../flow/types";
  import NodeShell from "./NodeShell.svelte";
  import NodeStatus from "./NodeStatus.svelte";
  import InPorts from "./InPorts.svelte";
  import OutPorts from "./OutPorts.svelte";

  /* «Референс» — картинка как герой (Weavy File node): своя загрузка или
   * картинка по проводу из ноды «Изображение»; короткое описание стиля под
   * ней; «Разбить на компоненты» живёт в инспекторе. */
  let { id, data, selected }: NodeProps<ReferenceFlowNode> = $props();

  let selfNode = $derived($flowNodes.find((node) => node.id === id) || null);
  let wiredImage = $derived.by(() => {
    if (!selfNode) return null;
    const value = pullInput($flowNodes, $flowEdges, selfNode, "image");
    return isImageSource(value) ? value : null;
  });
  let shownImage = $derived(data.image || wiredImage);

  const onFile = (e: Event) => {
    const input = e.currentTarget as HTMLInputElement;
    const f = input.files && input.files[0];
    if (!f) return;
    const applyUpload = captureNodeUpload(Number(id));
    const rd = new FileReader();
    rd.onload = () => applyUpload({ image: String(rd.result), fileName: f.name });
    rd.readAsDataURL(f);
    input.value = "";
  };
</script>

<NodeShell {id} type="reference" {selected}>
  {#snippet footer()}
    <div class="foot-left">
      <label class="btn-node small add-input nodrag" style="cursor: pointer">
        {data.image ? "Заменить изображение" : "+ Изображение"}
        <input type="file" accept="image/*" class="f-file" hidden onchange={onFile} />
      </label>
    </div>
    <div class="foot-right"><span class="foot-hint">{data.image ? data.fileName || "" : wiredImage ? "по проводу" : ""}</span></div>
  {/snippet}
  <InPorts type="reference" />
  {#if shownImage}
    <div class="n-hero nodrag"><img class="ref-img" alt="референс" src={shownImage} /></div>
  {:else}
    <label class="ref-drop nodrag">
      Перетащите или выберите скриншот
      <input type="file" accept="image/*" hidden onchange={onFile} />
    </label>
  {/if}
  <textarea
    class="f-brief nodrag nowheel"
    rows="2"
    placeholder="Что взять из референса (уходит в провод «стиль»)"
    value={data.brief}
    oninput={(e) => {
      const value = e.currentTarget.value;
      commitNodeText(`reference:${id}:brief`, () => {
        $flow.setNodeData(Number(id), { brief: value });
        $flow.propagate(Number(id));
      });
    }}
    onblur={() => flushNodeText(`reference:${id}:brief`)}
  ></textarea>
  <NodeStatus {id} />
  <OutPorts type="reference" />
</NodeShell>

<style>
  .n-hero .ref-img { display: block; width: 100%; max-height: 260px; object-fit: contain; border: 0; border-radius: 0; background: #0d0d0f; }
  .f-brief { min-height: 44px; }
  .foot-hint { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--dna-dim); font-size: 10.5px; }
</style>
