import type { NodeProps } from "@xyflow/react";
import { useFlowStore } from "../flow/store";
import type { PromptFlowNode } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { OutPorts } from "./PortHandles";

/* «Промпт» — живая текстовая нода: каждый ввод пишет data.text,
 * вызывает propagate() и автосейв (зеркало nodes.js:364-367). */
export function PromptNode({ id, data, selected }: NodeProps<PromptFlowNode>) {
  const setNodeData = useFlowStore((s) => s.setNodeData);
  const propagate = useFlowStore((s) => s.propagate);
  return (
    <NodeShell id={id} type="prompt" selected={selected}>
      <textarea
        className="f-text nodrag nowheel"
        placeholder="Что нужно сделать? Например: шапка маркетплейса объявлений…"
        value={data.text}
        onChange={(e) => {
          setNodeData(Number(id), { text: e.target.value });
          propagate(Number(id));
        }}
      />
      <NodeStatus id={id} />
      <OutPorts type="prompt" />
    </NodeShell>
  );
}
