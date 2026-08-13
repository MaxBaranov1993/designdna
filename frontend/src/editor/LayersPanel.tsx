/* Панель слоёв: поиск (React) + дерево слоёв (императивный остров контроллера —
 * строки, drag-reorder, hide/lock-флаги строятся портом renderLayers из editor.js). */
import * as ctl from "./controller";

export function LayersPanel() {
  return (
    <div className="fe-layers">
      <div className="fe-layers-head">Слои</div>
      <input
        className="fe-search"
        placeholder="Поиск слоёв…"
        ref={(el) => { ctl.dom.search = el; }}
        onChange={(e) => ctl.setLayerQuery(e.target.value)}
      />
      <div className="fe-layers-tree" ref={(el) => { ctl.dom.layersTree = el; }} />
    </div>
  );
}
