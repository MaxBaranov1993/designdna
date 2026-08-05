import type { ChangeEvent } from "react";
import type { NodeProps } from "@xyflow/react";
import { useFlowStore } from "../flow/store";
import { toast } from "../flow/toast";
import type { ReferenceFlowNode } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { InPorts, OutPorts } from "./PortHandles";

/* «Референс» — живая нода: изображение + описание стиля (уходит в текстовый провод).
 * Контролы — зеркало bodyHtml/wireNodeEvents (nodes.js:169-177, 371-388). */
export function ReferenceNode({ id, data, selected }: NodeProps<ReferenceFlowNode>) {
  const setNodeData = useFlowStore((s) => s.setNodeData);
  const propagate = useFlowStore((s) => s.propagate);

  const onFile = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files && e.target.files[0];
    if (!f) return;
    const rd = new FileReader();
    rd.onload = () => setNodeData(Number(id), { image: String(rd.result), fileName: f.name });
    rd.readAsDataURL(f);
    e.target.value = "";
  };

  const onDecompose = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.checked) {
      // разбор на компоненты требует vision-API (runDecompose) — подключается в Фазе B2
      toast("Разбор референса на компоненты появится в Фазе B2");
      return;
    }
    setNodeData(Number(id), { decomposed: false });
  };

  return (
    <NodeShell id={id} type="reference" selected={selected}>
      <InPorts type="reference" />
      {data.image ? <img className="ref-img" alt="референс" src={data.image} /> : null}
      <label className="ref-drop nodrag">
        {data.fileName || "Кликните, чтобы выбрать скриншот/изображение"}
        <input type="file" accept="image/*" className="f-file" hidden onChange={onFile} />
      </label>
      <textarea
        className="f-brief nodrag nowheel"
        placeholder="Описание стиля / что взять из референса (уходит в провод)"
        value={data.brief}
        onChange={(e) => {
          setNodeData(Number(id), { brief: e.target.value });
          propagate(Number(id));
        }}
      />
      <label className="ref-decompose nodrag">
        <input type="checkbox" className="f-decompose" checked={!!data.decomposed} onChange={onDecompose} />
        <span>Разбить на компоненты</span>
      </label>
      <NodeStatus id={id} />
      <OutPorts type="reference" />
    </NodeShell>
  );
}
