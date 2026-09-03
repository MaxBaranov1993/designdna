(blocks) => {
                  const num = (v) => Number.parseFloat(v) || 0;
                  const round2 = (v) => Math.round(Number(v || 0) * 100) / 100;
                  // ---- цвет: rgb/rgba, color(srgb|display-p3), oklch, oklab, lab, lch, color-mix ----
                  const clamp01=(v)=>Math.max(0,Math.min(1,v));
                  const gamma=(v)=>v<=0.0031308?12.92*v:1.055*Math.pow(v,1/2.4)-0.055;
                  const linToHex=(r,g,b)=>{
                    const R=Math.round(clamp01(gamma(r))*255),G=Math.round(clamp01(gamma(g))*255),B=Math.round(clamp01(gamma(b))*255);
                    return '#'+[R,G,B].map(x=>x.toString(16).padStart(2,'0')).join('');
                  };
                  // Björn Ottosson: OKLab → linear sRGB
                  const oklabToLinSrgb=(L,a,b)=>{
                    const l_=L+0.3963377774*a+0.2158037573*b;
                    const m_=L-0.1055613458*a-0.0638541728*b;
                    const s_=L-0.0894841775*a-1.2914855480*b;
                    const l=l_*l_*l_,m=m_*m_*m_,s=s_*s_*s_;
                    return [
                      4.0767416621*l-3.3077115913*m+0.2309699292*s,
                      -1.2684380046*l+2.6097574011*m-0.3413193965*s,
                      -0.0041960863*l-0.7034186147*m+1.7076147010*s];
                  };
                  // CIE Lab (D50) → linear sRGB (Bradford D50→D65)
                  const labToLinSrgb=(L,a,b)=>{
                    const d=6/29, fy=(L+16)/116, fx=fy+a/500, fz=fy-b/200;
                    const finv=(t)=>t>d?t*t*t:3*d*d*(t-4/29);
                    const xr=finv(fx)*0.95047, yr=finv(fy)*1.0, zr=finv(fz)*1.08883;
                    const X= 1.0479298208405488*xr + 0.022946793341019088*yr - 0.05019222954356957*zr;
                    const Y= 0.029627815688159344*xr + 0.990434484573249*yr - 0.01707382502938514*zr;
                    const Z=-0.009243058152591178*xr + 0.015055144896577895*yr + 0.7518742899580008*zr;
                    return [
                      3.1338561*X-1.6168667*Y-0.4906146*Z,
                      -0.9787684*X+1.9161415*Y+0.0334540*Z,
                      0.0719453*X-0.2289914*Y+1.4052427*Z];
                  };
                  // display-p3 (linear) → linear sRGB
                  const p3ToLinSrgb=(r,g,b)=>{
                    const X=0.4865709486*r+0.2656676932*g+0.1982172852*b;
                    const Y=0.2289745641*r+0.6917385218*g+0.0792869141*b;
                    const Z=0.0451133819*g+1.0439443689*b;
                    return [
                      3.2406*X-1.5372*Y-0.4986*Z,
                      -0.9689*X+1.8758*Y+0.0415*Z,
                      0.0557*X-0.2040*Y+1.0570*Z];
                  };
                  const pct=(tok,max)=>tok.endsWith('%')?(Number.parseFloat(tok)/100)*(max||1):Number.parseFloat(tok);
                  const hex = (v) => {
                    const value=String(v||'').trim();
                    let out=null, alpha=1;
                    const rgb=value.match(/^rgba?\(\s*([\d.]+)(?:%)?\s*,\s*([\d.]+)(?:%)?\s*,\s*([\d.]+)(?:%)?\s*(?:,\s*([\d.]+)%?\s*)?\)$/);
                    const rgbSlash=value.match(/^rgba?\(\s*([\d.]+%?)\s+([\d.]+%?)\s+([\d.]+%?)(?:\s*\/\s*([\d.]+%?)\s*)?\)$/);
                    const m=rgb||rgbSlash;
                    if(m){
                      const scale=m[1].endsWith('%')?2.55:1;
                      out='#'+[1,2,3].map(i=>Math.round(Math.max(0,Math.min(255,Number.parseFloat(m[i])*scale))).toString(16).padStart(2,'0')).join('');
                      if(m[4]===undefined) alpha=1;
                      else if(m[4].endsWith('%')) alpha=clamp01(Number.parseFloat(m[4])/100);
                      else alpha=clamp01(Number.parseFloat(m[4]));
                    } else if(/^color\(srgb/i.test(value)){
                      const t=value.match(/color\(srgb\s+([\d.]+%?)\s+([\d.]+%?)\s+([\d.]+%?)(?:\s*\/\s*([\d.]+%?))?\)/i);
                      if(!t) return null;
                      out='#'+[1,2,3].map(i=>Math.round(clamp01(pct(t[i],1))*255).toString(16).padStart(2,'0')).join('');
                      alpha=t[4]===undefined?1:clamp01(pct(t[4],1));
                    } else if(/^color\(display-p3/i.test(value)){
                      const t=value.match(/color\(display-p3\s+([\d.]+%?)\s+([\d.]+%?)\s+([\d.]+%?)(?:\s*\/\s*([\d.]+%?))?\)/i);
                      if(!t) return null;
                      const lin=p3ToLinSrgb(pct(t[1],1),pct(t[2],1),pct(t[3],1));
                      out=linToHex(lin[0],lin[1],lin[2]);
                      alpha=t[4]===undefined?1:clamp01(pct(t[4],1));
                    } else if(/^oklch\(/i.test(value)){
                      const t=value.match(/oklch\(\s*([\d.]+%?)\s+([\d.]+%?)\s+([\d.]+)(?:deg|grad|rad|turn)?\s*(?:\/\s*([\d.]+%?))?\)/i);
                      if(!t) return null;
                      const L=pct(t[1],1), C=Number.parseFloat(t[2]), H=Number.parseFloat(t[3])*Math.PI/180;
                      const lin=oklabToLinSrgb(L,C*Math.cos(H),C*Math.sin(H));
                      out=linToHex(lin[0],lin[1],lin[2]);
                      alpha=t[4]===undefined?1:clamp01(pct(t[4],1));
                    } else if(/^oklab\(/i.test(value)){
                      const t=value.match(/oklab\(\s*([\d.]+%?)\s+(-?[\d.]+%?)\s+(-?[\d.]+%?)(?:\s*\/\s*([\d.]+%?))?\)/i);
                      if(!t) return null;
                      const lin=oklabToLinSrgb(pct(t[1],1),pct(t[2],0.4),pct(t[3],0.4));
                      out=linToHex(lin[0],lin[1],lin[2]);
                      alpha=t[4]===undefined?1:clamp01(pct(t[4],1));
                    } else if(/^lch\(/i.test(value)){
                      const t=value.match(/lch\(\s*([\d.]+%?)\s+([\d.]+%?)\s+([\d.]+)(?:deg|grad|rad|turn)?\s*(?:\/\s*([\d.]+%?))?\)/i);
                      if(!t) return null;
                      const L=pct(t[1],100), C=Number.parseFloat(t[2]), H=Number.parseFloat(t[3])*Math.PI/180;
                      const lin=labToLinSrgb(L,C*Math.cos(H),C*Math.sin(H));
                      out=linToHex(lin[0],lin[1],lin[2]);
                      alpha=t[4]===undefined?1:clamp01(pct(t[4],1));
                    } else if(/^lab\(/i.test(value)){
                      const t=value.match(/lab\(\s*([\d.]+%?)\s+(-?[\d.]+%?)\s+(-?[\d.]+%?)(?:\s*\/\s*([\d.]+%?))?\)/i);
                      if(!t) return null;
                      const lin=labToLinSrgb(pct(t[1],100),pct(t[2],125),pct(t[3],125));
                      out=linToHex(lin[0],lin[1],lin[2]);
                      alpha=t[4]===undefined?1:clamp01(pct(t[4],1));
                    } else if(/^color-mix\(/i.test(value)){
                      // color-mix(in srgb|oklch..., A p%, B q%) — смешиваем уже
                      // разобранные цвета; oklch-интерполяция аппроксимируется srgb
                      const inner=value.slice(value.indexOf('(')+1,value.lastIndexOf(')'));
                      const segs=inner.split(',').map(s=>s.trim()).filter(Boolean);
                      if(segs.length<3) return null;
                      const a=hexColorMixPart(segs[1]), b=hexColorMixPart(segs[2]);
                      if(!a||!b) return null;
                      const pa=mixPercentOf(segs[1],50), pb=mixPercentOf(segs[2],100-pa);
                      const tot=pa+pb||1;
                      const mix=(i)=>Math.round((a.r*pa/tot+b.r*pb/tot));
                      out='#'+[mix(),mix(),mix()].map(x=>Math.max(0,Math.min(255,x)).toString(16).padStart(2,'0')).join('');
                      const alA=a.alpha??1, alB=b.alpha??1;
                      alpha=(alA*pa+alB*pb)/tot;
                    }
                    else return null;
                    // Порог был .05: полупрозрачные поверхности тёмных UI (white 3–5%
                    // как «чуть светлее фона», рамки 4%) выбрасывались как прозрачные —
                    // AI-ревью мастеров видело «фон темнее оригинала, рамки не те».
                    if(alpha<=.008) return null;
                    return alpha<1 ? out+Math.round(alpha*255).toString(16).padStart(2,'0') : out;
                  };
                  // helpers для color-mix (после hex — рекурсивный разбор частей)
                  function hexColorMixPart(part){
                    const m=part.match(/^(.*?)(?:\s+([\d.]+)%?)?$/);
                    const color=hex(m[1].trim());
                    if(!color) return null;
                    const h=color.length===9?color.slice(1,7):color.slice(1);
                    return {r:parseInt(h.slice(0,2),16),g:parseInt(h.slice(2,4),16),b:parseInt(h.slice(4,6),16),
                      alpha:color.length===9?parseInt(h.slice(6,8),16)/255:1};
                  }
                  function mixPercentOf(part,fallback){
                    const m=part.match(/([\d.]+)%?\s*$/);
                    return m?Number.parseFloat(m[1]):fallback;
                  }
                  const visible = (el,r,cs) => r.width>=1 && r.height>=1 && cs.display!=='none' &&
                    cs.visibility!=='hidden' && Number(cs.opacity)!==0;
                  const safeEnum = (v, allowed, fallback) => allowed.includes(v) ? v : fallback;
                  const SAFE_ALIGNS=['left','center','right','justify','start','end'];
                  const styleOf = (cs, warnings) => {
                    if (cs.backgroundImage && cs.backgroundImage !== 'none') warnings.add('complex background');
                    const deco=(cs.textDecorationLine||'none').split(' ')[0];
                    // per-side borders: uniform -> старые单一 поля; иначе borderSides [T,R,B,L]
                    const bw=[num(cs.borderTopWidth),num(cs.borderRightWidth),num(cs.borderBottomWidth),num(cs.borderLeftWidth)]
                      .map(v=>Math.min(64,Math.max(0,v)));
                    const bc=[hex(cs.borderTopColor),hex(cs.borderRightColor),hex(cs.borderBottomColor),hex(cs.borderLeftColor)];
                    const hasBorder=bw.some(v=>v>0);
                    const uniformW=bw.every(v=>v===bw[0]);
                    const uniformC=bc.every(v=>(v||null)===(bc[0]||null));
                    const lhPx=num(cs.lineHeight);
                    const style={
                      color:hex(cs.color), background:hex(cs.backgroundColor),
                      fontFamily:String(cs.fontFamily||'').replace(/["']/g,'').slice(0,160),
                      fontSize:Math.min(512,Math.max(1,num(cs.fontSize))),
                      fontWeight:Math.min(900,Math.max(100,Number.parseInt(cs.fontWeight,10)||400)),
                      // line-height:unknown (normal) НЕ подставляем 1.2 — рендер
                      // оставляет CSS normal и браузер берёт метрики шрифта
                      lineHeight:lhPx>0?Math.min(10,Math.max(.5,lhPx/Math.max(1,num(cs.fontSize)))):null,
                      letterSpacing:Math.max(-20,Math.min(100,num(cs.letterSpacing))),
                      borderColor:hasBorder?(uniformC?(bc[0]||'#e0e0e0'):null):null,
                      borderWidth:uniformW?bw[0]:null,
                      borderSides:hasBorder&&!uniformW
                        ?bw.map((w,i)=>({width:w,color:bc[i]||'#e0e0e0'})):null,
                      borderRadius:Math.min(1000,Math.max(0,num(cs.borderTopLeftRadius))),
                      boxShadow:cs.boxShadow && cs.boxShadow!=='none' ? cs.boxShadow.slice(0,300) : null,
                      // text-shadow не захватывался вовсе: подсвеченные заголовки
                      // («свечение» акцентного слова) приезжали плоскими.
                      textShadow:cs.textShadow && cs.textShadow!=='none' ? cs.textShadow.slice(0,300) : null,
                      textDecoration:safeEnum(deco,['none','underline','line-through','overline'],'none'),
                      whiteSpace:safeEnum(cs.whiteSpace,['normal','nowrap','pre','pre-wrap','pre-line','break-spaces'],'normal'),
                      overflow:safeEnum(cs.overflow,['visible','hidden','clip','scroll','auto'],'visible'),
                      // flex-shrink:0 — единственное нетривиальное значение (дефолт 1):
                      // карточки горизонтальных scroll-shelf не должны сжиматься в рендере
                      flexShrink:String(cs.flexShrink)==='0'?0:null,
                      textTransform:safeEnum(cs.textTransform,['none','uppercase','lowercase','capitalize'],'none'),
                      fontStyle:cs.fontStyle==='italic'||cs.fontStyle==='oblique'?cs.fontStyle:null,
                      fontVariantNumeric:String(cs.fontVariantNumeric||'').includes('tabular-nums')?'tabular-nums':null,
                      textAlign:SAFE_ALIGNS.includes(cs.textAlign)?cs.textAlign:null,
                      opacity:Math.min(1,Math.max(0,num(cs.opacity))),
                      objectFit:safeEnum(cs.objectFit,['contain','cover','fill','none','scale-down'],'fill'),
                      // фильтры/блендинг: безопасный charset как у boxShadow; url()-фильтры
                      // уходят в raster fallback (внешний ресурс не сериализуется)
                      filter:(cs.filter&&cs.filter!=='none'&&!/url\s*\(/.test(cs.filter))?cs.filter.slice(0,300):null,
                      backdropFilter:(cs.backdropFilter&&cs.backdropFilter!=='none'&&!/url\s*\(/.test(cs.backdropFilter))?cs.backdropFilter.slice(0,300):null,
                      mixBlendMode:safeEnum(cs.mixBlendMode,['normal','multiply','screen','overlay','darken','lighten','color-dodge','color-burn','hard-light','soft-light','difference','exclusion','hue','saturation','color','luminosity'],'normal')==='normal'?null:cs.mixBlendMode,
                      // object-position: выравнивание картинки внутри кадра (crop);
                      // дефолтное 50% 50% не пишем — только явные смещения
                      objectPosition:(()=>{const v=String(cs.objectPosition||'').trim();return v&&v!=='50% 50%'&&/^-?[\d.]+(px|%)?\s+-?[\d.]+(px|%)?$|^(left|center|right|top|bottom)(\s+(left|center|right|top|bottom))?$/.test(v)?v:null;})(),
                      // направление письма: rtl (арабский/иврит) и вертикальный текст (CJK)
                      direction:safeEnum(cs.direction,['ltr','rtl'],'ltr')==='rtl'?'rtl':null,
                      writingMode:safeEnum(cs.writingMode,['horizontal-tb','vertical-rl','vertical-lr','sideways-rl','sideways-lr'],'horizontal-tb')==='horizontal-tb'?null:cs.writingMode,
                      outline:(num(cs.outlineWidth)>0&&cs.outlineStyle!=='none')?Math.min(64,num(cs.outlineWidth)):null,
                      outlineColor:hex(cs.outlineColor)
                    };
                    // masks/clipping — честные визуальные каналы: gradient-mask и
                    // clip-path сериализуем в style (renderer применяет обратно);
                    // url()-mask уходит в raster fallback на уровне compile()
                    // (editable:false слой + element-screenshot), здесь — warning.
                    // Градиентный текст (background-clip:text + color:transparent):
                    // раньше цвет уезжал прозрачным, а градиент срезался как фон —
                    // акцентное слово исчезало. Сохраняем связку целиком.
                    const bgClip=String(cs.backgroundClip||cs.webkitBackgroundClip||'');
                    if(bgClip==='text' && cs.backgroundImage && cs.backgroundImage!=='none'
                        && !/url\s*\(/.test(cs.backgroundImage)){
                      style.backgroundClip='text';
                      style.backgroundImage=cs.backgroundImage.slice(0,800);
                    }
                    const mask=cs.maskImage||cs.webkitMaskImage||'';
                    if(mask && mask!=='none'){
                      if(/url\s*\(/.test(mask)) warnings.add('url mask: raster fallback');
                      else style.maskImage=mask.slice(0,800);
                    }
                    if(cs.clipPath && cs.clipPath!=='none') style.clipPath=cs.clipPath.slice(0,300);
                    return Object.fromEntries(Object.entries(style).filter(([,v])=>v!==null && v!==''));
                  };
                  const cleanTextStyle = (s) => {
                    const out = Object.assign({}, s);
                    delete out.background; delete out.borderColor; delete out.borderWidth;
                    delete out.borderRadius; delete out.boxShadow;
                    // textShadow и градиентная заливка текста — типографика, а не
                    // «краска контейнера»: их вычищать нельзя, иначе подсветка
                    // акцентного слова теряется.
                    if (out.backgroundClip !== 'text') delete out.backgroundImage;
                    return out;
                  };
                  const pathOf = (el,root) => {
                    if(el===root) return 'root'; const parts=[]; let cur=el;
                    while(cur && cur!==root){ const p=cur.parentElement; if(!p) break;
                      const same=[...p.children].filter(x=>x.tagName===cur.tagName);
                      parts.push(cur.tagName.toLowerCase()+':' + (same.indexOf(cur)+1)); cur=p; }
                    return 'root/'+parts.reverse().join('/');
                  };
                  // sourceKey → CSS-селектор от корня блока (для raster-скриншотов
                  // неeditable-поверхностей на стороне scraper-а).
                  const selectorOf=(key)=>String(key||'').split('/').slice(1).map(part=>{
                    const m=part.match(/^([a-z0-9-]+):(\d+)$/i);
                    return m ? m[1]+':nth-of-type('+m[2]+')' : '';
                  }).filter(Boolean).join('>');
                  const justify = (v) => ({'flex-start':'start','flex-end':'end','space-evenly':'space-around'}[v]||v);
                  const align = (v) => ({'flex-start':'start','flex-end':'end','normal':'stretch'}[v]||v);
                  const paddingOf = (cs) => [num(cs.paddingTop),num(cs.paddingRight),num(cs.paddingBottom),num(cs.paddingLeft)].map(v=>Math.round(v));
                  const svgDataUri = (el) => {
                    try {
                      const clone=el.cloneNode(true);
                      clone.setAttribute('xmlns','http://www.w3.org/2000/svg');
                      clone.querySelectorAll('script,foreignObject').forEach(node=>node.remove());
                      const sourceNodes=[el,...el.querySelectorAll('*')];
                      const cloneNodes=[clone,...clone.querySelectorAll('*')];
                      sourceNodes.forEach((source,index)=>{
                        const target=cloneNodes[index]; if(!target) return;
                        const computed=getComputedStyle(source);
                        if(computed.fill && computed.fill!=='none') target.setAttribute('fill',computed.fill);
                        if(computed.stroke && computed.stroke!=='none') target.setAttribute('stroke',computed.stroke);
                        if(computed.strokeWidth) target.setAttribute('stroke-width',computed.strokeWidth);
                        if(computed.strokeLinecap) target.setAttribute('stroke-linecap',computed.strokeLinecap);
                        if(computed.strokeLinejoin) target.setAttribute('stroke-linejoin',computed.strokeLinejoin);
                        if(computed.opacity && computed.opacity!=='1') target.setAttribute('opacity',computed.opacity);
                        target.removeAttribute('class');
                      });
                      const svg=new XMLSerializer().serializeToString(clone);
                      return 'data:image/svg+xml;base64,'+btoa(unescape(encodeURIComponent(svg)));
                    } catch(_) { return ''; }
                  };
                  const overlaps = (a,b) => !(a.right<=b.left+1 || b.right<=a.left+1 || a.bottom<=b.top+1 || b.bottom<=a.top+1);
                  const absUrl = (u) => { try { return new URL(u, document.baseURI).href; } catch (_) { return u; } };
                  // background-image → список визуальных слоёв {kind:'url'|'gradient'}.
                  // Сплит по запятым верхнего уровня (внутри url()/gradient запятые вложенные).
                  const parseBackground = (value) => {
                    const v=String(value||'');
                    if(!v||v==='none') return [];
                    const parts=[]; let depth=0, cur='';
                    for(const ch of v){
                      if(ch==='(') depth++;
                      else if(ch===')') depth=Math.max(0,depth-1);
                      if(ch===','&&depth===0){ parts.push(cur); cur=''; } else cur+=ch;
                    }
                    parts.push(cur);
                    const out=[];
                    for(const partRaw of parts){
                      const part=partRaw.trim();
                      const m=part.match(/url\((['"]?)([^'")]+)\1\)/);
                      if(m){ out.push({kind:'url',url:absUrl(m[2])}); continue; }
                      const g=part.match(/((?:repeating-)?(?:linear|radial|conic)-gradient\(.*\))/);
                      if(g) out.push({kind:'gradient',css:g[1].slice(0,800)});
                    }
                    return out;
                  };
                  const layoutOf = (el,cs,childRects) => {
                    const explicitFlex=cs.display==='flex'||cs.display==='inline-flex';
                    const explicitGrid=cs.display==='grid'||cs.display==='inline-grid';
                    const positionedKids=[...el.children].some(c=>{ const ccs=getComputedStyle(c); return ['absolute','fixed'].includes(ccs.position) || ccs.transform!=='none'; });
                    let direction='column', wrap=false;
                    if(explicitFlex){ direction=cs.flexDirection.startsWith('row')?'row':'column'; wrap=cs.flexWrap!=='nowrap'; }
                    else if(explicitGrid){ direction='row'; wrap=true; }
                    else if(childRects.length>1){
                      const row=childRects.slice(1).every(r=>Math.abs((r.top+r.height/2)-(childRects[0].top+childRects[0].height/2))<Math.max(6,childRects[0].height*.45));
                      direction=row?'row':'column';
                    }
                    const sorted=[...childRects].sort((a,b)=>direction==='row' ? (a.left-b.left || a.top-b.top) : (a.top-b.top || a.left-b.left));
                    const hasOverlap=sorted.some((r,i)=>sorted.slice(i+1).some(o=>overlaps(r,o)));
                    // явный flex/grid с margin-ами на детях: CSS gap не учитывает
                    // margins → flow не соберёт исходные позиции → free + пиннинг
                    const marginedKids=(explicitFlex||explicitGrid) && [...el.children].some(c=>{
                      const m=getComputedStyle(c);
                      return parseFloat(m.marginTop)||parseFloat(m.marginRight)||parseFloat(m.marginBottom)||parseFloat(m.marginLeft);
                    });
                    const flexingKids=explicitFlex && [...el.children].some(c=>num(getComputedStyle(c).flexGrow)>0);
                    // CSS Grid — двухосевая раскладка: wrapping-flex аппроксимация
                    // теряет треки/спаны и «схлопывает» пустые дорожки. Grid всегда
                    // сериализуется как free-layout: каждый ребёнок пиннится по
                    // измеренным x/y и остаётся независимым selectable/editable
                    // слоем внутри своего DOM-родителя (иерархия сохраняется).
                    let auto=(explicitFlex||(!explicitGrid&&childRects.length>0)) && !positionedKids && !hasOverlap && !marginedKids && !flexingKids;
                    // не-flex контейнеры: дети могут быть разведены MARGIN-ами (не gap).
                    // Меряем фактические зазоры: равномерные → auto с measuredGap;
                    // неравномерные → free с пиннингом детей (pixel-perfect).
                    let measuredGap=0;
                    if(auto && !explicitFlex && !explicitGrid && sorted.length>1){
                      const gaps=[];
                      for(let i=1;i<sorted.length;i++){
                        const a=sorted[i-1], b=sorted[i];
                        gaps.push(direction==='row' ? (b.left-(a.left+a.width)) : (b.top-(a.top+a.height)));
                      }
                      if(gaps.some(g=>Math.abs(g-gaps[0])>1.5)) auto=false;
                      else measuredGap=Math.max(0,gaps[0]);
                    }
                    return {layout:auto?'auto':'free',direction,wrap,explicit:explicitFlex||explicitGrid,measuredGap};
                  };
                  const transformKind = (value) => {
                    const raw=String(value||'none').trim();
                    if(!raw||raw==='none') return 'none';
                    const match=raw.match(/^matrix\(\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)\s*,\s*([-+\d.eE]+)\s*\)$/);
                    if(match){
                      const values=match.slice(1).map(Number);
                      if(values.every(Number.isFinite)){
                        // Карусели сжимают неактивные слайды (scale .97–1.02):
                        // это декоративный микро-масштаб, дети уже измерены в
                        // post-transform координатах — bbox точен без matrix.
                        // Растровый fallback из-за 3% масштаба превращал целые
                        // слайды (фото+текст+кнопки) в нередактируемую картинку.
                        // Настоящий поворот (|b|,|c| заметны) остаётся complex.
                        const nearIdentityScale=
                          Math.abs(values[0]-1)<=0.08 && Math.abs(values[3]-1)<=0.08 &&
                          Math.abs(values[1])<0.05 && Math.abs(values[2])<0.05;
                        if(nearIdentityScale) return 'translate';
                      }
                    }
                    return 'complex';
                  };
                  const frameFor = (r,parentRect,cs,parentAuto,isContainer,layout) => {
                    // x/y снимаем ВСЕГДА (даже в auto-родителях): рендерер в auto их
                    // игнорирует, но QA-пасс при дрейфе flow переводит контейнер в free
                    // и пиннит детей по этим координатам = pixel-perfect по конструкции.
                    const frame={width:round2(r.width),height:round2(r.height),
                      x:round2(r.left-parentRect.left),y:round2(r.top-parentRect.top)};
                    const positioned=['absolute','fixed'].includes(cs.position)||cs.transform!=='none';
                    if(positioned || !parentAuto){ frame.absolute=true; }
                    if(isContainer){
                      frame.layout=layout.layout; frame.direction=layout.direction;
                      // gap: у flex/grid — CSS-значения; у блочных — измеренные зазоры
                      frame.gap=layout.explicit
                        ? Math.round(layout.direction==='row'?num(cs.columnGap):num(cs.rowGap))
                        : Math.round(layout.measuredGap||0);
                      frame.padding=paddingOf(cs);
                      frame.justify=safeEnum(justify(cs.justifyContent),['start','center','end','space-between','space-around'],'start');
                      frame.align=safeEnum(align(cs.alignItems),['start','center','end','stretch','baseline'],'start');
                      if(layout.wrap) frame.wrap=true;
                    }
                    if(cs.overflow==='hidden'||cs.overflow==='clip') frame.clip=true;
                    // getBoundingClientRect уже содержит translate. Повторная запись
                    // той же matrix в IR применяла сдвиг второй раз. Complex transforms
                    // компилируются выше как element-screenshot raster fallback.
                    // stacking: явный z-index переносим в frame — рендерер ставит
                    // z-index, и браузер восстанавливает исходный порядок краски.
                    if(cs.zIndex && cs.zIndex!=='auto'){
                      const zi=Number.parseInt(cs.zIndex,10);
                      if(Number.isFinite(zi)) frame.z=Math.max(-1000,Math.min(1000,zi));
                    }
                    return frame;
                  };
                  const collectFontFaces = () => {
                    // Шрифты страницы как в html.to.design: читаем @font-face из
                    // доступных CSSOM-листов (same-origin и CORS-листы), абсолютизируем
                    // url — сервер скачает файлы и положит в базу /fonts.
                    const out = []; const seen = new Set();
                    const abs = (u, base) => { try { return new URL(u, base || document.baseURI).href; } catch (_) { return u; } };
                    const walk = (list, base) => {
                      for (const r of Array.from(list || [])) {
                        if (r.cssRules && r.cssRules.length) { try { walk(r.cssRules, base); } catch (_) {} continue; }
                        const isFace = (typeof CSSFontFaceRule !== 'undefined' && r instanceof CSSFontFaceRule) ||
                          (r.type === CSSRule.FONT_FACE_RULE);
                        if (!isFace) continue;
                        const fam = (r.style.getPropertyValue('font-family') || '').replace(/["']/g, '').trim();
                        if (!fam) continue;
                        const weight = (r.style.getPropertyValue('font-weight') || '400').trim();
                        const fstyle = (r.style.getPropertyValue('font-style') || 'normal').trim();
                        const unicodeRange = (r.style.getPropertyValue('unicode-range') || '').trim();
                        const src = r.style.getPropertyValue('src') || '';
                        const urls = []; const re = /url\((['"]?)([^'")]+)\1\)/g; let m;
                        while ((m = re.exec(src))) urls.push(abs(m[2], base));
                        const key = (fam + '|' + weight + '|' + fstyle + '|' + unicodeRange).toLowerCase();
                        if (urls.length && !seen.has(key)) {
                          seen.add(key);
                          out.push({ family: fam, weight, style: fstyle, unicodeRange, urls: urls.slice(0, 4) });
                        }
                      }
                    };
                    for (const sheet of Array.from(document.styleSheets)) {
                      let rules = null; try { rules = sheet.cssRules; } catch (_) {}
                      if (rules) walk(rules, sheet.href);
                    }
                    // Cross-origin таблицы (CDN, Google Fonts) бросают на
                    // cssRules — их @font-face выше не виден, и страница на
                    // гротеске превращалась в антикву. Реально загруженные
                    // файлы шрифтов доступны через resource timing независимо
                    // от CORS: сопоставляем их с семействами из document.fonts.
                    try {
                      const loaded = [];
                      for (const face of Array.from(document.fonts || [])) {
                        if (face && face.status === 'loaded' && face.family) {
                          loaded.push({
                            family: String(face.family).replace(/["']/g, '').trim(),
                            weight: String(face.weight || '400'),
                            style: String(face.style || 'normal'),
                            unicodeRange: String(face.unicodeRange || ''),
                          });
                        }
                      }
                      const fontUrls = (performance.getEntriesByType('resource') || [])
                        .map(entry => String(entry.name || ''))
                        .filter(name => /\.(woff2?|ttf|otf)(\?|$)/i.test(name));
                      // Одно семейство — один файл: без src в FontFace точного
                      // сопоставления нет, поэтому связываем по порядку загрузки
                      // и не перетираем уже найденные из CSSOM.
                      for (let i = 0; i < loaded.length && i < fontUrls.length; i++) {
                        const face = loaded[i];
                        const key = (face.family + '|' + face.weight + '|' + face.style + '|' + face.unicodeRange).toLowerCase();
                        if (seen.has(key)) continue;
                        seen.add(key);
                        out.push({ ...face, urls: [abs(fontUrls[i])] });
                      }
                    } catch (_) { /* resource timing недоступен — остаёмся с CSSOM */ }
                    return out.slice(0, 24);
                  };
                  const compileBlock = (block) => {
                    const root=document.querySelector(block.selector);
                    if(!root) return {selector:block.selector,error:'DOM element not found'};
                    const rr=root.getBoundingClientRect(), rcs=getComputedStyle(root);
                    if(!visible(root,rr,rcs)) return {selector:block.selector,error:'DOM block is not visible'};
                    const warnings=new Set();
                    let visited=0, emitted=0;
                    const dropped=[];
                    const extras=[];
                    const rasterRequests=[];
                    const assetRequests=[];
                    const paintRects=[];
                    const leafBoxes=[];
                    const isSvgData=(u)=>/^data:image\/svg\+xml/i.test(String(u||''));
                    const recordAsset=(node, apply, selector, w, h)=>{
                      const url=String(node&&node.src||'');
                      if(!url || isSvgData(url)) return;
                      assetRequests.push({
                        sourceKey:String(node.sourceKey||''),
                        url,
                        width:Math.max(1,Math.round(w||1)),
                        height:Math.max(1,Math.round(h||1)),
                        objectFit:(node.style&&node.style.objectFit)||'fill',
                        objectPosition:(node.style&&node.style.objectPosition)||'50% 50%',
                        apply, selector:String(selector||'')
                      });
                    };
                    const recordDropped=(sourceKey,reason,visual=false)=>{
                      dropped.push({sourceKey,reason,visual:!!visual});
                    };
                    const recordExtra=(sourceKey,reason,rect,visual=true)=>{
                      extras.push({sourceKey,reason,visual:!!visual,rect:{
                        x:Math.round(rect.left-rr.left),y:Math.round(rect.top-rr.top),
                        width:Math.round(rect.width),height:Math.round(rect.height)}});
                    };
                    const pushRootRect=(rect,sourceKey)=>{
                      const x=Math.round((rect.left||0)-(rr.left||0));
                      const y=Math.round((rect.top||0)-(rr.top||0));
                      const w=Math.round(rect.width||0);
                      const h=Math.round(rect.height||0);
                      paintRects.push({x,y,width:w,height:h});
                      leafBoxes.push({sourceKey,x,y,width:w,height:h});
                    };
                    /* Структурный отпечаток элемента: тег, раскладка, состав
                     * содержимого и бакеты размеров. Имена CSS-классов сюда не
                     * входят намеренно — Tailwind, CSS-modules и хешированные
                     * классы (css-1x2y3z, sc-hKgILt) делали прежнюю сигнатуру
                     * по первым двум классам бесполезной на большинстве сайтов.
                     * Отпечаток считается по 2 уровням потомков. */
                    const sizeBucket=(value)=>{
                      const v=Math.max(0,Number(value)||0);
                      if(v<=0) return 0;
                      return Math.round(Math.log2(v+1)*2);
                    };
                    const fingerprintCache=new WeakMap();
                    const contentFlags=(el)=>{
                      const flags=[];
                      if(el.querySelector?.('img,svg,picture,video,canvas')) flags.push('m');
                      if(el.querySelector?.('h1,h2,h3,h4,h5,h6')) flags.push('h');
                      if(el.querySelector?.('a[href]')) flags.push('l');
                      if(el.querySelector?.('button,[role="button"],input[type="submit"]')) flags.push('b');
                      if(el.querySelector?.('input,select,textarea')) flags.push('f');
                      const text=String(el.textContent||'').trim();
                      if(text) flags.push('t'+Math.min(4,Math.round(Math.log10(text.length+1))));
                      return flags.join('');
                    };
                    const fingerprintOf=(el,depth)=>{
                      if(!el||!el.tagName) return '';
                      if(depth<=0) return String(el.tagName).toLowerCase();
                      const cached=depth===2?fingerprintCache.get(el):null;
                      if(cached) return cached;
                      let cs=null;
                      try{ cs=getComputedStyle(el); }catch{ cs=null; }
                      const rect=el.getBoundingClientRect?.()||{width:0,height:0};
                      const parts=[
                        String(el.tagName).toLowerCase(),
                        cs?String(cs.display||'').slice(0,10):'',
                        cs?String(cs.flexDirection||'').slice(0,6):'',
                        contentFlags(el),
                        'c'+Math.min(9,el.children?.length||0),
                        'w'+sizeBucket(rect.width),
                        'h'+sizeBucket(rect.height),
                      ];
                      const children=Array.from(el.children||[]).slice(0,6)
                        .map(child=>fingerprintOf(child,depth-1));
                      const value=parts.join('|')+'('+children.join(',')+')';
                      if(depth===2) fingerprintCache.set(el,value);
                      return value;
                    };
                    /* Имя компонента из содержимого, а не из классов: сырые
                     * class-токены раньше утекали в UI Kit как названия семейств
                     * и привязывали таксономию к вёрстке одного сайта. */
                    const labelFrom=(el,role,visualFlags)=>{
                      const aria=String(el.getAttribute?.('aria-label')||el.getAttribute?.('data-component')||'').trim();
                      if(aria) return aria;
                      const heading=el.querySelector?.('h1,h2,h3,h4,h5,h6');
                      const headingText=heading?String(heading.textContent||'').trim():'';
                      if(headingText) return headingText.replace(/\s+/g,' ').slice(0,60);
                      const shape=[];
                      if(visualFlags.includes('m')) shape.push('image');
                      if(visualFlags.includes('t')) shape.push('text');
                      if(visualFlags.includes('b')) shape.push('action');
                      if(visualFlags.includes('f')) shape.push('field');
                      return shape.length?`${role}: ${shape.join(' + ')}`:role;
                    };
                    const componentMetaOf=(el)=>{
                      const tag=String(el.tagName||'').toLowerCase();
                      const ariaRole=String(el.getAttribute?.('role')||'').toLowerCase();
                      const semanticTags=new Set(['nav','form','header','footer','main','section','article','aside']);
                      const semanticRoles=new Set(['navigation','status','toolbar','region','complementary','form']);
                      const parent=el.parentElement;
                      // Повтор по структурному отпечатку: минимум 3 совпадающих
                      // соседа. Порог выше прежних 2 — отпечаток куда менее
                      // строгий, чем совпадение имён классов.
                      let repeatedBoundary=false, repeatIndex=-1, fingerprint='';
                      if(parent && parent.children && parent.children.length>=3){
                        fingerprint=fingerprintOf(el,2);
                        const matching=Array.from(parent.children)
                          .filter(candidate=>fingerprintOf(candidate,2)===fingerprint);
                        if(matching.length>=3){
                          repeatedBoundary=true;
                          repeatIndex=matching.indexOf(el);
                        }
                      }
                      const hasInput=!!el.querySelector?.('input,select,textarea');
                      const hasAction=!!el.querySelector?.('button,[role="button"],input[type="submit"]');
                      const childAlreadyGroupsForm=[...el.children].some(child=>
                        !!child.querySelector?.('input,select,textarea') &&
                        !!child.querySelector?.('button,[role="button"],input[type="submit"]'));
                      const syntheticForm=tag!=='form' && hasInput && hasAction && !childAlreadyGroupsForm;
                      // Визуально обособленный контейнер: собственный фон, рамка
                      // или тень + разнородное содержимое. Так карточка находится
                      // по оформлению, а не по тому, назвал ли её автор «card».
                      let visualCard=false;
                      const flags=contentFlags(el);
                      if(!semanticTags.has(tag) && !repeatedBoundary){
                        let cs=null;
                        try{ cs=getComputedStyle(el); }catch{ cs=null; }
                        if(cs){
                          const painted=!!hex(cs.backgroundColor)
                            || num(cs.borderTopWidth)>0 || num(cs.borderBottomWidth)>0
                            || (cs.boxShadow && cs.boxShadow!=='none')
                            || num(cs.borderTopLeftRadius)>3;
                          const rect=el.getBoundingClientRect?.()||{width:0,height:0};
                          const composite=(flags.match(/[mhlbf]/g)||[]).length>=2;
                          visualCard=painted && composite && rect.width>=48 && rect.height>=32;
                        }
                      }
                      if(!semanticTags.has(tag) && !semanticRoles.has(ariaRole)
                        && !repeatedBoundary && !syntheticForm && !visualCard) return null;
                      const componentRole=syntheticForm?'form':(ariaRole||tag||'component');
                      const meta={kind:'dom',componentBoundary:true,
                        componentRole:componentRole.slice(0,100),
                        componentLabel:labelFrom(el,componentRole,flags).slice(0,100)};
                      if(repeatedBoundary){
                        meta.repeatGroup=(pathOf(parent,root)+'>'+fingerprint).slice(0,500);
                        meta.repeatIndex=repeatIndex;
                      }
                      return meta;
                    };
                    function unionArea(rects){
                      if(!rects.length) return 0;
                      const xs=new Set(), ys=new Set();
                      for(const r of rects){
                        xs.add(r.x); xs.add(r.x+r.width); ys.add(r.y); ys.add(r.y+r.height);
                      }
                      const xa=[...xs].sort((a,b)=>a-b), ya=[...ys].sort((a,b)=>a-b);
                      let area=0;
                      for(let i=0;i<xa.length-1;i++){
                        const x1=xa[i], x2=xa[i+1];
                        for(let j=0;j<ya.length-1;j++){
                          const y1=ya[j], y2=ya[j+1];
                          if(rects.some(r=> r.x<x2 && r.x+r.width>x1 && r.y<y2 && r.y+r.height>y1)){
                            area += (x2-x1)*(y2-y1);
                          }
                        }
                      }
                      return area;
                    }
                    const compile = (el,parentRect,parentAuto,rootEl) => {
                      const tag=String(el.tagName||'').toUpperCase();
                      if(['SCRIPT','STYLE','NOSCRIPT','TEMPLATE'].includes(tag)) return null;
                      const r=el.getBoundingClientRect(), cs=getComputedStyle(el);
                      const key=pathOf(el,rootEl);
                      if(!visible(el,r,cs)){ recordDropped(key,'invisible',false); return null; }
                      visited++;
                      let type='card', role=tag.toLowerCase();
                      if(/^H[1-4]$/.test(tag)) type='heading';
                      else if(el.matches('button,[role="button"]')) type='button';
                      else if(el.matches('input,select,textarea')) type='input';
                      else if(['IMG','SVG','CANVAS','VIDEO','IFRAME'].includes(tag)) type='image';
                      else if(tag==='A' && (hex(cs.backgroundColor)||num(cs.borderTopWidth)>0)) type='button';
                      const isContainerType=type==='card'||type==='button'||type==='input';
                      const style=styleOf(cs,warnings);
                      const elW=Math.max(1,round2(r.width)), elH=Math.max(1,round2(r.height));
                      // Intrinsically non-editable surfaces: видимый selectable
                      // raster fallback (editable:false + причина + source metadata).
                      // Ничего визуального не исчезает молча: растр берётся из
                      // toDataURL/poster, либо scraper делает element-screenshot
                      // по rasterRequests; совсем недоступное — честный visual extra.
                      const hasVisibleKids=[...el.children].some(c=>{
                        const cr=c.getBoundingClientRect(), ccs=getComputedStyle(c);
                        return visible(c,cr,ccs);
                      });
                      const closedShadowSuspect=tag.includes('-') && !el.shadowRoot &&
                        !hasVisibleKids && !String(el.innerText||'').trim();
                      // url()-mask: внешний маскирующий ресурс не сериализуется в
                      // style (CSS-инъекция/недоступность), warning-only терял бы
                      // paint молча — честный selectable raster fallback вместо этого.
                      const maskValue=cs.maskImage||cs.webkitMaskImage||'';
                      const hasUrlMask=!!maskValue && maskValue!=='none' && /url\s*\(/.test(maskValue);
                      const filterValue=cs.filter||'';
                      const hasUrlFilter=!!filterValue && filterValue!=='none' && /url\s*\(/.test(filterValue);
                      const complexTransform=transformKind(cs.transform)==='complex';
                      // open shadow root: shadow-дерево доступно, но обход пока
                      // небезопасен (slots/изоляция стилей) — тот же raster fallback,
                      // видимое содержимое не исчезает молча.
                      const openShadow=!!el.shadowRoot &&
                        (el.shadowRoot.children.length>0 || String(el.shadowRoot.textContent||'').trim().length>0);
                      // Inline SVG: сериализация примитивов (path/rect/circle/…)
                      // поэлементно невозможна, а drop детей как non-container-child
                      // терял иконки молча. Клонируем markup в standalone data:URL
                      // (currentColor резолвится вычисленным color) — точный векторный
                      // слой без element-screenshot. <use>-спрайты и oversized svg —
                      // через element-screenshot raster fallback.
                      if(tag==='SVG'){
                        let svgSrc='';
                        const usesSprite=!!el.querySelector('use');
                        let rawSvg='';
                        try{ rawSvg=el.outerHTML; }catch(_){ rawSvg=''; }
                        if(!usesSprite && rawSvg && !/<script/i.test(rawSvg) && rawSvg.length<=32768){
                          try{
                            const clone=el.cloneNode(true);
                            clone.setAttribute('width',String(Math.max(1,Math.round(r.width))));
                            clone.setAttribute('height',String(Math.max(1,Math.round(r.height))));
                            const fillComputed=String(getComputedStyle(el).fill||'').trim();
                            if(fillComputed && fillComputed!=='none' && !clone.getAttribute('fill'))
                              clone.setAttribute('fill',fillComputed);
                            let text=clone.outerHTML.replace(/currentColor/g,
                              String(getComputedStyle(el).color||'#000').trim()||'#000');
                            if(!/xmlns\s*=/.test(text)) text=text.replace(/^<svg/i,'<svg xmlns="http://www.w3.org/2000/svg"');
                            svgSrc='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(text);
                          }catch(_){ svgSrc=''; }
                        }
                        const svgReason='inline svg: векторный snapshot разметки — примитивы не редактируются поэлементно';
                        const frame=frameFor(r,parentRect,cs,parentAuto,false,{layout:'free',direction:'column',wrap:false,explicit:false,measuredGap:0});
                        const node={type:'image',src:svgSrc,alt:el.getAttribute('aria-label')||'svg icon',
                          sourceKey:key,sourceMeta:{kind:'svg',reason:svgReason},editable:false,lockedReason:svgReason,
                          style:{objectFit:'fill'},frame};
                        if(!svgSrc) rasterRequests.push({sourceKey:key,selector:selectorOf(key)});
                        emitted++; pushRootRect(r,key);
                        return node;
                      }
                      if(['CANVAS','VIDEO','IFRAME'].includes(tag) || closedShadowSuspect || openShadow || hasUrlMask || hasUrlFilter || complexTransform){
                        let kind='shadow-dom', reason='closed shadow root: содержимое недоступно для сериализации', src='';
                        if(tag==='CANVAS'){
                          let gl=false;
                          // getContext('webgl*') на canvas с 2d-контекстом вернёт null
                          // (не создаст), на свежем canvas создаст пустой контекст —
                          // визуально это не меняет ничего (blank == blank).
                          try{ gl=!!(el.getContext('webgl2')||el.getContext('webgl')); }catch(_){}
                          kind=gl?'webgl':'canvas';
                          reason=gl?'webgl canvas: буфер не редактируется поэлементно — растровый snapshot'
                            :'canvas: растровая поверхность — поэлементное редактирование невозможно';
                          try{ src=el.toDataURL('image/png'); }catch(_){ src=''; warnings.add('canvas tainted: element screenshot requested'); }
                        } else if(tag==='VIDEO'){
                          kind='video'; reason='video surface: постер как растровый fallback — содержимое не редактируется';
                          src=el.poster||'';
                        } else if(tag==='IFRAME'){
                          kind='iframe';
                          let sameOrigin=false;
                          try{ sameOrigin=!!(el.contentDocument && el.contentDocument.body); }catch(_){ sameOrigin=false; }
                          reason=sameOrigin?'same-origin iframe: вложенный документ сериализован растром'
                            :'cross-origin iframe: содержимое недоступно (same-origin policy)';
                        } else if(openShadow){
                          kind='shadow-dom';
                          reason='open shadow root: shadow-дерево изолировано — растровый snapshot (обход пока небезопасен)';
                        } else if(hasUrlMask){
                          kind='url-mask';
                          reason='url() mask: внешний маскирующий ресурс не сериализуется — растровый snapshot';
                        } else if(hasUrlFilter){
                          kind='url-mask';
                          reason='url() filter: внешний SVG-фильтр не сериализуется — растровый snapshot';
                        } else if(complexTransform){
                          kind='complex-transform';
                          reason='rotate/scale/skew transform: element screenshot avoids applying measured geometry twice';
                        }
                        const frame=frameFor(r,parentRect,cs,parentAuto,false,{layout:'free',direction:'column',wrap:false,explicit:false,measuredGap:0});
                        const node={type:'image',src,alt:el.alt||el.getAttribute('aria-label')||kind,
                          sourceKey:key,sourceMeta:{kind,reason},editable:false,lockedReason:reason,
                          style:{objectFit:'fill'},frame};
                        rasterRequests.push({sourceKey:key,selector:selectorOf(key)});
                        emitted++; pushRootRect(r,key);
                        return node;
                      }
                      // Синтетические визуальные слои: background-image и ::before/::after
                      // становятся полноценными IR-слоями с source metadata, а не
                      // молча теряются. Порядок краски: bg → before → контент → after.
                      const pseudoLayers=(pseudo,kind)=>{
                        let pcs=null;
                        try{ pcs=getComputedStyle(el,pseudo); }catch(_){ return []; }
                        if(!pcs) return [];
                        const content=String(pcs.content||'none');
                        const textMatch=content.match(/^(['"])([\s\S]*)\1$/);
                        // content:attr(data-text) — рабочая лошадка «текст в разметке, краска в
                        // CSS»: Chrome отдаёт его нерезолвленным, и целые заголовки уезжали в
                        // потери. Значение берём с самого элемента.
                        const attrMatch=content.match(/^attr\(\s*([-\w]+)\s*\)$/);
                        const attrText=attrMatch ? String(el.getAttribute(attrMatch[1])||'').trim() : '';
                        const pseudoText=textMatch ? textMatch[2] : attrText;
                        const hasTextContent=!!(pseudoText && pseudoText.trim());
                        const hasUnserializableContent=!!content && content!=='none' && content!=='normal'
                          && !textMatch && !hasTextContent;
                        const hasContent=hasTextContent || hasUnserializableContent;
                        const bgL=parseBackground(pcs.backgroundImage);
                        const bgColor=hex(pcs.backgroundColor);
                        if(!hasContent && !bgL.length && !bgColor) return [];
                        // Бокс: абсолютно спозиционированный pseudo меряем по его
                        // offset-ам; inline pseudo делит line box с элементом —
                        // якорим на бокс элемента (объединение с paint элемента не
                        // раздувает coverage).
                        let x=0,y=0,w=elW,h=elH;
                        if(pcs.position==='absolute'||pcs.position==='fixed'){
                          const left=num(pcs.left),top=num(pcs.top),right=num(pcs.right),bottom=num(pcs.bottom);
                          w=Math.max(1,Math.round(num(pcs.width)||(elW-left-right)||elW));
                          h=Math.max(1,Math.round(num(pcs.height)||(elH-top-bottom)||elH));
                          x=Math.round(num(pcs.left)||(elW-right-w));
                          y=Math.round(num(pcs.top)||(elH-bottom-h));
                        }
                        const frame={absolute:true,x,y,width:w,height:h};
                        const skey=key+'::'+kind;
                        if(bgL.length){
                          // CSS background: первый слой верхний. В IR-порядке краски
                          // (снизу вверх) идём с хвоста списка; ключи уникальны по
                          // CSS-индексу (стабильная идентичность слоя).
                          if(hasContent){
                            // bg + текстовый content одного pseudo не помещаются в
                            // один слой — контент журналируем как честную потерю.
                            recordExtra(skey,'pseudo-content',r,true);
                          }
                          const fit=pcs.backgroundSize==='cover'?'cover':pcs.backgroundSize==='contain'?'contain':'fill';
                          const out=[];
                          for(let i=bgL.length-1;i>=0;i--){
                            const bg=bgL[i];
                            const lkey=bgL.length>1 ? skey+'-bg'+i : skey;
                            if(bg.kind==='url'){
                              const layer={type:'image',src:bg.url,alt:'',sourceKey:lkey,
                                sourceMeta:{kind,url:bg.url,layer:i},style:{objectFit:fit},frame};
                              recordAsset(layer,'background',selectorOf(key),w,h);
                              out.push(layer);
                            } else out.push({type:'rect',fill:'#00000000',radius:Math.min(1000,Math.max(0,num(pcs.borderTopLeftRadius))),
                              sourceKey:lkey,sourceMeta:{kind,reason:'gradient',layer:i},style:{backgroundImage:bg.css},frame});
                          }
                          return out;
                        }
                        if(hasTextContent){
                          return [{type:'text',text:pseudoText.slice(0,1000),sourceKey:skey,
                            sourceMeta:{kind},style:cleanTextStyle(styleOf(pcs,warnings)),frame}];
                        }
                        if(hasContent && !hasTextContent){
                          // counters/attr()/url() в content сериализовать не можем —
                          // журналируем как честно потерянный визуальный канал.
                          recordExtra(skey,'pseudo-content',r,true);
                        }
                        if(bgColor) return [{type:'rect',fill:bgColor,radius:Math.min(1000,Math.max(0,num(pcs.borderTopLeftRadius))),
                          sourceKey:skey,sourceMeta:{kind},style:{},frame}];
                        return [];
                      };
                      // background-clip:text — это заливка глифов, а не фон блока:
                      // синтетический слой нарисовал бы градиентный прямоугольник
                      // поверх текста. Градиент уже уехал в style (styleOf).
                      const clipsTextFill=String(cs.backgroundClip||cs.webkitBackgroundClip||'')==='text';
                      const bgLayers=clipsTextFill?[]:parseBackground(cs.backgroundImage);
                      const beforeLayers=pseudoLayers('::before','pseudo-before');
                      const afterLayers=pseudoLayers('::after','pseudo-after');
                      const bgLayerFor=(bg,i)=>{
                        const fit=cs.backgroundSize==='cover'?'cover':cs.backgroundSize==='contain'?'contain':'fill';
                        const lkey=bgLayers.length>1 ? key+'::bg'+i : key+'::bg';
                        if(bg.kind==='url'){
                          const layer={type:'image',src:bg.url,alt:'',sourceKey:lkey,
                            sourceMeta:{kind:'background-image',url:bg.url,layer:i},
                            style:{objectFit:fit},frame:{absolute:true,x:0,y:0,width:elW,height:elH}};
                          recordAsset(layer,'background',selectorOf(key),elW,elH);
                          return layer;
                        }
                        return {type:'rect',fill:'#00000000',radius:Math.min(1000,Math.max(0,num(cs.borderTopLeftRadius))),
                          sourceKey:lkey,sourceMeta:{kind:'background-image',reason:'gradient',layer:i},
                          style:{backgroundImage:bg.css},frame:{absolute:true,x:0,y:0,width:elW,height:elH}};
                      };
                      const directText=String(el.innerText||el.textContent||'').replace(/\s+/g,' ').trim();
                      const childRects=[...el.children].map(c=>c.getBoundingClientRect()).filter(x=>x.width>=1&&x.height>=1);
                      const layout=layoutOf(el,cs,childRects);
                      const childParentAuto=layout.layout==='auto';
                      const visibleChildEls=[...el.children].filter(c=>{
                        const cr=c.getBoundingClientRect(), ccs=getComputedStyle(c);
                        return visible(c,cr,ccs);
                      });
                      const hasElementChildren=visibleChildEls.length>0;
                      const neutralTextTag=el.matches('span,strong,em,b,i,small,label,p');
                      const INLINE_TAGS=new Set(['strong','em','b','i','a','span','mark','code','small','br','sub','sup']);
                      const inlineOnly=visibleChildEls.length>0 &&
                        visibleChildEls.every(c=>INLINE_TAGS.has(String(c.tagName||'').toLowerCase()));
                      // inline-ребёнок «ломает» слияние с текстом родителя:
                      // собственная краска (bg/border/shadow/pseudo) или другая
                      // типографика — тогда он обязан стать отдельным text-слоем
                      const inlineBreaksMerging=(cand)=>{
                        return [cand,...cand.querySelectorAll('*')].some(candidate=>{
                        const ccs=getComputedStyle(candidate);
                        const ownPaint=!!hex(ccs.backgroundColor) || parseBackground(ccs.backgroundImage).length>0 ||
                          [ccs.borderTopWidth,ccs.borderRightWidth,ccs.borderBottomWidth,ccs.borderLeftWidth].some(v=>num(v)>0) ||
                          (!!ccs.boxShadow && ccs.boxShadow!=='none');
                        let pseudoPaint=false;
                        for(const pseudo of ['::before','::after']){
                          try{
                            const pcs=getComputedStyle(candidate,pseudo), content=String(pcs.content||'none');
                            const match=content.match(/^(['"])([\s\S]*)\1$/);
                            if((match && match[2].trim()) || (content!=='none' && content!=='normal' && !match) ||
                                !!hex(pcs.backgroundColor) || parseBackground(pcs.backgroundImage).length>0){
                              pseudoPaint=true; break;
                            }
                          }catch(_){}
                        }
                        // textShadow и background-clip:text — самостоятельные
                        // визуальные каналы акцентного слова: без них подсвеченный
                        // спан молча сливался с текстом родителя.
                        const clipsText=String(ccs.backgroundClip||ccs.webkitBackgroundClip||'')==='text';
                        const typographyDiff=ccs.fontFamily!==cs.fontFamily || ccs.fontSize!==cs.fontSize ||
                          ccs.fontWeight!==cs.fontWeight || ccs.color!==cs.color ||
                          ccs.letterSpacing!==cs.letterSpacing || ccs.textTransform!==cs.textTransform ||
                          ccs.textShadow!==cs.textShadow || clipsText;
                        return ownPaint || pseudoPaint || typographyDiff;
                        });
                      };
                      const childBreaksTextMerging=visibleChildEls.some(c=>inlineBreaksMerging(c));
                      const textOnly=isContainerType && directText && neutralTextTag &&
                        (!hasElementChildren || (inlineOnly && !childBreaksTextMerging)) &&
                        !bgLayers.length && !beforeLayers.length && !afterLayers.length &&
                        !hex(cs.backgroundColor) && num(cs.borderTopWidth)===0 && (!cs.boxShadow || cs.boxShadow==='none');
                      if(textOnly) type='text';
                      // type may have changed to text/heading/image; recompute container flag
                      const isContainer=type==='card'||type==='button'||type==='input';
                      // visual channels the editable IR tree cannot represent yet
                      // (background-image и ::before/::after уже перенесены в
                      // синтетические слои выше, canvas/iframe/shadow — в raster
                      // fallback — они больше не lost channels)
                      const rawChildren=[];
                      // split-inline: у text/heading-родителя появились отдельные
                      // text-слои с собственной типографикой — поглощённый текст
                      // родителя надо ограничить прямыми текст-нодами (иначе дубль)
                      let splitInlineKids=false, directOnlyText='';
                      // Прямые текст-ноды текстового узла: пока просто копим ссылки.
                      // Понадобятся, только если у этого же узла найдётся inline-акцент
                      // со своей типографикой (см. splitTextLayers ниже).
                      let splitTextLayers=false; const inlineTextNodes=[];
                      // Дети, которые занимают место в оригинальном потоке, но в IR
                      // не попали (скрыты по opacity, схлопнуты как пустые): flow
                      // без них съезжает — см. пиннинг после сборки детей.
                      let droppedFlowKids=0;
                      /* Строки одной текст-ноды. Объединённый bbox многострочного
                       * текста начинается у левого края (вторая строка), поэтому
                       * рендер сдвигал первую строку под соседний inline-акцент
                       * («Output:» печатался поверх «who to email…»). Режем ноду по
                       * строкам через Range.getClientRects и отдаём слой на строку. */
                      const textLineLayers=(tn,idx)=>{
                        const raw=tn.textContent||'';
                        const range=document.createRange();
                        const rectsOf=(from,to)=>{
                          range.setStart(tn,from); range.setEnd(tn,to);
                          return [...range.getClientRects()].filter(x=>x.width>0.5&&x.height>0.5);
                        };
                        const alignMap={start:'left',end:'right',left:'left',center:'center',right:'right',justify:'justify'};
                        const layers=[]; let start=0, guard=0;
                        while(start<raw.length && guard++<64){
                          if(!rectsOf(start,raw.length).length) break;
                          // самый длинный префикс, укладывающийся в одну строку
                          let lo=start+1, hi=raw.length, best=start+1;
                          while(lo<=hi){
                            const mid=(lo+hi)>>1;
                            if(rectsOf(start,mid).length<=1){ best=mid; lo=mid+1; } else hi=mid-1;
                          }
                          const rects=rectsOf(start,best);
                          const piece=raw.slice(start,best).replace(/\s+/g,' ').trim();
                          if(piece && rects.length){
                            const lr=rects[0];
                            const lstyle=cleanTextStyle(styleOf(cs,warnings));
                            const align=alignMap[lstyle.textAlign]||null;
                            delete lstyle.textAlign;
                            layers.push({type:'text',text:piece.slice(0,1000),
                              sourceKey:key+'::text'+idx+'l'+start,align,style:lstyle,
                              frame:{width:round2(lr.width),height:round2(lr.height),
                                x:round2(lr.left-r.left),y:round2(lr.top-r.top),absolute:true},
                              __domIdx:idx});
                          }
                          start=best;
                        }
                        return layers;
                      };
                      [...el.childNodes].forEach((child,idx)=>{
                        if(child.nodeType===Node.TEXT_NODE){
                          const text=(child.textContent||'').replace(/\s+/g,' ').trim();
                          if(text) directOnlyText=(directOnlyText+' '+text).trim();
                          if(text && !isContainer) inlineTextNodes.push({node:child,idx});
                          if(!text || !isContainer) return;
                          const range=document.createRange(); range.selectNodeContents(child); const tr=range.getBoundingClientRect();
                          if(tr.width<1||tr.height<1) return;
                          const lines=[...range.getClientRects()].filter(x=>x.width>0.5&&x.height>0.5);
                          if(lines.length>1){
                            const layers=textLineLayers(child,idx);
                            if(layers.length>1){
                              for(const layer of layers){
                                rawChildren.push(layer);
                                emitted++;
                                pushRootRect({left:r.left+layer.frame.x,top:r.top+layer.frame.y,
                                  width:layer.frame.width,height:layer.frame.height},layer.sourceKey);
                              }
                              return;
                            }
                          }
                          // субпиксельная точность: округление в целый px и надбавка
                          // +2px сдвигали глифы на доли px и портили сходство
                          const textFrame={width:round2(tr.width),height:round2(tr.height),
                            x:round2(tr.left-r.left),y:round2(tr.top-r.top)};
                          if(!childParentAuto){ textFrame.absolute=true; }
                          const tstyle=cleanTextStyle(styleOf(cs,warnings));
                          // IR-enum align уже́е CSS: start/end сводим к физическим сторонам (LTR)
                          const talign={start:'left',end:'right',left:'left',center:'center',right:'right',justify:'justify'}[tstyle.textAlign]||null;
                          delete tstyle.textAlign;
                          const tnode={type:'text',text:text.slice(0,1000),sourceKey:key+'::text'+idx,
                            align:talign,style:tstyle,frame:textFrame};
                          rawChildren.push(tnode);
                          emitted++; pushRootRect({left:r.left+textFrame.x,top:r.top+textFrame.y,width:textFrame.width,height:textFrame.height},tnode.sourceKey);
                        } else if(child.nodeType===Node.ELEMENT_NODE){
                          const ccr=child.getBoundingClientRect(), ccs=getComputedStyle(child);
                          if(!visible(child,ccr,ccs)){
                            if(ccr.width>=1 && ccr.height>=1 && ccs.display!=='none'
                               && ccs.position!=='absolute' && ccs.position!=='fixed') droppedFlowKids++;
                            return;
                          }
                          if(!isContainer){
                            const ctag=String(child.tagName||'').toLowerCase();
                            const ctext=(child.textContent||'').replace(/\s+/g,' ').trim();
                            if(INLINE_TAGS.has(ctag) && ctext && !inlineBreaksMerging(child)){
                              // однотипографический inline-ребёнок: текст уже
                              // поглощён node.text родителя — это НЕ потеря
                              recordDropped(pathOf(child,rootEl),'merged-into-text',false);
                              return;
                            }
                            if(INLINE_TAGS.has(ctag) && ctext){
                              // собственная краска/типографика (цветная ссылка
                              // в заголовке, bold-акцент): отдельный text-слой с
                              // точным rect и СВОИМ стилем, а не drop
                              const cframe={width:round2(ccr.width),height:round2(ccr.height),
                                x:round2(ccr.left-r.left),y:round2(ccr.top-r.top),absolute:true};
                              const cstyle=cleanTextStyle(styleOf(ccs,warnings));
                              const calign={start:'left',end:'right',left:'left',center:'center',right:'right',justify:'justify'}[cstyle.textAlign]||null;
                              delete cstyle.textAlign;
                              rawChildren.push({type:'text',text:ctext.slice(0,1000),
                                sourceKey:pathOf(child,rootEl),align:calign,style:cstyle,frame:cframe,__domIdx:idx});
                              emitted++;
                              pushRootRect({left:r.left+cframe.x,top:r.top+cframe.y,width:cframe.width,height:cframe.height},pathOf(child,rootEl));
                              splitInlineKids=true;
                              return;
                            }
                            recordDropped(pathOf(child,rootEl),'non-container-child',true);
                            return;
                          }
                          const compiled=compile(child,r,childParentAuto,rootEl);
                          if(!compiled && ccs.position!=='absolute' && ccs.position!=='fixed') droppedFlowKids++;
                          if(compiled){
                            // CSS order у flex-детей: визуальный порядок может
                            // отличаться от DOM; сортим позже по __flexOrder
                            const o=Number(getComputedStyle(child).order)||0;
                            if(o) compiled.__flexOrder=o;
                            // margin:0 auto центрирует блок в auto-layout:
                            // computed style резолвит 'auto' в пиксели, поэтому
                            // детект — симметричные ненулевые боковые маргины.
                            // Flow-раскладка рендера это не воспроизводит —
                            // пинним по измеренным координатам.
                            const cml=num(ccs.marginLeft), cmr=num(ccs.marginRight);
                            if(childParentAuto && ccs.display!=='inline' &&
                               cml>0.5 && Math.abs(cml-cmr)<1){
                              compiled.frame.absolute=true;
                            }
                            rawChildren.push(compiled);
                          }
                        }
                      });
                      // Текст с inline-акцентом («**Output:** verified send list»):
                      // акцент уже вынесен в absolute-слой по своему rect, а текст
                      // родителя рисовался с начала бокса и наползал на него. Режем
                      // прямые текст-ноды на СТРОКИ (Range.getClientRects) и кладём
                      // каждую строку своим absolute-слоем: первая строка встаёт
                      // после акцента, остальные — от левого края, как в браузере.
                      if(splitInlineKids && inlineTextNodes.length){
                        for(const item of inlineTextNodes){
                          for(const layer of textLineLayers(item.node,item.idx)){
                            rawChildren.push(layer);
                            emitted++;
                            pushRootRect({left:r.left+layer.frame.x,top:r.top+layer.frame.y,
                              width:layer.frame.width,height:layer.frame.height},layer.sourceKey);
                            splitTextLayers=true;
                          }
                        }
                        if(splitTextLayers) rawChildren.sort((a,b)=>((a&&a.__domIdx)||0)-((b&&b.__domIdx)||0));
                      }
                      for(const c of rawChildren){ if(c) delete c.__domIdx; }
                      if(type==='button' && childParentAuto && directText && rawChildren.length){
                        const collectText=(item)=>{
                          if(!item || typeof item!=='object') return '';
                          if(item.type==='text' || item.type==='heading') return String(item.text||'');
                          return (item.children||[]).map(collectText).filter(Boolean).join(' ');
                        };
                        const childText=rawChildren.map(collectText).filter(Boolean).join(' ').replace(/\s+/g,' ').trim();
                        let missing='', atStart=false;
                        if(childText && directText!==childText && directText.endsWith(childText)){
                          missing=directText.slice(0,directText.length-childText.length).trim(); atStart=true;
                        } else if(childText && directText!==childText && directText.startsWith(childText)){
                          missing=directText.slice(childText.length).trim();
                        }
                        if(missing){
                          const canvas=document.createElement('canvas'), ctx=canvas.getContext('2d');
                          if(ctx) ctx.font=String(cs.fontWeight)+' '+String(cs.fontSize)+' '+String(cs.fontFamily);
                          const linePx=Math.max(1,Math.round(num(cs.lineHeight)||num(cs.fontSize)*1.2));
                          const implicit={type:'text',text:missing.slice(0,120),sourceKey:key+(atStart?'::implicit-prefix':'::implicit-suffix'),
                            style:cleanTextStyle(styleOf(cs,warnings)),frame:{width:Math.max(1,Math.ceil(ctx ? ctx.measureText(missing).width : num(cs.fontSize))),height:linePx}};
                          if(atStart) rawChildren.unshift(implicit); else rawChildren.push(implicit);
                          emitted++;
                          // leafBox не записываем: узел потоковый (x/y нет), позиция
                          // известна только после layout — захваченный (0,0) давал
                          // фантомную ошибку bbox ~11px в fidelity-метриках
                        }
                      }
                      const node={type,sourceKey:key,style,frame:frameFor(r,parentRect,cs,parentAuto,isContainer,layout)};
                      // Flex может визуально переупорядочить детей: column/row-REVERSE
                      // и CSS order. IR хранит детей в визуальном порядке (renderer
                      // Flow-агностичен) — иначе рендер раскладывает по DOM-порядку
                      // и блоки меняются местами (цена под заголовком и т.п.).
                      if(layout.explicit && rawChildren.length>1){
                        if(String(cs.flexDirection||'').endsWith('-reverse')){
                          // все flex-элементы (включая потоковые text-узлы)
                          // участвуют в reverse-потоке
                          rawChildren.reverse();
                        }
                        let hasOrder=false;
                        for(const c of rawChildren){ if(c&&c.__flexOrder){hasOrder=true;break;} }
                        if(hasOrder){
                          rawChildren.sort((a,b)=>((a&&a.__flexOrder)||0)-((b&&b.__flexOrder)||0));
                        }
                        for(const c of rawChildren){ if(c) delete c.__flexOrder; }
                      }
                      // text-align элемента-текста (<p>, <h1>) — в IR-поле align
                      // (enum уже́е CSS: start/end сводим к физическим сторонам)
                      if(type==='text'||type==='heading'){
                        const a={start:'left',end:'right',left:'left',center:'center',right:'right',justify:'justify'}[style.textAlign]||null;
                        if(a) node.align=a;
                        delete style.textAlign;
                      }
                      const componentMeta=componentMetaOf(el);
                      if(componentMeta) node.sourceMeta=componentMeta;
                      const ownText=splitTextLayers?'':(splitInlineKids?directOnlyText:directText);
                      if(type==='heading'){ node.level=Number(tag.slice(1)); node.text=ownText.slice(0,1000); }
                      if(type==='text') node.text=ownText.slice(0,1000);
                      if(type==='button') node.text=String(el.innerText||'').replace(/\s+/g,' ').trim().slice(0,1000);
                      if(type==='input'){
                        node.placeholder=(el.value||el.placeholder||el.options?.[el.selectedIndex]?.text||'').slice(0,1000);
                        const value=node.placeholder;
                        if(value && !rawChildren.length){
                          const pad=paddingOf(cs), linePx=Math.max(1,Math.round(num(cs.lineHeight)||num(cs.fontSize)*1.2));
                          const textStyle=cleanTextStyle(Object.assign({},style,{whiteSpace:'nowrap',overflow:'hidden'}));
                          const vnode={type:'text',text:value,sourceKey:key+'::value',style:textStyle,frame:{
                            width:Math.max(1,Math.round(r.width)-pad[1]-pad[3]),height:Math.min(Math.max(1,Math.round(r.height)),linePx),
                            absolute:true,x:pad[3],y:Math.max(0,Math.round((r.height-linePx)/2))
                          }};
                          rawChildren.push(vnode);
                          emitted++; pushRootRect({left:r.left+(vnode.frame.x||0),top:r.top+(vnode.frame.y||0),width:vnode.frame.width,height:vnode.frame.height},vnode.sourceKey);
                        }
                      }
                      if(type==='button' && node.text && !rawChildren.length){
                        const linePx=Math.max(1,Math.round(num(cs.lineHeight)||num(cs.fontSize)*1.2));
                        const vnode={type:'text',text:node.text,sourceKey:key+'::text',style:cleanTextStyle(styleOf(cs,warnings)),frame:{
                          width:Math.max(1,Math.round(r.width)),height:Math.min(Math.max(1,Math.round(r.height)),linePx),
                          absolute:true,x:0,y:Math.max(0,Math.round((r.height-linePx)/2))
                        }};
                        rawChildren.push(vnode);
                        emitted++; pushRootRect({left:r.left+(vnode.frame.x||0),top:r.top+(vnode.frame.y||0),width:vnode.frame.width,height:vnode.frame.height},vnode.sourceKey);
                      }
                      if(type==='image'){
                        // CANVAS/VIDEO/IFRAME/shadow уже ушли в raster fallback выше.
                        if(tag==='IMG'){
                          node.src=el.currentSrc||el.src||'';
                          if(node.src){
                            // sourceMeta обязан нести kind (IR schema: required):
                            // обычный <img> без componentBoundary получает kind:'dom'
                            node.sourceMeta=Object.assign({},node.sourceMeta||{kind:'dom'},{url:node.src});
                            recordAsset(node,'img',selectorOf(key),elW,elH);
                          }
                        }
                        else if(tag==='SVG') node.src=svgDataUri(el);
                        else { node.src=el.poster||''; warnings.add('video poster fallback'); }
                        node.alt=el.alt||el.getAttribute('aria-label')||'';
                      }
                      // Собираем итоговых детей в порядке краски: background-image
                      // (дно) → ::before → DOM-контент → ::after (верх). Каждый
                      // синтетический слой — полноценный IR-узел: считается в
                      // emitted/leaf/paint-метриках наравне с DOM-слоями.
                      const allChildren=[];
                      const addSynth=(layer)=>{
                        emitted++;
                        pushRootRect({left:r.left+layer.frame.x,top:r.top+layer.frame.y,
                          width:layer.frame.width,height:layer.frame.height},layer.sourceKey);
                        allChildren.push(layer);
                      };
                      if(isContainer){
                        // Все background-слои, а не только первый: CSS-порядок
                        // (первый верхний) разворачиваем в paint-порядок (снизу вверх).
                        for(let i=bgLayers.length-1;i>=0;i--) addSynth(bgLayerFor(bgLayers[i],i));
                        beforeLayers.forEach(addSynth);
                        allChildren.push(...rawChildren);
                        afterLayers.forEach(addSynth);
                      } else {
                        // Отделённые inline-акценты (подсвеченное слово внутри
                        // заголовка) обязаны доехать: без этого они исчезали
                        // молча — текст родителя их уже не содержал, а своего
                        // слоя они не получали.
                        if(splitInlineKids) allChildren.push(...rawChildren);
                        // Синтетические каналы неконтейнерный тип нести не может —
                        // журналируем честно.
                        if(bgLayers.length) recordExtra(key,'background-image',r,true);
                        beforeLayers.forEach(l=>recordExtra(l.sourceKey,'pseudo',r,true));
                        afterLayers.forEach(l=>recordExtra(l.sourceKey,'pseudo',r,true));
                      }
                      // split-inline дети у text/heading — иначе цветные ссылки
                      // в заголовках терялись (node.text без детей не рендерится)
                      if((isContainer || splitInlineKids) && allChildren.length) node.children=allChildren;
                      // Смешанный режим ломает раскладку: ребёнок с transform
                      // (или поднятый flatten-ом из обёртки) уже помечен absolute
                      // и выпал из потока, а соседи, оставшиеся в flow, встают на
                      // его место — метка колонки печаталась поверх первой ссылки,
                      // правая группа space-between уезжала в левый край. Если
                      // среди DOM-детей auto-контейнера есть хоть один пиннутый,
                      // пиннем контейнер целиком: x/y у всех уже сняты от него,
                      // поэтому позиции остаются pixel-perfect по конструкции.
                      // Синтетические слои (фон, ::before/::after) в счёт не идут —
                      // они absolute всегда и не должны сносить auto-flow.
                      if(node.frame.layout==='auto' && (droppedFlowKids>0
                          || rawChildren.some(child=>child&&child.frame&&child.frame.absolute))){
                        node.frame.layout='free';
                        allChildren.forEach(child=>{ if(child&&child.frame) child.frame.absolute=true; });
                      }
                      // Renderer uses a dedicated source-control/source-input wrapper.
                      // Keeping their measured children in auto flow discards captured
                      // x/y (notably button text padding). Pin inner parts so the
                      // editable text/value layer stays at the exact DOM bbox.
                      if((type==='button'||type==='input') && allChildren.length){
                        node.frame.layout='free';
                        allChildren.forEach(child=>{
                          if(child&&child.frame) child.frame.absolute=true;
                        });
                      }
                      if(type==='card') node.role=role;
                      const pad=node.frame.padding||[0,0,0,0]; const neutral=!style.background && !style.borderWidth && !style.boxShadow && pad.every(x=>x===0);
                      const semantic=el.matches('nav,form,header,footer,main,section,article,button,input,select,textarea,a,[role]')||!!el.id||!!componentMeta;
                      const explicitLayout=['flex','inline-flex','grid','inline-grid'].includes(cs.display);
                      if(type==='card' && allChildren.length===0 && neutral && !explicitLayout && num(cs.flexGrow)<=0){ recordDropped(key,'collapsed-neutral',false); return null; }
                      if(type==='card' && allChildren.length===1 && neutral && !semantic && !explicitLayout && layout.layout!=='auto') {
                        const only=allChildren[0];
                        recordDropped(key,'flattened',false);
                        const of=only.frame||{};
                        // Координаты пересчитываем на деда всегда, а вот absolute
                        // навешивать можно только когда дед НЕ auto: в auto-flow
                        // пиннинг вырывал поднятого ребёнка из потока, и соседи,
                        // оставшиеся в flow, съезжали на его место (метка поверх
                        // заголовка колонки; правая группа space-between уезжала
                        // в левый край, потому что в потоке оставался один ребёнок).
                        const flatFrame={
                          x:Math.round(r.left-parentRect.left+(Number(of.x)||0)),
                          y:Math.round(r.top-parentRect.top+(Number(of.y)||0))
                        };
                        if(!parentAuto || of.absolute) flatFrame.absolute=true;
                        only.frame=Object.assign({}, of, flatFrame);
                        // обёртка выброшена: она не попадает ни в emitted, ни в
                        // paint/leaf-метрики (считаются только вернувшиеся IR-узлы)
                        return only;
                      }
                      // emitted/leaf/paint метрики инкрементируем только для узлов,
                      // реально попавших в IR: collapsed-neutral/flattened обёртки
                      // не должны раздувать editableLayers.
                      emitted++; pushRootRect(r,key);
                      return node;
                    };
                    const rootChildRects=[...root.children].map(c=>c.getBoundingClientRect()).filter(x=>x.width>=1&&x.height>=1);
                    const rootLayout=layoutOf(root,rcs,rootChildRects);
                    const rootAuto=rootLayout.layout==='auto';
                    const rootCentered=rootAuto && rootLayout.direction==='column' && rootChildRects.length>0 &&
                      rootChildRects.every(r=>Math.abs((r.left+r.width/2)-(rr.left+rr.width/2))<=2);
                    const rootAlign=rootCentered ? 'center' : safeEnum(align(rcs.alignItems),['start','center','end','stretch','baseline'],'start');
                    // background-image корня — синтетический слой на дне rootChildren
                    // (как у обычных элементов), а не lost channel.
                    const rootBgLayers=parseBackground(rcs.backgroundImage);
                    let inheritedBackdrop=null;
                    if(!hex(rcs.backgroundColor) && !rootBgLayers.length){
                      for(let ancestor=root.parentElement;ancestor;ancestor=ancestor.parentElement){
                        const acs=getComputedStyle(ancestor), color=hex(acs.backgroundColor);
                        if(color){ inheritedBackdrop=color; break; }
                      }
                    }
                    if(rr.width>=1 && rr.height>=1 && (hex(rcs.backgroundColor) || num(rcs.borderTopWidth)>0)){
                      paintRects.push({x:0,y:0,width:Math.round(rr.width),height:Math.round(rr.height)});
                    }
                    const rootChildren=[];
                    if(inheritedBackdrop){
                      const rootArea=Math.max(1,rr.width*rr.height);
                      const directRects=rootChildRects.map(rect=>({
                        x:rect.left-rr.left,y:rect.top-rr.top,width:rect.width,height:rect.height}));
                      const directCoverage=100*unionArea(directRects)/rootArea;
                      const stableSolid=rr.width<=480 && directCoverage>=98;
                      const reason='inherited page backdrop: locked raster fallback';
                      const solidSvg=stableSolid ? 'data:image/svg+xml,'+encodeURIComponent(
                        '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"><rect width="1" height="1" fill="'+inheritedBackdrop+'"/></svg>') : '';
                      const backdrop={type:'image',src:solidSvg,alt:'Inherited page backdrop',editable:false,
                        lockedReason:reason,sourceKey:'root::backdrop',
                        sourceMeta:{kind:'inherited-background',reason:'raster-fallback'},style:{objectFit:'fill'},
                        frame:{absolute:true,x:0,y:0,width:Math.max(1,Math.round(rr.width)),height:Math.max(1,Math.round(rr.height))}};
                      rootChildren.push(backdrop);
                      if(!stableSolid) rasterRequests.push({sourceKey:backdrop.sourceKey,selector:'',mode:'backdrop'});
                      emitted++; pushRootRect(rr,backdrop.sourceKey);
                    }
                    [...root.childNodes].forEach((child,idx)=>{
                      if(child.nodeType===Node.TEXT_NODE){
                        const text=(child.textContent||'').replace(/\s+/g,' ').trim();
                        if(text){
                          const range=document.createRange(); range.selectNodeContents(child); const tr=range.getBoundingClientRect();
                          // субпиксельная точность — как у текстов внутри блоков
                          const textFrame={width:round2(tr.width),height:round2(tr.height),
                            x:round2(tr.left-rr.left),y:round2(tr.top-rr.top)};
                          if(!rootAuto){ textFrame.absolute=true; }
                          const tstyle=cleanTextStyle(styleOf(rcs,warnings));
                          const talign={start:'left',end:'right',left:'left',center:'center',right:'right',justify:'justify'}[tstyle.textAlign]||null;
                          delete tstyle.textAlign;
                          const tnode={type:'text',text:text.slice(0,1000),sourceKey:'root::text'+idx,align:talign,style:tstyle,frame:textFrame};
                          rootChildren.push(tnode);
                          emitted++; pushRootRect(tr,tnode.sourceKey);
                        }
                      }
                      else if(child.nodeType===Node.ELEMENT_NODE){
                        const ccr=child.getBoundingClientRect(), ccs=getComputedStyle(child);
                        if(!visible(child,ccr,ccs)) return;
                        const node=compile(child,rr,rootAuto,root);
                        if(node) rootChildren.push(node);
                      }
                    });
                    if(rootBgLayers.length){
                      const rw=Math.max(1,Math.round(rr.width)), rh=Math.max(1,Math.round(rr.height));
                      const fit=rcs.backgroundSize==='cover'?'cover':rcs.backgroundSize==='contain'?'contain':'fill';
                      const rootBgFor=(bg,i)=>{
                        const lkey=rootBgLayers.length>1 ? 'root::bg'+i : 'root::bg';
                        if(bg.kind==='url'){
                          const layer={type:'image',src:bg.url,alt:'',sourceKey:lkey,
                             sourceMeta:{kind:'background-image',url:bg.url,layer:i},
                             style:{objectFit:fit},frame:{absolute:true,x:0,y:0,width:rw,height:rh}};
                          recordAsset(layer,'background','',rw,rh);
                          return layer;
                        }
                        return {type:'rect',fill:'#00000000',radius:Math.min(1000,Math.max(0,num(rcs.borderTopLeftRadius))),
                             sourceKey:lkey,sourceMeta:{kind:'background-image',reason:'gradient',layer:i},
                             style:{backgroundImage:bg.css},frame:{absolute:true,x:0,y:0,width:rw,height:rh}};
                      };
                      // unshift в CSS-порядке: нижний (последний в CSS) слой
                      // оказывается первым в rootChildren = дно paint-стека.
                      for(let i=0;i<rootBgLayers.length;i++){
                        const layer=rootBgFor(rootBgLayers[i],i);
                        rootChildren.unshift(layer);
                        emitted++; pushRootRect(rr,layer.sourceKey);
                      }
                    }
                    const rootArea=Math.max(1,Math.round(rr.width)*Math.round(rr.height));
                    const paintArea=unionArea(paintRects);
                    const rawPaintCoverage=Math.max(0,Math.min(100,Math.round(100*paintArea/rootArea)));
                    // Любой потерянный визуальный канал (visual drop или extras
                    // visual:true: pseudo/background-image/iframe/...) запрещает 100%:
                    // coverage описывает только реально представленный в IR paint,
                    // а не union DOM bbox. UI никогда не покажет 100 при потерях.
                    const hasVisualLoss=dropped.some(d=>d.visual) || extras.some(e=>e.visual);
                    const paintCoverage=hasVisualLoss ? Math.min(rawPaintCoverage,99) : rawPaintCoverage;
                    const coverage=paintCoverage;
                    const componentBoundaries=(()=>{
                      let count=0; const visit=(node)=>{
                        if(node?.sourceMeta?.componentBoundary) count++;
                        (node?.children||[]).forEach(visit);
                      };
                      rootChildren.forEach(visit); return count;
                    })();
                    return {selector:block.selector,sourceKey:'root',
                      root:{width:Math.round(rr.width),height:Math.round(rr.height),style:styleOf(rcs,warnings)},
                      nodes:rootChildren,layout:rootLayout.layout,direction:rootLayout.direction,
                      gap:Math.round(rootLayout.explicit?(rootLayout.direction==='row'?num(rcs.columnGap):num(rcs.rowGap)):(rootLayout.measuredGap||0)),
                      padding:paddingOf(rcs),justify:safeEnum(justify(rcs.justifyContent),['start','center','end','space-between','space-around'],'start'),
                      align:rootAlign,visited,emitted,dropped,extras,rasterRequests,assetRequests,paintRects,leafBoxes,paintCoverage,coverage,componentBoundaries,
                      warnings:[...warnings],fontFaces:collectFontFaces()};
                  };
                  return blocks.map(compileBlock);
                }
