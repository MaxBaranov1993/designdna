import type { ReactNode } from "react";
import { NODE_DEFS } from "../flow/ports";
import { useFlowStore } from "../flow/store";
import type { NodeType } from "../flow/types";
import { cn } from "../lib/utils";

/* Общий каркас ноды: шапка (иконка, название, ✕) и тело.
 * Зеркало .node-head/.node-body legacy; классы n-<type> и f-* сохранены для тестов. */
export function NodeShell({
  id,
  type,
  selected,
  children,
}: {
  id: string;
  type: NodeType;
  selected?: boolean;
  children: ReactNode;
}) {
  const def = NODE_DEFS[type];
  const deleteNode = useFlowStore((s) => s.deleteNode);
  return (
    <div className={cn("fnode node", "n-" + type, selected && "selected")} style={{ width: def.w }}>
      <div className="node-head">
        <span className="n-icon">{def.icon}</span>
        <span className="n-title">{def.title}</span>
        <button className="n-x nodrag" title="Удалить ноду (Del)" onClick={() => deleteNode(Number(id))}>
          ✕
        </button>
      </div>
      <div className="node-body">{children}</div>
    </div>
  );
}

/* Статусная строка ноды — зеркало .n-status (runtime, в сейв не попадает) */
export function NodeStatus({ id }: { id: string }) {
  const status = useFlowStore((s) => s.statuses[Number(id)]);
  return <div className={cn("n-status", status?.kind)}>{status?.text || ""}</div>;
}
