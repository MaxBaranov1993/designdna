import {
  Background,
  BackgroundVariant,
  ReactFlow,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
} from "@xyflow/react";
import type { Edge } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { Button } from "./components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./components/ui/card";
import { PromptNode } from "./nodes/PromptNode";
import type { FlowNode } from "./flow/types";

// Реестр кастомных нод — вне компонента, чтобы ссылка не пересоздавалась на рендер
const nodeTypes = { prompt: PromptNode };

const initialNodes: FlowNode[] = [
  {
    id: "prompt-1",
    type: "prompt",
    position: { x: 120, y: 140 },
    data: { label: "Промпт", value: "" },
  },
];

function EditorCanvas() {
  const [nodes, , onNodesChange] = useNodesState<FlowNode>(initialNodes);
  const [edges, , onEdgesChange] = useEdgesState<Edge>([]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      nodeTypes={nodeTypes}
      fitView
    >
      <Background variant={BackgroundVariant.Dots} gap={24} size={1.5} color="#3f3f46" />
    </ReactFlow>
  );
}

export default function App() {
  return (
    <div className="flex h-full flex-col">
      {/* Топбар: название + заглушки Экспорт/Импорт (логика в следующих фазах) */}
      <header className="flex h-12 shrink-0 items-center justify-between border-b bg-background px-4">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold">DesignAI</span>
          <span className="text-xs text-muted-foreground">нодовый редактор</span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm">
            Импорт
          </Button>
          <Button variant="outline" size="sm">
            Экспорт
          </Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <main className="min-w-0 flex-1">
          <ReactFlowProvider>
            <EditorCanvas />
          </ReactFlowProvider>
        </main>

        {/* Панель инспектора — заглушка Фазы A */}
        <aside className="w-72 shrink-0 overflow-y-auto border-l p-4">
          <Card>
            <CardHeader>
              <CardTitle>Инспектор</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs leading-relaxed text-muted-foreground">
                Выберите ноду на канвасе — её свойства появятся здесь. В Фазе A панель
                заглушка.
              </p>
            </CardContent>
          </Card>
        </aside>
      </div>
    </div>
  );
}
