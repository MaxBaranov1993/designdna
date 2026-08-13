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
  return (
    <div className="fe-responsive-status">
      <div className="fe-responsive-status-head">
        <span>{sess.viewport} · {sess.previewWidth} px</span>
        <span><span className="fe-source-tag">frame {frameSource}</span> <span className="fe-source-tag">style {styleSource}</span></span>
      </div>
      <div className="fe-responsive-actions">
        <button className="fe-btn" data-responsive-act="reset" disabled={sess.viewport === "desktop"}>Reset override</button>
        <button className="fe-btn" data-responsive-act="all">Apply to all</button>
        <button className="fe-btn" data-responsive-copy="mobile">Copy to M</button>
        <button className="fe-btn" data-responsive-copy="tablet">Copy to T</button>
        <button className="fe-btn" data-responsive-copy="desktop">Copy to D</button>
      </div>
    </div>
  );
}

function TextGroup({ node }: { node: any }) {
  return (
    <div className="fe-insp-group"><span className="fe-glabel">Текст</span>
      <textarea data-textprop={node.text !== undefined ? "text" : "title"} defaultValue={node.text || node.title || ""} />
      <div className="fe-row" style={{ marginTop: 6 }}>
        <div className="fe-field"><label>Sz</label>
          <select data-el-prop="size" defaultValue={node.size || "md"}>
            <option value="xs">XS</option><option value="sm">SM</option><option value="md">MD</option>
            <option value="lg">LG</option><option value="xl">XL</option><option value="display">Display</option>
          </select>
        </div>
        <div className="fe-field"><label>≡</label>
          <select data-el-prop="align" defaultValue={node.align || "left"}>
            <option value="left">Left</option><option value="center">Center</option><option value="right">Right</option>
          </select>
        </div>
      </div>
      {node.type === "heading" && (
        <div className="fe-row"><div className="fe-field"><label>H</label>
          <select data-el-prop="level" defaultValue={node.level || 2}>
            <option value="1">H1</option><option value="2">H2</option><option value="3">H3</option><option value="4">H4</option>
          </select>
        </div></div>
      )}
    </div>
  );
}

function ButtonGroup({ node }: { node: any }) {
  const st = node.style || {};
  const fill = toFullHex(st.background || node.fill || "");
  const textColor = toFullHex(st.color || "");
  const radius = typeof st.borderRadius === "number" ? st.borderRadius : typeof node.radius === "number" ? node.radius : "";
  const fontSize = typeof st.fontSize === "number" ? st.fontSize : "";
  const fontWeight = typeof st.fontWeight === "number" ? st.fontWeight : "";
  return (
    <div className="fe-insp-group"><span className="fe-glabel">Кнопка</span>
      <div className="fe-field" style={{ marginBottom: 6 }}><label>Txt</label><input type="text" data-el-prop="text" defaultValue={node.text || ""} /></div>
      <div className="fe-field" style={{ marginBottom: 6 }}><label>Var</label>
        <select data-el-prop="variant" defaultValue={node.variant || "primary"}>
          <option value="primary">Primary</option><option value="secondary">Secondary</option>
          <option value="outline">Outline</option><option value="ghost">Ghost</option>
        </select>
      </div>
      <div className="fe-color-row"><label>Fill</label><input type="color" data-node-style-color="background" defaultValue={fill} /><span className="fe-hex">{st.background || ""}</span></div>
      <div className="fe-color-row"><label>Text</label><input type="color" data-node-style-color="color" defaultValue={textColor} /><span className="fe-hex">{st.color || ""}</span></div>
      <div className="fe-row">
        <div className="fe-field"><label>Font</label><select data-node-style-select="fontFamily" defaultValue={st.fontFamily || ""}><FontOptions autoLabel="Auto" /></select></div>
      </div>
      <div className="fe-row">
        <div className="fe-field"><label>Sz</label><input type="text" inputMode="decimal" data-node-style-num="fontSize" defaultValue={fontSize} placeholder="auto" /></div>
        <div className="fe-field"><label>Wt</label><input type="text" inputMode="decimal" data-node-style-num="fontWeight" defaultValue={fontWeight} placeholder="auto" /></div>
      </div>
      <div className="fe-row">
        <div className="fe-field"><label>R</label><input type="text" inputMode="decimal" data-node-style-num="borderRadius" defaultValue={radius} placeholder="auto" /></div>
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
          <div className="fe-field" style={{ marginBottom: 4 }}><label>D</label><select data-font="display" defaultValue={t.font.display.family}><FontOptions /></select></div>
          <div className="fe-field" style={{ marginBottom: 4 }}><label>B</label><select data-font="body" defaultValue={t.font.body.family}><FontOptions /></select></div>
          <div className="fe-field"><label>Sc</label>
            <select data-token="font.scale" defaultValue={t.font.scale || "default"}>
              <option value="compact">Compact</option><option value="default">Default</option><option value="spacious">Spacious</option>
            </select>
          </div>
        </div>
      )}
      <div className="fe-insp-group"><span className="fe-glabel">Форма и отступы</span>
        <div className="fe-row">
          <div className="fe-field"><label>R</label>
            <select data-token="radius.card" defaultValue={(t.radius && t.radius.card) || "md"}>
              <option value="none">None</option><option value="sm">SM</option><option value="md">MD</option>
              <option value="lg">LG</option><option value="xl">XL</option><option value="full">Full</option>
            </select>
          </div>
          <div className="fe-field"><label>Sp</label>
            <select data-token="spacing.section" defaultValue={(t.spacing && t.spacing.section) || "md"}>
              <option value="sm">SM</option><option value="md">MD</option><option value="lg">LG</option><option value="xl">XL</option>
            </select>
          </div>
        </div>
        <div className="fe-field"><label>Sh</label>
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
