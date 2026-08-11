import type { NodeProps } from "@xyflow/react";
import { useFlowStore } from "../flow/store";
import type { StyleDnaFlowNode } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { InPorts, OutPorts } from "./PortHandles";

export function StyleDnaNode({ id, data, selected }: NodeProps<StyleDnaFlowNode>) {
  const runNode = useFlowStore((s) => s.runNode);
  const busy = useFlowStore((s) => !!s.busy[Number(id)]);
  const tokensText = data.tokens ? JSON.stringify(data.tokens, null, 2) : "";
  return (
    <NodeShell id={id} type="styledna" selected={selected}>
      <InPorts type="styledna" />
      <div className="ctl-row">
        <button className="btn-node primary small f-run nodrag" disabled={busy} onClick={() => runNode(Number(id))}>
          {busy ? <span className="spinner" /> : null} Extract DNA
        </button>
      </div>
      {data.summary ? <pre className="dna-summary">{data.summary}</pre> : <div className="bp-hint">IR или tokens → палитра, шрифты, радиусы, отступы</div>}
      {tokensText ? (
        <details className="rs-log f-log">
          <summary>tokens</summary>
          <div className="rs-log-lines">
            <pre>{tokensText.slice(0, 1400)}</pre>
          </div>
        </details>
      ) : null}
      <NodeStatus id={id} />
      <OutPorts type="styledna" data={data} />
    </NodeShell>
  );
}
