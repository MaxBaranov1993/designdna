import * as ctl from "./controller";
import { useEditorStore } from "./store";

function colors(tokens: any): string[] {
  const source = tokens?.semantic?.color || tokens?.color || {};
  return [...new Set(Object.values(source).filter((value): value is string => typeof value === "string" && /^#[0-9a-f]{3,8}$/i.test(value)))].slice(0, 8);
}

export function HarmonizerPanel() {
  const proposal = useEditorStore((state) => state.harmonizerProposal);
  if (!proposal) return null;
  const palette = colors(proposal.tokens);
  const displayFont = proposal.tokens?.font?.display?.family || proposal.tokens?.semantic?.font?.display || "из Style DNA";
  const bodyFont = proposal.tokens?.font?.body?.family || proposal.tokens?.semantic?.font?.body || "из Style DNA";
  return (
    <div className="fe-harmonize-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget && proposal.status !== "loading") ctl.dismissHarmonizerProposal();
    }}>
      <section className="fe-harmonize-card" role="dialog" aria-modal="true" aria-labelledby="harmonize-title">
        <div className="fe-harmonize-kicker">AI Harmonizer · {proposal.sourceCount} источн.</div>
        <h2 id="harmonize-title">{proposal.status === "loading" ? "Собираю общую Style DNA…" : "Сделать страницу визуально цельной"}</h2>
        {proposal.status === "loading" ? <div className="fe-harmonize-loader"><i/><span>Ищу повторяющиеся цвета, шрифты, радиусы, тени и semantic roles</span></div> : null}
        {proposal.status === "error" ? <div className="fe-harmonize-error">Harmonizer недоступен: {proposal.error}</div> : null}
        {proposal.status === "ready" ? (
          <>
            <p>Структура, тексты и изображения сохранятся. Изменятся только стилевые фасеты, связанные с общей системой.</p>
            <div className="fe-harmonize-preview">
              <div><small>Палитра</small><span className="fe-harmonize-palette">{palette.map((color) => <i key={color} style={{ background: color }} title={color}/>)}</span></div>
              <div><small>Типографика</small><b>{displayFont}</b><span>{bodyFont}</span></div>
              <div><small>Нормализация</small><b>цвет · тип · радиус · тень</b><span>через semantic bindings</span></div>
            </div>
            <div className="fe-harmonize-note">Предпросмотр не изменил IR. После Apply доступен обычный Undo.</div>
          </>
        ) : null}
        <div className="fe-harmonize-actions">
          <button className="fe-btn" disabled={proposal.status === "loading"} onClick={() => ctl.dismissHarmonizerProposal()}>Отмена</button>
          {proposal.status === "ready" ? <button className="fe-btn primary" data-act="apply-harmonizer" onClick={() => ctl.applyHarmonizerProposal(proposal)}>Применить Style DNA</button> : null}
        </div>
      </section>
    </div>
  );
}
