import type { NodeProps } from "@xyflow/react";
import { IrPreview } from "../components/IrPreview";
import { useFlowStore } from "../flow/store";
import type { BlockParseFlowNode } from "../flow/types";
import { NodeShell, NodeStatus } from "./NodeShell";
import { OutPorts } from "./PortHandles";

/* «BlockParse» — run-based (решение владельца 11, NODES-HOUDINI.md §7):
 * URL + отметка «Это мой сайт» -> POST /api/block-parse {url}. Список блоков —
 * миниатюры IR; чекбокс «зажечь» показывает выходной порт блока (порты только
 * у зажжённых, §7.5-2), порт tokens постоянный. Ошибка блока — в его записи,
 * чекбокс такого блока недоступен. */
export function BlockParseNode({ id, data, selected }: NodeProps<BlockParseFlowNode>) {
  const setNodeData = useFlowStore((s) => s.setNodeData);
  const deleteEdge = useFlowStore((s) => s.deleteEdge);
  const runNode = useFlowStore((s) => s.runNode);
  const busy = useFlowStore((s) => !!s.busy[Number(id)]);

  const toggleLit = (name: string, lit: boolean) => {
    setNodeData(Number(id), {
      blocks: data.blocks.map((b) => (b.name === name ? { ...b, lit } : b)),
    });
    if (!lit) {
      // погасили порт — снимаем его провода (аналог removeMixInput)
      useFlowStore
        .getState()
        .edges.filter((e) => e.source === id && e.sourceHandle === name)
        .forEach((e) => deleteEdge(e.id));
    }
  };

  return (
    <NodeShell id={id} type="blockparse" selected={selected}>
      <input
        type="text"
        className="f-url nodrag"
        placeholder="https://mysite.com/landing"
        value={data.url}
        onChange={(e) => setNodeData(Number(id), { url: e.target.value })}
      />
      <label className="bp-mine nodrag" title="Юридика: разбирать можно только собственные страницы">
        <input
          type="checkbox"
          className="f-mine"
          checked={data.mine}
          onChange={(e) => setNodeData(Number(id), { mine: e.target.checked })}
        />
        Это мой сайт
      </label>
      <div className="ctl-row">
        <button
          className="btn-node primary small f-run nodrag"
          style={{ marginLeft: "auto" }}
          disabled={busy || !data.mine}
          title={!data.mine ? "Сначала отметьте «Это мой сайт»" : undefined}
          onClick={() => runNode(Number(id))}
        >
          {busy ? <span className="spinner" /> : null} ⧉ Разобрать блоки
        </button>
      </div>
      {!data.mine ? <div className="bp-hint">Запуск доступен после отметки «Это мой сайт»</div> : null}
      {data.blocks.length ? (
        <div className="bp-blocks">
          {data.blocks.map((b) => (
            <div key={b.name} className="bp-block" data-block={b.name}>
              <label
                className="bp-lit"
                title={
                  b.error
                    ? "Блок с ошибкой — порт недоступен"
                    : "Зажечь выходной порт этого блока"
                }
              >
                <input
                  type="checkbox"
                  className="f-lit nodrag"
                  disabled={!!b.error}
                  checked={b.lit}
                  onChange={(e) => toggleLit(b.name, e.target.checked)}
                />
                <span className="bp-name">{b.name}</span>
                {b.cached ? <span className="bp-cached">из кэша</span> : null}
              </label>
              {b.error ? (
                <div className="bp-error">{b.error}</div>
              ) : (
                <IrPreview className="bp-preview" ir={b.ir || null} height={72} empty="" />
              )}
            </div>
          ))}
        </div>
      ) : null}
      <NodeStatus id={id} />
      <OutPorts type="blockparse" data={data} />
    </NodeShell>
  );
}
