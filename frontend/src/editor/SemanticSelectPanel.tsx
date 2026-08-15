import { useState } from "react";
import * as ctl from "./controller";
import { useEditorStore } from "./store";

const EXAMPLES = ["все кнопки", "заголовки", "все карточки", "изображения", "элементы источника B"];

export function SemanticSelectPanel() {
  const open = useEditorStore((state) => state.semanticSelectOpen);
  const [query, setQuery] = useState("");
  const [count, setCount] = useState<number | null>(null);
  if (!open) return null;
  const run = () => setCount(ctl.semanticSelect(query));
  return (
    <div className="fe-semantic-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) ctl.closeSemanticSelect(); }}>
      <section className="fe-semantic-card" role="dialog" aria-modal="true" aria-labelledby="semantic-title">
        <div className="fe-semantic-kicker">Semantic Selection · AI понимает смысл и источник</div>
        <h2 id="semantic-title">Что выделить?</h2>
        <div className="fe-semantic-input">
          <input autoFocus value={query} onChange={(event) => { setQuery(event.target.value); setCount(null); }} onKeyDown={(event) => { if (event.key === "Enter") run(); }} placeholder="Например: все CTA из Header" />
          <button className="fe-btn primary" data-act="run-semantic-select" disabled={!query.trim()} onClick={run}>Выделить</button>
        </div>
        <div className="fe-semantic-examples">{EXAMPLES.map((example) => <button key={example} onClick={() => { setQuery(example); setCount(null); }}>{example}</button>)}</div>
        {count !== null ? <div className={"fe-semantic-result " + (count ? "found" : "empty")}>{count ? `Выделено элементов: ${count}` : "Совпадений нет — уточните тип или название источника"}</div> : null}
        <p>Запрос комбинирует семантику элемента и provenance. Например, «кнопки из Imported header» не затронет CTA из других источников.</p>
        <div className="fe-semantic-actions"><button className="fe-btn" onClick={() => ctl.closeSemanticSelect()}>Готово</button></div>
      </section>
    </div>
  );
}
