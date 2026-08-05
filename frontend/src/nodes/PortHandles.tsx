import { Handle, Position } from "@xyflow/react";
import { portsOfNode } from "../flow/ports";
import type { AnyNodeData, NodeType } from "../flow/types";
import { cn } from "../lib/utils";

/* Входные порты — строки слева (зеркало .port-row.in). У mix входы динамические
 * и рендерятся прямо в MixNode вместе со слайдерами весов. */
export function InPorts({ type, data }: { type: NodeType; data?: AnyNodeData }) {
  if (type === "mix") return null;
  return (
    <>
      {portsOfNode({ type, data }).in.map((p) => (
        <div key={p.name} className="port-row in" data-port={p.name} data-kind={p.kind}>
          <Handle
            id={p.name}
            type="target"
            position={Position.Left}
            className={cn("port-dot", "pp-in-" + p.name, p.kind === "ir" && "port-ir")}
          />
          <span className="plabel">{p.label}</span>
        </div>
      ))}
    </>
  );
}

/* Выходные порты — строки справа (зеркало .port-row.out) */
export function OutPorts({ type, data }: { type: NodeType; data?: AnyNodeData }) {
  return (
    <>
      {portsOfNode({ type, data }).out.map((p) => (
        <div key={p.name} className="port-row out" data-port={p.name} data-kind={p.kind}>
          <span className="plabel">{p.label}</span>
          <Handle
            id={p.name}
            type="source"
            position={Position.Right}
            className={cn("port-dot", "pp-out-" + p.name, p.kind === "ir" && "port-ir")}
          />
        </div>
      ))}
    </>
  );
}
