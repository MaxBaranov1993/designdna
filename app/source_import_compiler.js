(blocks) => {
                  const num = (v) => Number.parseFloat(v) || 0;
                  const round2 = (v) => Math.round(Number(v || 0) * 100) / 100;
                  const hex = (v) => {
                    const value=String(v||'');
                    const rgb=value.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?/);
                    if(rgb){
                      const alpha=rgb[4]===undefined ? 1 : Math.max(0,Math.min(1,Number(rgb[4])));
                      if(alpha<=.05) return null;
                      const color='#'+rgb.slice(1,4).map(x=>(+x).toString(16).padStart(2,'0')).join('');
                      return alpha<1 ? color+Math.round(alpha*255).toString(16).padStart(2,'0') : color;
                    }
                    const srgb=value.match(/color\(srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+))?\)/);
                    if(!srgb) return null;
                    const alpha=srgb[4]===undefined ? 1 : Math.max(0,Math.min(1,Number(srgb[4])));
                    if(alpha<=.05) return null;
                    const color='#'+srgb.slice(1,4).map(x=>Math.round(Math.max(0,Math.min(1,Number(x)))*255).toString(16).padStart(2,'0')).join('');
                    return alpha<1 ? color+Math.round(alpha*255).toString(16).padStart(2,'0') : color;
                  };
                  const visible = (el,r,cs) => r.width>=1 && r.height>=1 && cs.display!=='none' &&
                    cs.visibility!=='hidden' && Number(cs.opacity)!==0;
                  const safeEnum = (v, allowed, fallback) => allowed.includes(v) ? v : fallback;
                  const styleOf = (cs, warnings) => {
                    if (cs.backgroundImage && cs.backgroundImage !== 'none') warnings.add('complex background');
                    const deco=(cs.textDecorationLine||'none').split(' ')[0];
                    const style={
                      color:hex(cs.color), background:hex(cs.backgroundColor),
                      fontFamily:String(cs.fontFamily||'').replace(/["']/g,'').slice(0,160),
                      fontSize:Math.min(512,Math.max(1,num(cs.fontSize))),
                      fontWeight:Math.min(900,Math.max(100,Number.parseInt(cs.fontWeight,10)||400)),
                      lineHeight:(()=>{const lh=num(cs.lineHeight);return lh>0?Math.min(10,Math.max(.5,lh/Math.max(1,num(cs.fontSize)))):1.2})(),
                      letterSpacing:Math.max(-20,Math.min(100,num(cs.letterSpacing))),
                      borderColor:hex(cs.borderTopColor) || (num(cs.borderTopWidth)>0 ? '#e0e0e0' : null),
                      borderWidth:Math.min(64,Math.max(0,num(cs.borderTopWidth))),
                      borderRadius:Math.min(1000,Math.max(0,num(cs.borderTopLeftRadius))),
                      boxShadow:cs.boxShadow && cs.boxShadow!=='none' ? cs.boxShadow.slice(0,300) : null,
                      textDecoration:safeEnum(deco,['none','underline','line-through','overline'],'none'),
                      whiteSpace:safeEnum(cs.whiteSpace,['normal','nowrap','pre','pre-wrap','pre-line','break-spaces'],'normal'),
                      overflow:safeEnum(cs.overflow,['visible','hidden','clip','scroll','auto'],'visible'),
                      textTransform:safeEnum(cs.textTransform,['none','uppercase','lowercase','capitalize'],'none'),
                      opacity:Math.min(1,Math.max(0,num(cs.opacity))),
                      objectFit:safeEnum(cs.objectFit,['contain','cover','fill','none','scale-down'],'fill')
                    };
                    // masks/clipping — честные визуальные каналы: gradient-mask и
                    // clip-path сериализуем в style (renderer применяет обратно);
                    // url()-mask уходит в raster fallback на уровне compile()
                    // (editable:false слой + element-screenshot), здесь — warning.
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
                      if(values.every(Number.isFinite) && Math.abs(values[0]-1)<1e-6 && Math.abs(values[1])<1e-6 &&
                        Math.abs(values[2])<1e-6 && Math.abs(values[3]-1)<1e-6) return 'translate';
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
                    const paintRects=[];
                    const leafBoxes=[];
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
                    const componentMetaOf=(el)=>{
                      const tag=String(el.tagName||'').toLowerCase();
                      const ariaRole=String(el.getAttribute?.('role')||'').toLowerCase();
                      const semanticTags=new Set(['nav','form','header','footer','main','section','article','aside']);
                      const semanticRoles=new Set(['navigation','status','toolbar','region','complementary','form']);
                      const identity=[String(el.id||''),...Array.from(el.classList||[])].join(' ');
                      const named=/(^|[\s_-])(card|panel|widget|module|item|tile|rail|nav|menu|action|status|profile)([\s_-]|$)/i.test(identity);
                      const classes=Array.from(el.classList||[])
                        .map(value=>String(value)).filter(value=>/^[a-z][a-z0-9_-]{1,63}$/i.test(value)).slice(0,2);
                      const signature=tag+(classes.length?'.'+classes.join('.'):'');
                      const parent=el.parentElement;
                      const repeatCandidate=!!parent && (['li','button','a','article'].includes(tag)||named);
                      const siblings=repeatCandidate ? Array.from(parent.children).filter(candidate=>{
                        const candidateClasses=Array.from(candidate.classList||[])
                          .map(value=>String(value)).filter(value=>/^[a-z][a-z0-9_-]{1,63}$/i.test(value)).slice(0,2);
                        return String(candidate.tagName||'').toLowerCase()+(candidateClasses.length?'.'+candidateClasses.join('.'):'')===signature;
                      }) : [];
                      const repeatedBoundary=siblings.length>=2;
                      const hasInput=!!el.querySelector?.('input,select,textarea');
                      const hasAction=!!el.querySelector?.('button,[role="button"],input[type="submit"]');
                      const childAlreadyGroupsForm=[...el.children].some(child=>
                        !!child.querySelector?.('input,select,textarea') &&
                        !!child.querySelector?.('button,[role="button"],input[type="submit"]'));
                      const syntheticForm=tag!=='form' && hasInput && hasAction && !childAlreadyGroupsForm;
                      if(!semanticTags.has(tag) && !semanticRoles.has(ariaRole) && !named && !repeatedBoundary && !syntheticForm) return null;
                      const componentRole=syntheticForm?'form':(ariaRole||tag||'component');
                      const rawLabel=String(el.getAttribute?.('aria-label')||el.getAttribute?.('data-component')||el.id||classes[0]||componentRole);
                      const meta={kind:'dom',componentBoundary:true,
                        componentRole:componentRole.slice(0,100),componentLabel:rawLabel.slice(0,100)};
                      if(repeatedBoundary){
                        meta.repeatGroup=(pathOf(parent,root)+'>'+signature).slice(0,500);
                        meta.repeatIndex=siblings.indexOf(el);
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
                      const complexTransform=transformKind(cs.transform)==='complex';
                      // open shadow root: shadow-дерево доступно, но обход пока
                      // небезопасен (slots/изоляция стилей) — тот же raster fallback,
                      // видимое содержимое не исчезает молча.
                      const openShadow=!!el.shadowRoot &&
                        (el.shadowRoot.children.length>0 || String(el.shadowRoot.textContent||'').trim().length>0);
                      if(['CANVAS','VIDEO','IFRAME'].includes(tag) || closedShadowSuspect || openShadow || hasUrlMask || complexTransform){
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
                        const hasTextContent=!!(textMatch && textMatch[2].trim());
                        const hasUnserializableContent=!!content && content!=='none' && content!=='normal' && !textMatch;
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
                            if(bg.kind==='url') out.push({type:'image',src:bg.url,alt:'',sourceKey:lkey,
                              sourceMeta:{kind,url:bg.url,layer:i},style:{objectFit:fit},frame});
                            else out.push({type:'rect',fill:'#00000000',radius:Math.min(1000,Math.max(0,num(pcs.borderTopLeftRadius))),
                              sourceKey:lkey,sourceMeta:{kind,reason:'gradient',layer:i},style:{backgroundImage:bg.css},frame});
                          }
                          return out;
                        }
                        if(hasTextContent){
                          return [{type:'text',text:textMatch[2].slice(0,1000),sourceKey:skey,
                            sourceMeta:{kind},style:cleanTextStyle(styleOf(pcs,warnings)),frame}];
                        }
                        if(hasContent && !textMatch){
                          // counters/attr()/url() в content сериализовать не можем —
                          // журналируем как честно потерянный визуальный канал.
                          recordExtra(skey,'pseudo-content',r,true);
                        }
                        if(bgColor) return [{type:'rect',fill:bgColor,radius:Math.min(1000,Math.max(0,num(pcs.borderTopLeftRadius))),
                          sourceKey:skey,sourceMeta:{kind},style:{},frame}];
                        return [];
                      };
                      const bgLayers=parseBackground(cs.backgroundImage);
                      const beforeLayers=pseudoLayers('::before','pseudo-before');
                      const afterLayers=pseudoLayers('::after','pseudo-after');
                      const bgLayerFor=(bg,i)=>{
                        const fit=cs.backgroundSize==='cover'?'cover':cs.backgroundSize==='contain'?'contain':'fill';
                        const lkey=bgLayers.length>1 ? key+'::bg'+i : key+'::bg';
                        if(bg.kind==='url') return {type:'image',src:bg.url,alt:'',sourceKey:lkey,
                          sourceMeta:{kind:'background-image',url:bg.url,layer:i},
                          style:{objectFit:fit},frame:{absolute:true,x:0,y:0,width:elW,height:elH}};
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
                      const childBreaksTextMerging=visibleChildEls.some(c=>{
                        return [c,...c.querySelectorAll('*')].some(candidate=>{
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
                        const typographyDiff=ccs.fontFamily!==cs.fontFamily || ccs.fontSize!==cs.fontSize ||
                          ccs.fontWeight!==cs.fontWeight || ccs.color!==cs.color ||
                          ccs.letterSpacing!==cs.letterSpacing || ccs.textTransform!==cs.textTransform;
                        return ownPaint || pseudoPaint || typographyDiff;
                        });
                      });
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
                      [...el.childNodes].forEach((child,idx)=>{
                        if(child.nodeType===Node.TEXT_NODE){
                          const text=(child.textContent||'').replace(/\s+/g,' ').trim();
                          if(!text || !isContainer) return;
                          const range=document.createRange(); range.selectNodeContents(child); const tr=range.getBoundingClientRect();
                          if(tr.width<1||tr.height<1) return;
                          const textFrame={width:Math.ceil(tr.width)+2,height:Math.round(tr.height),
                            x:Math.round(tr.left-r.left),y:Math.round(tr.top-r.top)};
                          if(!childParentAuto){ textFrame.absolute=true; }
                          const tnode={type:'text',text:text.slice(0,1000),sourceKey:key+'::text'+idx,
                            style:cleanTextStyle(styleOf(cs,warnings)),frame:textFrame};
                          rawChildren.push(tnode);
                          emitted++; pushRootRect({left:r.left+textFrame.x,top:r.top+textFrame.y,width:textFrame.width,height:textFrame.height},tnode.sourceKey);
                        } else if(child.nodeType===Node.ELEMENT_NODE){
                          const ccr=child.getBoundingClientRect(), ccs=getComputedStyle(child);
                          if(!visible(child,ccr,ccs)) return;
                          if(!isContainer){
                            recordDropped(pathOf(child,rootEl),'non-container-child',true);
                            return;
                          }
                          const compiled=compile(child,r,childParentAuto,rootEl);
                          if(compiled) rawChildren.push(compiled);
                        }
                      });
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
                          emitted++; pushRootRect({left:r.left+(implicit.frame.x||0),top:r.top+(implicit.frame.y||0),width:implicit.frame.width,height:implicit.frame.height},implicit.sourceKey);
                        }
                      }
                      const node={type,sourceKey:key,style,frame:frameFor(r,parentRect,cs,parentAuto,isContainer,layout)};
                      const componentMeta=componentMetaOf(el);
                      if(componentMeta) node.sourceMeta=componentMeta;
                      if(type==='heading'){ node.level=Number(tag.slice(1)); node.text=directText.slice(0,1000); }
                      if(type==='text') node.text=directText.slice(0,1000);
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
                        if(tag==='IMG') node.src=el.currentSrc||el.src||'';
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
                      } else if(bgLayers.length || beforeLayers.length || afterLayers.length){
                        // неконтейнерный тип (image/heading) не может нести детей —
                        // синтетический канал теряется, журналируем честно
                        if(bgLayers.length) recordExtra(key,'background-image',r,true);
                        beforeLayers.forEach(l=>recordExtra(l.sourceKey,'pseudo',r,true));
                        afterLayers.forEach(l=>recordExtra(l.sourceKey,'pseudo',r,true));
                      }
                      if(isContainer && allChildren.length) node.children=allChildren;
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
                        only.frame=Object.assign({}, of, {
                          absolute:true,
                          x:Math.round(r.left-parentRect.left+(Number(of.x)||0)),
                          y:Math.round(r.top-parentRect.top+(Number(of.y)||0))
                        });
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
                          const textFrame={width:Math.ceil(tr.width)+2,height:Math.round(tr.height),
                            x:Math.round(tr.left-rr.left),y:Math.round(tr.top-rr.top)};
                          if(!rootAuto){ textFrame.absolute=true; }
                          const tnode={type:'text',text:text.slice(0,1000),sourceKey:'root::text'+idx,style:cleanTextStyle(styleOf(rcs,warnings)),frame:textFrame};
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
                        return bg.kind==='url'
                          ? {type:'image',src:bg.url,alt:'',sourceKey:lkey,
                             sourceMeta:{kind:'background-image',url:bg.url,layer:i},
                             style:{objectFit:fit},frame:{absolute:true,x:0,y:0,width:rw,height:rh}}
                          : {type:'rect',fill:'#00000000',radius:Math.min(1000,Math.max(0,num(rcs.borderTopLeftRadius))),
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
                      align:rootAlign,visited,emitted,dropped,extras,rasterRequests,paintRects,leafBoxes,paintCoverage,coverage,componentBoundaries,
                      warnings:[...warnings],fontFaces:collectFontFaces()};
                  };
                  return blocks.map(compileBlock);
                }
