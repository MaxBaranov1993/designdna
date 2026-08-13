/* Общий инспектор (модель pen.dev) — React-порт inspector.js renderSingle/renderMulti.
 * Разметка 1:1: .pi > .pi-type + .pi-group (Alignment / Position / Flex Layout /
 * Dimensions / Appearance / reset-frame). Все data-pi / data-style-* / data-pi-dir /
 * data-pi-ja / data-pi-justify хуки сохранены — их обрабатывает wireInspector.ts.
 * Инпуты неконтролируемые (defaultValue): коммит по нативному change, как в legacy. */
import type { GeoHandle, GeoRef, GeoSel } from "../globals";
import * as ctl from "../controller";
import { ColorField } from "./ColorPicker";
import { FontOptions } from "./FontOptions";

function getByPath(obj: any, path: string) {
  return path.split(".").reduce((o, k) => (o == null ? o : o[k]), obj);
}

function nodeOf(ir: any, ref: GeoRef): any {
  if (ref.secIdx == null) return ir;
  if (ref.path == null) return ir.tree ? ir.tree[ref.secIdx] : null;
  return getByPath(ir.tree[ref.secIdx], ref.path);
}

function isContainer(ir: any, ref: GeoRef): boolean {
  if (ref.secIdx == null || ref.path == null) return true;
  const n = nodeOf(ir, ref);
  return !!(n && (n.type === "card" || (n.children && n.children.length)));
}

function fullHex(v: any, fallback: string): string {
  const s = String(v || "").trim();
  if (/^#[0-9a-f]{3}$/i.test(s)) return "#" + s.slice(1).split("").map((c) => c + c).join("").toLowerCase();
  if (/^#[0-9a-f]{6}$/i.test(s)) return s.toLowerCase();
  return fallback;
}

const isTransparent = (v: any) => v == null || v === "" || String(v).toLowerCase() === "transparent";

function AlignButtons() {
  return (
    <>
      <div className="pi-btnrow">
        <button className="pi-ibtn" data-act="align-left" title="По левому краю">⫷</button>
        <button className="pi-ibtn" data-act="align-center-h" title="Центр по горизонтали">⫿</button>
        <button className="pi-ibtn" data-act="align-right" title="По правому краю">⫸</button>
      </div>
      <div className="pi-btnrow" style={{ marginTop: 4 }}>
        <button className="pi-ibtn" data-act="align-top" title="По верхнему краю">⊤</button>
        <button className="pi-ibtn" data-act="align-center-v" title="Центр по вертикали">⊶</button>
        <button className="pi-ibtn" data-act="align-bottom" title="По нижнему краю">⊥</button>
      </div>
      <div className="pi-btnrow" style={{ marginTop: 4 }}>
        <button className="pi-ibtn" data-act="distribute-h" title="Распределить по горизонтали">↔</button>
        <button className="pi-ibtn" data-act="distribute-v" title="Распределить по вертикали">↕</button>
      </div>
    </>
  );
}

function MultiInspector({ sels }: { sels: GeoSel[] }) {
  return (
    <div className="pi">
      <div className="pi-type">Выделено: {sels.length}</div>
      <div className="pi-group"><span className="pi-glabel">Alignment</span><AlignButtons /></div>
      <div className="pi-group"><span className="pi-glabel">Элементы</span>
        <div className="pi-sel-list">
          {sels.map((s, i) => <div key={i}>{s.label}</div>)}
        </div>
      </div>
    </div>
  );
}

function SingleInspector({ sel, ir, geo }: { sel: GeoSel; ir: any; geo: GeoHandle | null }) {
  const ref = sel.ref;
  const f: any = (geo && geo.frameOf(ref)) || {};
  const node = nodeOf(ir, ref) || {};
  const isRoot = ref.secIdx == null;
  const cont = isContainer(ir, ref);
  const pos = !isRoot && geo ? geo.posOf(ref) : null;
  const size = geo ? geo.sizeOf(ref) : null;

  const x = typeof f.x === "number" ? f.x : pos ? pos.x : "";
  const y = typeof f.y === "number" ? f.y : pos ? pos.y : "";
  const rot = typeof f.rotation === "number" ? f.rotation : 0;
  const w = typeof f.width === "number" ? f.width : size ? size.w : "";
  const h = typeof f.height === "number" ? f.height : size ? size.h : "";

  let padV: any = "", padH: any = "";
  if (typeof f.padding === "number") { padV = f.padding; padH = f.padding; }
  else if (Array.isArray(f.padding) && f.padding.length >= 2) { padV = f.padding[0]; padH = f.padding[1]; }

  const dir = f.layout === "free" ? "free" : f.direction === "row" ? "row" : "column";
  const justify = f.justify || "start";
  const align = f.align || "start";
  const radioName = `pi-justify-${ref.secIdx}-${ref.path || "root"}`;

  const st = node.style || {};
  const fill = fullHex(st.background || node.fill, "#ffffff");
  const color = fullHex(st.color, "#111111");
  const stroke = fullHex(st.borderColor, "#e0e0e0");
  const radius = typeof st.borderRadius === "number" ? st.borderRadius : typeof node.radius === "number" ? node.radius : "";
  const fontFamily = st.fontFamily || "";
  const fontSize = typeof st.fontSize === "number" ? st.fontSize : "";
  const fontWeight = typeof st.fontWeight === "number" ? st.fontWeight : "";
  const isText = node.type === "text" || node.type === "heading" || node.type === "button" || node.text != null || node.title != null;
  const opacityVal = Math.round((Number(st.opacity) || 1) * 100);

  return (
    <div className="pi">
      <div className="pi-type">{sel.label}</div>

      <div className="pi-group"><span className="pi-glabel">Alignment</span><AlignButtons /></div>

      <div className="pi-group"><span className="pi-glabel">Position</span>
        <div className="pi-row">
          <div className="pi-field"><label title="Тяни горизонтально — scrub; можно выражения: 100*2">X</label><input type="text" inputMode="decimal" data-pi="x" defaultValue={x} disabled={isRoot} /></div>
          <div className="pi-field"><label title="Тяни горизонтально — scrub; можно выражения: 100*2">Y</label><input type="text" inputMode="decimal" data-pi="y" defaultValue={y} disabled={isRoot} /></div>
        </div>
        <div className="pi-row">
          <div className="pi-field"><label>R</label><input type="text" inputMode="decimal" data-pi="rotation" defaultValue={rot} disabled={isRoot} /></div>
          <div className="pi-field"></div>
        </div>
        {!isRoot && (
          <div className="pi-row"><label className="pi-check"><input type="checkbox" data-pi="absolute" defaultChecked={!!f.absolute} /> Absolute Position</label></div>
        )}
        {!isRoot && (
          <div className="pi-row" title="Constraints: реакция на resize родителя">
            <div className="pi-field"><label>CH</label>
              <select data-pi="constr-h" defaultValue={(f.constraints && f.constraints.h) || undefined}>
                {["left", "center", "right", "scale"].map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
            <div className="pi-field"><label>CV</label>
              <select data-pi="constr-v" defaultValue={(f.constraints && f.constraints.v) || undefined}>
                {["top", "center", "bottom", "scale"].map((o) => <option key={o} value={o}>{o}</option>)}
              </select>
            </div>
          </div>
        )}
      </div>

      {cont && (
        <div className="pi-group"><span className="pi-glabel">Flex Layout</span>
          <div className="pi-btnrow">
            <button className={`pi-ibtn ${dir === "free" ? "active" : ""}`} data-pi-dir="free" title="Без раскладки: дети по x/y (layout:none в pen.dev)">⊞</button>
            <button className={`pi-ibtn ${dir === "column" ? "active" : ""}`} data-pi-dir="column" title="Колонка (vertical)">↓</button>
            <button className={`pi-ibtn ${dir === "row" ? "active" : ""}`} data-pi-dir="row" title="Ряд (horizontal)">→</button>
          </div>
          <div className="pi-row" style={{ marginTop: 6 }}><label style={{ fontSize: 10, color: "var(--muted,#6c7086)", fontWeight: 700 }}>Alignment</label></div>
          <div className="pi-grid3">
            {["start", "center", "end"].map((a) =>
              ["start", "center", "end"].map((j) => (
                <button key={`${j}|${a}`} className={`pi-ibtn ${justify === j && align === a ? "active" : ""}`} data-pi-ja={`${j}|${a}`} title={`justify:${j} align:${a}`}><span className="dot"></span></button>
              )),
            )}
          </div>
          <div className="pi-row" style={{ marginTop: 6 }}>
            <div className="pi-field"><label>Gap</label><input type="text" inputMode="decimal" data-pi="gap" defaultValue={typeof f.gap === "number" ? f.gap : ""} /></div>
          </div>
          <div className="pi-row"><label className="pi-radio"><input type="radio" name={radioName} data-pi-justify="space-between" defaultChecked={justify === "space-between"} /> Space Between</label></div>
          <div className="pi-row"><label className="pi-radio"><input type="radio" name={radioName} data-pi-justify="space-around" defaultChecked={justify === "space-around"} /> Space Around</label></div>
          <div className="pi-row" style={{ marginTop: 6 }}>
            <div className="pi-field"><label>Pad↕</label><input type="text" inputMode="decimal" data-pi="padv" defaultValue={padV} /></div>
            <div className="pi-field"><label>Pad↔</label><input type="text" inputMode="decimal" data-pi="padh" defaultValue={padH} /></div>
          </div>
        </div>
      )}

      <div className="pi-group"><span className="pi-glabel">Dimensions</span>
        <div className="pi-row">
          <div className="pi-field"><label title="Можно выражения: 960/3">W</label><input type="text" inputMode="decimal" data-pi="width" defaultValue={w} /></div>
          <div className="pi-field"><label title="Можно выражения: 960/3">H</label><input type="text" inputMode="decimal" data-pi="height" defaultValue={h} /></div>
        </div>
        <div className="pi-checks" style={{ marginTop: 6 }}>
          <label className="pi-check"><input type="checkbox" data-pi="fillw" defaultChecked={f.width === "fill"} /> Fill Width</label>
          <label className="pi-check"><input type="checkbox" data-pi="fillh" defaultChecked={f.height === "fill"} /> Fill Height</label>
          <label className="pi-check"><input type="checkbox" data-pi="hugw" defaultChecked={f.width === "hug"} /> Hug Width</label>
          <label className="pi-check"><input type="checkbox" data-pi="hugh" defaultChecked={f.height === "hug"} /> Hug Height</label>
          <label className="pi-check"><input type="checkbox" data-pi="clip" defaultChecked={!!f.clip} /> Clip Content</label>
        </div>
      </div>

      {!isRoot && (
        <div className="pi-group"><span className="pi-glabel">Appearance</span>
          <div className="pi-row">
            <ColorField styleKey="background" label="Fill" hex={fill}
              raw={st.background || node.fill || ""} transparent={isTransparent(st.background || node.fill)} />
          </div>
          {isText && (
            <div className="pi-row">
              <ColorField styleKey="color" label="Text" hex={color}
                raw={st.color || ""} transparent={isTransparent(st.color)} />
            </div>
          )}
          <div className="pi-row">
            <ColorField styleKey="borderColor" label="Line" hex={stroke}
              raw={st.borderColor || ""} transparent={isTransparent(st.borderColor)} />
          </div>
          <div className="pi-row">
            <div className="pi-field"><label>Opacity</label><input type="range" min={0} max={100} data-style-range="opacity" defaultValue={opacityVal} /><span data-opacity-label>{opacityVal}%</span></div>
          </div>
          <div className="pi-row">
            <div className="pi-field"><label>R</label><input type="text" inputMode="decimal" data-style-num="borderRadius" defaultValue={radius} placeholder="0" /></div>
            <div className="pi-field"><label>BW</label><input type="text" inputMode="decimal" data-style-num="borderWidth" defaultValue={typeof st.borderWidth === "number" ? st.borderWidth : ""} placeholder="0" /></div>
          </div>
          {isText && (
            <>
              <div className="pi-row">
                <div className="pi-field"><label>Font</label><select data-style-select="fontFamily" defaultValue={fontFamily}><FontOptions autoLabel="Auto" /></select></div>
              </div>
              <div className="pi-row">
                <div className="pi-field"><label>Sz</label><input type="text" inputMode="decimal" data-style-num="fontSize" defaultValue={fontSize} placeholder="auto" /></div>
                <div className="pi-field"><label>Wt</label><input type="text" inputMode="decimal" data-style-num="fontWeight" defaultValue={fontWeight} placeholder="auto" /></div>
              </div>
            </>
          )}
        </div>
      )}

      {!isRoot && (
        <div className="pi-group"><button className="pi-ibtn pi-wide" data-act="reset-frame">Сбросить frame</button></div>
      )}
    </div>
  );
}

export function SharedInspector() {
  const sess = ctl.getSession();
  const sels = sess ? sess.sel : [];
  if (!sels.length) return null;
  if (sels.length > 1) return <MultiInspector sels={sels} />;
  return <SingleInspector sel={sels[0]} ir={sess!.ir} geo={sess!.geo} />;
}
