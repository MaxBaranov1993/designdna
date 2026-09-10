"""Read the actual Design IR DOM into an ordered, editable export scene.

No model calls or mutations of the source IR. Assets stay local; the same public
font catalog as the editor is permitted for missing fonts. Unsupported CSS is
recorded explicitly, per painted object.
"""
from __future__ import annotations

import base64
import copy
import math

from playwright.sync_api import sync_playwright

from ir_render import RENDERER_JS, RENDER_DOCUMENT_HTML, RENDER_DOCUMENT_URL, WEBFONT_HOSTS, _neutralize_links, _requested_font_families
from timeline_assets import install_render_asset_guard, materialize_render_assets, rewrite_local_asset_urls
from timeline_render import _READINESS_JS, _builtin_inter_faces


COLLECT_SCENE = r"""() => {
  const root = document.querySelector('#host [data-design-width]');
  const scene = {width: root.getBoundingClientRect().width,
    height: Math.max(root.scrollHeight, root.getBoundingClientRect().height), items: [], warnings: []};
  let serial = 0, characters = 0;
  const bounds = el => { const r = el.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}; };
  const number = v => Number.parseFloat(v) || 0;
  function color(value) {
    // Canvas normalizes CSS Color 4 (including color-mix/OKLCH) to sRGB.
    const c = document.createElement('canvas'); c.width = c.height = 1;
    const ctx = c.getContext('2d'); ctx.clearRect(0,0,1,1); ctx.fillStyle = value; ctx.fillRect(0,0,1,1);
    const [r,g,b,a] = ctx.getImageData(0,0,1,1).data;
    return {hex:[r,g,b].map(v => v.toString(16).padStart(2,'0')).join(''), alpha:a/255};
  }
  function source(el) {
    const section = el.closest('[data-ir-sec]');
    return (section?.getAttribute('data-ir-sec') || '') + ':' + (el.closest('[data-ir-path]')?.getAttribute('data-ir-path') || el.tagName.toLowerCase());
  }
  function raster(el, box, reason, backgroundOnly = false, opacity = 1) {
    const id = 'object-' + (++serial); el.setAttribute('data-pptx-object', id);
    const shadow = getComputedStyle(el).boxShadow;
    if (shadow !== 'none') {
      const margin = 2 * Math.max(0, ...(shadow.match(/-?[\d.]+px/g) || []).map(v => Math.abs(Number.parseFloat(v))));
      box = {x:box.x-margin,y:box.y-margin,w:box.w+margin*2,h:box.h+margin*2};
    }
    scene.items.push({kind:'image', ...box, id, path:source(el), reason, backgroundOnly, opacity});
    if (reason !== 'image') scene.warnings.push({path:source(el), reason, text: backgroundOnly ? '' : el.innerText || ''});
  }
  function text(node, css, opacity) {
    const value = node.textContent || '';
    if (!value.trim()) return;
    characters += value.length;
    if (characters > 100000) throw new Error('Слишком много текста для одного слайда (100 000 символов)');
    const lines = [], range = document.createRange();
    for (let i = 0; i < value.length; i++) {
      range.setStart(node, i); range.setEnd(node, i + 1);
      const r = range.getBoundingClientRect();
      if (r.width < 0.01 || r.height < 0.01) continue;
      let line = lines[lines.length - 1];
      if (!line || Math.abs(line.y - r.y) > 1) { line = {x:r.x,y:r.y,w:0,h:r.height,text:''}; lines.push(line); }
      line.text += value[i]; line.w = Math.max(line.w, r.right - line.x); line.h = Math.max(line.h,r.height);
    }
    const col = color(css.color); col.alpha *= opacity;
    for (const line of lines) {
      if (!line.text.trim()) continue;
      if (css.textTransform === 'uppercase') line.text = line.text.toLocaleUpperCase();
      if (css.textTransform === 'lowercase') line.text = line.text.toLocaleLowerCase();
      scene.items.push({kind:'text', ...line, path:source(node.parentElement), color:col,
        family:css.fontFamily.split(',')[0].replace(/["']/g,'').trim(), size:number(css.fontSize),
        bold:number(css.fontWeight) >= 600, italic:css.fontStyle === 'italic',
        underline:css.textDecorationLine.includes('underline'), spacing:number(css.letterSpacing),
        href:node.parentElement.closest('[data-pptx-href]')?.getAttribute('data-pptx-href') || node.parentElement.closest('a[href]')?.getAttribute('href') || ''});
    }
  }
  function walk(el, opacity = 1) {
    const css = getComputedStyle(el), box = bounds(el);
    if (css.display === 'none' || css.visibility === 'hidden' || Number(css.opacity) === 0) return;
    opacity *= Number(css.opacity);
    if (scene.items.length > 4000) throw new Error('Слишком много объектов для одного слайда (4000)');
    if (box.w <= 0 || box.h <= 0 || box.y >= scene.height) return;
    // A subtree fallback is explicit: its text cannot be advertised as native.
    const transformed = css.transform !== 'none';
    const clipped = ['hidden','clip','scroll','auto'].includes(css.overflow) &&
      (el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1);
    const generated = ['::before','::after'].some(pseudo => {
      const ps=getComputedStyle(el,pseudo);
      return !['none','normal'].includes(ps.content) && ps.display !== 'none' &&
        (!['""', "''"].includes(ps.content) || ps.backgroundImage !== 'none' || color(ps.backgroundColor).alpha > 0);
    });
    const effect = generated ? 'generated CSS content' : css.backgroundClip === 'text' || css.textShadow !== 'none' ? 'text effects' :
      transformed ? 'transform' : css.filter !== 'none' ? 'filter' :
      css.clipPath !== 'none' ? 'clip-path' : css.maskImage !== 'none' ? 'mask' :
      css.mixBlendMode !== 'normal' ? 'blend-mode' : clipped ? 'clipped content' : null;
    if (effect) { raster(el, box, effect, false, opacity); return; }
    if (['IMG','SVG','CANVAS','VIDEO','IFRAME','INPUT','SELECT','TEXTAREA'].includes(el.tagName)) {
      raster(el, box, el.tagName === 'IMG' ? 'image' : el.tagName.toLowerCase(), false, opacity); return;
    }
    const sides = ['Top','Right','Bottom','Left'];
    const border = sides.map(side => [number(css['border'+side+'Width']), css['border'+side+'Color'], css['border'+side+'Style']]);
    const uniformBorder = border.every(b => JSON.stringify(b) === JSON.stringify(border[0]));
    const radii = [css.borderTopLeftRadius,css.borderTopRightRadius,css.borderBottomLeftRadius,css.borderBottomRightRadius];
    const uniformRadius = radii.every(r => r === radii[0] && !r.includes(' ') && !r.includes('%'));
    const backgroundFallback = css.backgroundImage !== 'none' || css.boxShadow !== 'none' || !uniformBorder || !uniformRadius;
    if (backgroundFallback) raster(el, box, 'background / border / shadow', true, opacity);
    else {
      const fill = color(css.backgroundColor), stroke = color(border[0][1]);
      fill.alpha *= opacity; stroke.alpha *= opacity;
      if (fill.alpha > 0 || border[0][0] > 0) scene.items.push({kind:'shape', ...box, path:source(el),
        fill, stroke, strokeWidth:border[0][0], radius:Math.min(number(radii[0]),box.w/2,box.h/2), dash:border[0][2]});
    }
    // CSS order and local stacking order, preserving document order on ties.
    const children = [...el.childNodes].map((node,index) => ({node,index,order:node.nodeType===1 ? number(getComputedStyle(node).order) : 0,
      z:node.nodeType===1 ? number(getComputedStyle(node).zIndex) : 0}));
    children.sort((a,b) => a.z-b.z || a.order-b.order || a.index-b.index);
    for (const {node} of children) {
      if (node.nodeType === Node.TEXT_NODE) text(node, css, opacity);
      else if (node.nodeType === Node.ELEMENT_NODE && !['STYLE','SCRIPT','LINK'].includes(node.tagName)) walk(node,opacity);
    }
  }
  walk(root);
  return scene;
}"""


def needs_font_catalog(ir: dict) -> bool:
    system = {"arial", "helvetica", "verdana", "tahoma", "trebuchet ms", "georgia", "times new roman", "courier new", "segoe ui",
              "serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-serif", "ui-sans-serif", "ui-monospace", "inter"}
    local = {str(face.get("family", "")).casefold() for face in (ir.get("meta") or {}).get("fontFaces", [])}
    return any(family.casefold() not in system | local for family in _requested_font_families(ir))


def capture_scene(ir: dict, *, width: int = 1280, viewport: str = "desktop") -> tuple[dict, dict]:
    if not isinstance(ir, dict) or not ir.get("tree"):
        raise ValueError("Нет макета для экспорта")
    if viewport not in {"desktop", "tablet", "mobile"} or not 320 <= width <= 4096:
        raise ValueError("Неверный размер или вид холста")
    render_ir = _neutralize_links(ir)
    root_frame = render_ir.get("frame") or {}
    if viewport != "desktop" or not isinstance(root_frame.get("width"), (int, float)):
        render_ir["frame"] = dict(root_frame, width=width)
    assets, errors = materialize_render_assets(render_ir)
    if errors:
        raise ValueError("Ресурсы экспорта: " + "; ".join(errors[:3]))
    render_ir = rewrite_local_asset_urls(render_ir)
    faces, inter_assets = _builtin_inter_faces()
    meta = render_ir.setdefault("meta", {})
    if not any(str(f.get("family", "")).casefold() == "inter" for f in meta.get("fontFaces", [])):
        meta["fontFaces"] = list(meta.get("fontFaces") or []) + faces
        assets.update(inter_assets)
    blocked: list[str] = []
    webfonts = needs_font_catalog(render_ir)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": width, "height": 900}, device_scale_factor=1)
        try:
            install_render_asset_guard(context, assets, blocked, RENDER_DOCUMENT_URL, RENDER_DOCUMENT_HTML,
                                       allow_hosts=WEBFONT_HOSTS if webfonts else ())
            page = context.new_page()
            page.goto(RENDER_DOCUMENT_URL, timeout=30_000)
            page.add_script_tag(path=str(RENDERER_JS))
            page.evaluate("""async ({ir,viewport,webfonts}) => {
              IRRenderer.renderIR(document.querySelector('#host'),ir,{fit:false,viewport,offline:!webfonts});
              const link=document.getElementById('ir-fonts');
              if (!webfonts) link?.removeAttribute('href');
              else if (link && !link.sheet) await Promise.race([
                new Promise(resolve => { link.addEventListener('load',resolve,{once:true}); link.addEventListener('error',resolve,{once:true}); }),
                new Promise(resolve => setTimeout(resolve,12000))]);
            }""", {"ir": render_ir, "viewport": viewport, "webfonts": webfonts})
            readiness = page.evaluate(_READINESS_JS)
            if readiness.get("errors") or blocked:
                raise ValueError("Экспорт не готов: " + "; ".join((readiness.get("errors") or blocked)[:3]))
            # Renderer links are deliberately inert. Recover their intended
            # destination from the canonical node, never navigate or fetch it.
            page.evaluate("""({ir,viewport}) => {
              ir=IRRenderer.materializeResponsiveIR(ir,viewport);
              for(const el of document.querySelectorAll('[data-ir-path]')) {
                const section=ir.tree[Number(el.closest('[data-ir-sec]')?.getAttribute('data-ir-sec'))];
                if(!section) continue;
                const key=el.getAttribute('data-ir-path');
                let node=section;
                for(const part of key.split('.')) node=node?.[part];
                if(typeof node === 'string') { node=section; for(const part of key.split('.').slice(0,-1)) node=node?.[part]; }
                if(!node) { const find=n => n?.sourceKey===key ? n : (n?.children||[]).map(find).find(Boolean); node=find(section); }
                if(node && typeof node==='object' && typeof node.href==='string') el.setAttribute('data-pptx-href',node.href);
              }
            }""", {"ir": ir, "viewport": viewport})
            scene = page.evaluate(COLLECT_SCENE)
            if sum(item["kind"] == "image" for item in scene["items"]) > 128:
                raise ValueError("Больше 128 растровых объектов; экспортируйте отдельный блок")
            if not 1 <= scene["height"] <= 16000 or scene["width"] * scene["height"] > 32_000_000:
                raise ValueError("Слишком большой слайд; экспортируйте отдельный блок (до 16 000 px / 32 MP)")
            page.set_viewport_size({"width": math.ceil(scene["width"]), "height": math.ceil(scene["height"])})
            # Re-read geometry after the viewport grows; fixed/sticky elements may move.
            scene = page.evaluate(COLLECT_SCENE)
            total_bytes = 0
            for item in scene["items"]:
                if item["kind"] != "image":
                    continue
                selector = '[data-pptx-object="' + item["id"] + '"]'
                page.evaluate("""({selector,backgroundOnly,opacity}) => {
                  const el = document.querySelector(selector);
                  const style = document.createElement('style'); style.id='pptx-isolation';
                  style.textContent = 'body *{visibility:hidden!important} '+selector+','+selector+' *{visibility:visible!important}';
                  if (backgroundOnly) {
                    const rect=el.getBoundingClientRect(), css=getComputedStyle(el), clone=document.createElement('div');
                    for(const key of css) clone.style.setProperty(key,css.getPropertyValue(key));
                    Object.assign(clone.style,{position:'absolute',left:rect.x+'px',top:rect.y+'px',margin:'0',width:rect.width+'px',height:rect.height+'px',boxSizing:'border-box',transform:'none',opacity:String(opacity)});
                    clone.id='pptx-background'; document.body.append(clone);
                    style.textContent='body *{visibility:hidden!important} #pptx-background{visibility:visible!important}';
                  }
                  document.head.append(style);
                }""", {"selector": selector, "backgroundOnly": item["backgroundOnly"], "opacity": item["opacity"]})
                x, y = max(0, item["x"]), max(0, item["y"])
                w = min(item["x"] + item["w"], scene["width"]) - x
                h = min(item["y"] + item["h"], scene["height"]) - y
                try:
                    if w <= 0 or h <= 0:
                        item["hidden"] = True
                        continue
                    png = page.screenshot(type="png", omit_background=True, animations="disabled", clip={"x": x, "y": y, "width": w, "height": h})
                    total_bytes += len(png)
                    if total_bytes > 48_000_000:
                        raise ValueError("Растровые элементы превышают 48 MB; экспортируйте отдельный блок")
                    item.update(x=x, y=y, w=w, h=h, png=base64.b64encode(png).decode())
                finally:
                    page.evaluate("document.getElementById('pptx-isolation')?.remove(); document.getElementById('pptx-background')?.remove()")
            scene["items"] = [item for item in scene["items"] if not item.get("hidden")]
            scene["viewport"] = viewport
            scene["preview"] = base64.b64encode(page.screenshot(type="png", full_page=True)).decode()
            return scene, copy.deepcopy(ir)
        finally:
            context.close()
            browser.close()
