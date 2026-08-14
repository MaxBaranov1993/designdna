/* Type-specific группы инспектора — React-порт добавок editor.js renderInspector
 * поверх общего Inspector: responsive-статус (data-responsive-act/copy), текст
 * (data-textprop / data-el-prop), кнопка (data-node-style-*), артборд-токены
 * (data-color / data-font / data-token). События навешивает wireInspector.ts. */
import * as ctl from "../controller";
import { FontOptions } from "./FontOptions";

const COLOR_KEYS = ["primary", "secondary", "accent", "background", "surface", "text", "textMuted", "border"];
const COLOR_LABELS: Record<string, string> = {
  primary: "Primary", secondary: "Secondary", accent: "Accent", background: "Фон",
  surface: "Surface", text: "Текст", textMuted: "Muted", border: "Border",
};

function toFullHex(hex: string): string {
  if (/^#[0-9a-fA-F]{6}$/.test(hex)) return hex;
  if (/^#[0-9a-fA-F]{3}$/.test(hex)) return "#" + [...hex.slice(1)].map((c) => c + c).join("");
  return "#888888";
}

function ResponsiveStatus() {
  const sess = ctl.getSession();
  if (!sess) return null;
  const sel = sess.sel[0];
  const canonical = ctl.canonicalNode(sel.ref) || {};
  const override = sess.viewport === "desktop" ? null : (canonical.responsive || {})[sess.viewport] || null;
  const frameSource = override && override.frame ? sess.viewport : "shared";
  const styleSource = override && override.style ? sess.viewport : "shared";
  const frameLabel = frameSource === "shared" ? "Унаследовано" : "Переопределено";
  const styleLabel = styleSource === "shared" ? "Унаследовано" : "Переопределено";
  return (
    <div className="fe-responsive-status">
      <div className="fe-responsive-status-head">
        <span>{sess.viewport === "desktop" ? "Компьютер" : sess.viewport === "tablet" ? "Планшет" : "Телефон"} · {sess.previewWidth} px</span>
        <span className="fe-responsive-state"><span className={`fe-source-tag ${frameSource !== "shared" ? "override" : "inherited"}`}>Frame: {frameLabel}</span> <span className={`fe-source-tag ${styleSource !== "shared" ? "override" : "inherited"}`}>Style: {styleLabel}</span></span>
      </div>
      <details className="fe-responsive-advanced">
        <summary>Дополнительно</summary>
        <div className="fe-responsive-actions">
          <button className="fe-btn" data-responsive-act="reset" disabled={sess.viewport === "desktop"}>Сбросить своё</button>
          <button className="fe-btn" data-responsive-act="all">Применить ко всем</button>
          <button className="fe-btn" data-responsive-copy="mobile">Копировать на телефон</button>
          <button className="fe-btn" data-responsive-copy="tablet">Копировать на планшет</button>
          <button className="fe-btn" data-responsive-copy="desktop">Копировать на компьютер</button>
        </div>
      </details>
    </div>
  );
}

function TextGroup({ node }: { node: any }) {
  return (
    <div className="fe-insp-group"><span className="fe-glabel">Текст</span>
      <textarea data-textprop={node.text !== undefined ? "text" : "title"} defaultValue={node.text || node.title || ""} />
      <div className="fe-row" style={{ marginTop: 6 }}>
        <div className="fe-field fe-field-wide"><label>Размер</label>
          <select data-el-prop="size" defaultValue={node.size || "md"}>
            <option value="xs">XS</option><option value="sm">SM</option><option value="md">MD</option>
            <option value="lg">LG</option><option value="xl">XL</option><option value="display">Display</option>
          </select>
        </div>
        <div className="fe-field fe-field-wide"><label>Выравнивание</label>
          <select data-el-prop="align" defaultValue={node.align || "left"}>
            <option value="left">Слева</option><option value="center">По центру</option><option value="right">Справа</option>
          </select>
        </div>
      </div>
      {node.type === "heading" && (
        <div className="fe-row"><div className="fe-field fe-field-wide"><label>Уровень</label>
          <select data-el-prop="level" defaultValue={node.level || 2}>
            <option value="1">H1</option><option value="2">H2</option><option value="3">H3</option><option value="4">H4</option>
          </select>
        </div></div>
      )}
    </div>
  );
}

function ButtonGroup({ node }: { node: any }) {
  return (
    <div className="fe-insp-group"><span className="fe-glabel">Кнопка</span>
      <div className="fe-field fe-field-wide" style={{ marginBottom: 6 }}><label>Текст</label><input type="text" data-el-prop="text" defaultValue={node.text || ""} /></div>
      <div className="fe-field fe-field-wide"><label>Вид</label>
        <select data-el-prop="variant" defaultValue={node.variant || "primary"}>
          <option value="primary">Основная</option><option value="secondary">Вторая</option>
          <option value="outline">Обводка</option><option value="ghost">Призрачная</option>
        </select>
      </div>
    </div>
  );
}

function ArtboardGroups({ t }: { t: any }) {
  return (
    <>
      {t.color && (
        <div className="fe-insp-group"><span className="fe-glabel">Цвета (токены)</span>
          {COLOR_KEYS.filter((k) => t.color[k]).map((k) => (
            <div className="fe-color-row" key={k}><label>{COLOR_LABELS[k] || k}</label>
              <input type="color" data-color={k} defaultValue={toFullHex(t.color[k])} /><span className="fe-hex">{t.color[k]}</span>
            </div>
          ))}
        </div>
      )}
      {t.font && (
        <div className="fe-insp-group"><span className="fe-glabel">Шрифты</span>
          <div className="fe-field fe-field-wide" style={{ marginBottom: 4 }}><label>Заголовок</label><select data-font="display" defaultValue={t.font.display.family}><FontOptions /></select></div>
          <div className="fe-field fe-field-wide" style={{ marginBottom: 4 }}><label>Текст</label><select data-font="body" defaultValue={t.font.body.family}><FontOptions /></select></div>
          <div className="fe-field fe-field-wide"><label>Интервал</label>
            <select data-token="font.scale" defaultValue={t.font.scale || "default"}>
              <option value="compact">Compact</option><option value="default">Default</option><option value="spacious">Spacious</option>
            </select>
          </div>
        </div>
      )}
      <div className="fe-insp-group"><span className="fe-glabel">Форма и отступы</span>
        <div className="fe-row">
          <div className="fe-field fe-field-wide"><label>Скругление</label>
            <select data-token="radius.card" defaultValue={(t.radius && t.radius.card) || "md"}>
              <option value="none">None</option><option value="sm">SM</option><option value="md">MD</option>
              <option value="lg">LG</option><option value="xl">XL</option><option value="full">Full</option>
            </select>
          </div>
          <div className="fe-field fe-field-wide"><label>Отступы</label>
            <select data-token="spacing.section" defaultValue={(t.spacing && t.spacing.section) || "md"}>
              <option value="sm">SM</option><option value="md">MD</option><option value="lg">LG</option><option value="xl">XL</option>
            </select>
          </div>
        </div>
        <div className="fe-field fe-field-wide"><label>Тень</label>
          <select data-token="shadow" defaultValue={t.shadow || "sm"}>
            <option value="none">None</option><option value="sm">SM</option><option value="md">MD</option><option value="lg">LG</option>
          </select>
        </div>
      </div>
    </>
  );
}

/** Type-specific группы для одиночного выделения (после .fe-shared-insp). */
export function TypeGroups() {
  const sess = ctl.getSession();
  if (!sess || sess.sel.length !== 1) return null;
  const sel = sess.sel[0];
  const node = sel.node || {};
  const isRoot = sel.ref.secIdx == null;
  const t = sess.ir.tokens || {};
  const hasResponsive = !!(sess.ir.responsive && sess.ir.responsive.viewports);

  return (
    <>
      {!isRoot && hasResponsive && <ResponsiveStatus />}
      {(node.type === "heading" || node.type === "text") && <TextGroup node={node} />}
      {node.type === "button" && <ButtonGroup node={node} />}
      {isRoot && <ArtboardGroups t={t} />}
    </>
  );
}
