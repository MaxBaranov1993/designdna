import { useState } from "react";
import { Handle, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";
import type { PromptFlowNode } from "../flow/types";

// Кастомная нода «Промпт»: текстовый ввод + выходной handle справа.
export function PromptNode({ data, selected }: NodeProps<PromptFlowNode>) {
  // Фаза A: значение живёт в локальном состоянии ноды, стор графа подключится позже
  const [value, setValue] = useState(data.value ?? "");

  return (
    <div
      className={
        "w-64 rounded-lg border bg-card text-card-foreground shadow-md " +
        (selected ? "border-primary" : "border-border")
      }
    >
      <div className="flex items-center justify-between border-b px-3 py-2">
        <span className="text-xs font-semibold">{data.label}</span>
        <span className="text-[10px] uppercase tracking-wide text-muted-foreground">text</span>
      </div>
      <div className="p-3">
        {/* nodrag/nowheel: ввод и скролл в textarea не должны двигать канвас */}
        <textarea
          className="nodrag nowheel h-24 w-full resize-none rounded-md border border-input bg-background p-2 text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          placeholder="Опишите, что сгенерировать…"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
      </div>
      <Handle
        type="source"
        position={Position.Right}
        className="!h-3 !w-3 !border-background !bg-primary"
      />
    </div>
  );
}
