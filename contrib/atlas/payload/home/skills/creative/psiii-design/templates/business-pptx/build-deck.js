/* ════════════════════════════════════════════════════════════════════════
 *  build-deck.js — ПУТЬ 1: один спец → и .pptx, и HTML-превью, идентичные.
 *
 *  buildBrandDeck({ JSZip, templateBytes, slides }) возвращает { pptx, html }:
 *    • pptx  — фирменный файл (buildBrandPptx, сборка прямо в мастере);
 *    • html  — HTML-превью, отрисованное ИЗ ТОГО ЖЕ .pptx: для каждого слайда
 *              берём его макет (фон + декор + геометрию плейсхолдеров) и наполняем
 *              текстом плейсхолдеров слайда. Превью = файл по построению — расхождение
 *              исключено (нет второго рендера, нет gen_pptx).
 *
 *  Один источник — массив `slides` (тот же, что у buildBrandPptx; типы и поля — в
 *  шапке build-pptx.js). Создание превью и выгрузка экспорта берутся из одного спека.
 *
 *  Использование (внутри run_script; СНАЧАЛА finalize-pptx.js и build-pptx.js):
 *    eval(await readFile('<ds>/templates/business-pptx/finalize-pptx.js'));
 *    eval(await readFile('<ds>/templates/business-pptx/build-pptx.js'));
 *    eval(await readFile('<ds>/templates/business-pptx/build-deck.js'));
 *    const { pptx, html } = await buildBrandDeck({
 *      JSZip,
 *      templateBytes: await readFileBinary('<ds>/templates/business-pptx/source.pptx'),
 *      slides: [ { type:'title', title:'…', name:'…', role:'…' }, … ],
 *      assetsBase: '../..',           // путь к корню ДС от места, где сохранишь превью
 *                                     //   (в потребителе — '_ds/<папка>' или '../_ds/<папка>')
 *    });
 *    await saveFile('export/deck.pptx', pptx);   // выгрузка
 *    await saveFile('decks/preview.html', html); // превью (то же самое визуально)
 *    // гейты: assertBrandPptx(pptx) и assertDesignDiscipline(pptx) — см. finalize-pptx.js
 * ════════════════════════════════════════════════════════════════════════ */

async function buildBrandDeck({ JSZip, templateBytes, slides, assetsBase = '../..', title = 'Презентация ПСиИИ' }) {
  if (typeof buildBrandPptx !== 'function')
    throw new Error('buildBrandDeck: сначала загрузи build-pptx.js (нужен buildBrandPptx).');
  const pptx = await buildBrandPptx({ JSZip, templateBytes, slides });
  const bytes = new Uint8Array(await pptx.arrayBuffer());
  const html = await renderDeckHtmlFromPptx({ JSZip, bytes, assetsBase, title });
  return { pptx, html };
}

async function renderDeckHtmlFromPptx({ JSZip, bytes, assetsBase = '../..', title = 'Презентация ПСиИИ' }) {
  const CX = 24382800;
  const PX = e => Math.round(+e / CX * 1920 * 10) / 10;          // EMU → px (канвас 1920)
  const zip = await JSZip.loadAsync(bytes);
  const get = async n => (zip.file(n) ? zip.file(n).async('string') : '');
  const esc = t => String(t == null ? '' : t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  // ── тема ──
  const theme = await get('ppt/theme/theme1.xml');
  const themeClr = {};
  for (const m of theme.matchAll(/<a:(dk1|lt1|dk2|lt2|accent1|accent2|accent3|accent4|accent5|accent6)>[\s\S]*?(?:srgbClr val="([0-9A-Fa-f]{6})"|sysClr val="[^"]+" lastClr="([0-9A-Fa-f]{6})")/g))
    themeClr[m[1]] = '#' + (m[2] || m[3]);
  const mstyle = {};
  const master = await get('ppt/slideMasters/slideMaster1.xml');
  for (const tag of ['titleStyle', 'bodyStyle', 'otherStyle']) {
    const mm = master.match(new RegExp('<p:' + tag + '>([\\s\\S]*?)</p:' + tag + '>'));
    if (!mm) continue;
    const lvl = mm[1].match(/<a:lvl1pPr[^>]*>([\s\S]*?)<\/a:lvl1pPr>/); const src = lvl ? lvl[1] : mm[1];
    const dr = src.match(/<a:defRPr([^>]*)>([\s\S]*?)<\/a:defRPr>/) || src.match(/<a:defRPr([^>]*)\/>/);
    const a = dr ? dr[1] : '', inner = dr && dr[2] ? dr[2] : '';
    mstyle[tag] = { sz: (a.match(/sz="(\d+)"/) || [])[1],
      latin: (inner.match(/typeface="([^"]+)"/) || [])[1],
      color: (inner.match(/schemeClr val="([^"]+)"/) || inner.match(/srgbClr val="([^"]+)"/) || [])[1] };
  }

  // ── порядок слайдов ──
  const pres = await get('ppt/presentation.xml');
  const prelsX = await get('ppt/_rels/presentation.xml.rels');
  const relT = {};
  for (const m of prelsX.matchAll(/<Relationship Id="([^"]+)"[^>]*Target="([^"]+)"/g)) relT[m[1]] = m[2];
  const order = [...pres.matchAll(/<p:sldId [^>]*r:id="([^"]+)"/g)]
    .map(m => ('ppt/' + relT[m[1]].replace(/^\/?ppt\//, '')).replace(/^ppt\/ppt\//, 'ppt/'));

  const fontFamily = latin => {
    const f = latin || '';
    if (/\+mj|Display/.test(f)) return "'YS Display Cond', sans-serif";
    return "'YS Text', sans-serif";
  };
  const fontWeight = latin => {
    const f = latin || '';
    if (/\+mj|Display/.test(f)) return 900;
    if (/Medium/.test(f)) return 500;
    if (/Bold/.test(f)) return 700;
    return 400;
  };
  const ALGN = { l: 'left', ctr: 'center', r: 'right', just: 'justify' };
  const ANCHOR = { t: 'flex-start', ctr: 'center', b: 'flex-end' };

  const sections = [];
  let slideNo = 0;
  for (const slidePath of order) {
    slideNo++;
    const sx = await get(slidePath);
    const srels = await get(slidePath.replace(/slides\/(slide\d+)\.xml$/, 'slides/_rels/$1.xml.rels'));
    // clrMapOvr слайда
    const mo = sx.match(/<a:overrideClrMapping([^>]*)\/>/);
    const map = { bg1: 'lt1', tx1: 'dk1', bg2: 'lt2', tx2: 'dk2', accent1: 'accent1', accent2: 'accent2', accent3: 'accent3', accent4: 'accent4', accent5: 'accent5', accent6: 'accent6' };
    if (mo) for (const k of Object.keys(map)) { const v = (mo[1].match(new RegExp(k + '="([^"]+)"')) || [])[1]; if (v) map[k] = v; }
    const resolveColor = v => {
      if (!v) return null;
      if (/^[0-9A-Fa-f]{6}$/.test(v)) return '#' + v;
      return themeClr[map[v] || v] || themeClr[v] || null;
    };
    // макет слайда
    const layRel = (srels.match(/Target="([^"]*slideLayouts\/slideLayout\d+\.xml)"/) || [])[1] || '';
    const layPath = ('ppt/' + layRel.replace(/^\.\.\//, '').replace(/^\/?ppt\//, '')).replace(/^ppt\/ppt\//, 'ppt/');
    const lx = await get(layPath);
    const lrelsPath = layPath.replace(/slideLayouts\/(slideLayout\d+)\.xml$/, 'slideLayouts/_rels/$1.xml.rels');
    const lrels = await get(lrelsPath);

    // фон макета
    const lbg = (lx.match(/<p:bg>[\s\S]*?<\/p:bg>/) || [''])[0];
    let bgColor = '#FFFFFF';
    const bgScheme = (lbg.match(/<a:solidFill><a:schemeClr val="([^"]+)"/) || lbg.match(/<a:solidFill><a:srgbClr val="([^"]+)"/) || [])[1];
    if (bgScheme) bgColor = resolveColor(bgScheme) || '#FFFFFF';

    const parts = [];

    // ── декор макета: фигуры без <p:ph> + картинки + соединители ──
    for (const sp of lx.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)) {
      const b = sp[0];
      if (/<p:ph\b/.test(b)) continue;                       // плейсхолдер — рисуем из слайда
      const off = b.match(/<a:off x="(-?\d+)" y="(-?\d+)"\/>/), ext = b.match(/<a:ext cx="(\d+)" cy="(\d+)"\/>/);
      if (!off || !ext) continue;
      const x = PX(off[1]), y = PX(off[2]), w = PX(ext[1]), h = PX(ext[2]);
      const prst = (b.match(/prst="([^"]+)"/) || [])[1] || 'rect';
      const fillS = (b.match(/<a:solidFill><a:(srgbClr|schemeClr) val="([^"]+)"/) || []);
      const noFill = /<a:noFill\/>/.test((b.match(/<p:spPr>[\s\S]*?<\/a:prstGeom>/) || [''])[0]);
      let fill = fillS[2] ? resolveColor(fillS[2]) : (noFill ? 'transparent' : 'transparent');
      let radius = 0;
      if (prst === 'roundRect') { const adj = +((b.match(/<a:gd name="adj" fmla="val (\d+)"/) || [])[1] || 16667) / 100000; radius = adj * Math.min(w, h); }
      const ln = b.match(/<a:ln w="(\d+)"[^>]*>[\s\S]*?<a:(srgbClr|schemeClr) val="([^"]+)"/);
      const border = ln ? `border:${Math.max(1, PX(ln[1]))}px solid ${resolveColor(ln[3])};` : '';
      const txt = [...b.matchAll(/<a:t>([^<]*)<\/a:t>/g)].map(t => t[1]).join(' ');
      parts.push(`<div style="position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;background:${fill};border-radius:${Math.round(radius)}px;${border}"></div>`);
      if (txt.trim()) parts.push(`<div style="position:absolute;left:${x}px;top:${y}px;width:${w}px;height:${h}px;display:flex;align-items:center;justify-content:center;font-family:'YS Text';font-size:24px;color:#494949;">${esc(txt)}</div>`);
    }
    // картинки макета (логотип и т.п.) — предпочитаем SVG-дублёр, EMF/WMF пропускаем
    for (const pic of lx.matchAll(/<p:pic>[\s\S]*?<\/p:pic>/g)) {
      const b = pic[0];
      const off = b.match(/<a:off x="(-?\d+)" y="(-?\d+)"\/>/), ext = b.match(/<a:ext cx="(\d+)" cy="(\d+)"\/>/);
      const svgEid = (b.match(/<asvg:svgBlip[^>]*r:embed="([^"]+)"/) || [])[1];
      const eid = svgEid || (b.match(/<a:blip[^>]*r:embed="([^"]+)"/) || [])[1];
      if (!off || !ext || !eid) continue;
      const tgt = (lrels.match(new RegExp('Id="' + eid + '"[^>]*Target="([^"]+)"')) || [])[1];
      if (!tgt) continue;
      const mediaPath = ('ppt/' + tgt.replace(/^\.\.\//, '').replace(/^\/?ppt\//, '')).replace(/^ppt\/ppt\//, 'ppt/');
      const ext2 = (mediaPath.split('.').pop() || 'png').toLowerCase();
      if (ext2 === 'emf' || ext2 === 'wmf') continue;          // браузер не рисует — пропускаем (есть SVG-дублёр)
      const f = zip.file(mediaPath); if (!f) continue;
      const mime = ext2 === 'svg' ? 'image/svg+xml' : ext2 === 'jpg' ? 'image/jpeg' : 'image/' + ext2;
      const u8 = await f.async('uint8array');
      let bin = ''; for (let i = 0; i < u8.length; i++) bin += String.fromCharCode(u8[i]);
      const dataUri = `data:${mime};base64,${btoa(bin)}`;
      parts.push(`<img src="${dataUri}" alt="" style="position:absolute;left:${PX(off[1])}px;top:${PX(off[2])}px;width:${PX(ext[1])}px;height:${PX(ext[2])}px;object-fit:contain;">`);
    }

    // ── геометрия+стиль плейсхолдеров из макета ──
    const phStyle = {};
    for (const sp of lx.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)) {
      const b = sp[0]; const ph = b.match(/<p:ph([^>]*?)\/?>/); if (!ph) continue;
      const t = (ph[1].match(/type="([^"]+)"/) || [])[1] || 'body';
      const idx = (ph[1].match(/idx="(\d+)"/) || [])[1] || '';
      const off = b.match(/<a:off x="(-?\d+)" y="(-?\d+)"\/>/), ext = b.match(/<a:ext cx="(\d+)" cy="(\d+)"\/>/);
      if (!off || !ext) continue;
      const dr = b.match(/<a:defRPr([^>]*)>([\s\S]*?)<\/a:defRPr>/) || b.match(/<a:defRPr([^>]*)\/>/);
      const da = dr ? dr[1] : '', inner = dr && dr[2] ? dr[2] : '';
      const bodyPr = (b.match(/<a:bodyPr[^>]*\/?>/) || [''])[0];
      const ms = mstyle[t === 'title' || t === 'ctrTitle' ? 'titleStyle' : 'bodyStyle'] || {};
      const latin = (inner.match(/<a:latin typeface="([^"]+)"/) || [])[1] || ms.latin;
      const colRaw = (inner.match(/schemeClr val="([^"]+)"/) || inner.match(/srgbClr val="([^"]+)"/) || [])[1] || ms.color;
      const csTypeface = (b.match(/<a:cs typeface="([^"]+)"/) || [])[1] || '';
      const isMedium = /Medium/.test(latin || '') || /Medium/.test(csTypeface);
      phStyle[t + (idx ? ':' + idx : '')] = {
        x: PX(off[1]), y: PX(off[2]), w: PX(ext[1]), h: PX(ext[2]),
        sz: +((da.match(/sz="(\d+)"/) || [])[1] || ms.sz || 2800) / 100,
        family: fontFamily(latin), weight: /\+mj|Display/.test(latin || '') ? 900 : (isMedium ? 500 : fontWeight(latin)),
        color: resolveColor(colRaw) || '#1F1F20',
        algn: ALGN[(bodyPr.match(/anchorCtr="1"/) ? 'ctr' : null) || (b.match(/<a:lvl1pPr[^>]*algn="([^"]+)"/) || [])[1] || 'l'] || 'left',
        anchor: ANCHOR[(bodyPr.match(/anchor="([^"]+)"/) || [])[1] || 't'] || 'flex-start',
        display: /\+mj|Display/.test(latin || ''),
      };
    }

    // ── текст плейсхолдеров из слайда ──
    for (const sp of sx.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)) {
      const b = sp[0]; const ph = b.match(/<p:ph([^>]*?)\/?>/); if (!ph) continue;
      const t = (ph[1].match(/type="([^"]+)"/) || [])[1] || 'body';
      const idx = (ph[1].match(/idx="(\d+)"/) || [])[1] || '';
      const key = t + (idx ? ':' + idx : '');
      const st = phStyle[key]; if (!st) continue;
      // номер страницы (slidenum) — реальное число
      let lines;
      if (/<a:fld[^>]*type="slidenum"/.test(b)) lines = [String(slideNo)];
      else lines = [...b.matchAll(/<a:p>([\s\S]*?)<\/a:p>/g)].map(p => [...p[1].matchAll(/<a:t>([^<]*)<\/a:t>/g)].map(x => x[1]).join(''));
      if (!lines.length) lines = [''];
      const lh = st.display ? 0.9 : 1.12;
      const body = lines.map(l => `<div>${esc(l) || '&nbsp;'}</div>`).join('');
      parts.push(`<div data-ph="${key}" style="position:absolute;left:${st.x}px;top:${st.y}px;width:${st.w}px;height:${st.h}px;display:flex;flex-direction:column;justify-content:${st.anchor};font-family:${st.family};font-weight:${st.weight};font-size:${st.sz}px;line-height:${lh};color:${st.color};text-align:${st.algn};letter-spacing:${st.display ? '-0.01em' : '0'};">${body}</div>`);
    }

    sections.push(
      `<section data-screen-label="${String(slideNo).padStart(2, '0')}" style="position:relative;width:1920px;height:1080px;overflow:hidden;background:${bgColor};font-family:'YS Text',sans-serif;">${parts.join('')}</section>`);
  }

  return wrapDeckHtml(sections, assetsBase, title);
}

function wrapDeckHtml(sections, assetsBase, title) {
  return `<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"><title>${title}</title>
<link rel="stylesheet" href="${assetsBase}/tokens/fonts.css">
<style>
  html,body{margin:0;background:#111;}
  *{box-sizing:border-box;}
  #stage{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;}
  #slide-wrap{position:relative;}
  #slide-wrap > section{display:none;}
  #slide-wrap > section.active{display:block;}
  .nav{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);display:flex;gap:14px;align-items:center;z-index:10;
       font-family:'YS Text',sans-serif;color:#fff;background:rgba(0,0,0,0.55);border-radius:999px;padding:8px 16px;}
  .nav button{font:inherit;color:#fff;background:none;border:1px solid rgba(255,255,255,0.4);border-radius:999px;width:34px;height:34px;cursor:pointer;}
  .nav span{min-width:64px;text-align:center;font-size:15px;}
</style></head>
<body>
<div id="stage"><div id="slide-wrap">
${sections.join('\n')}
</div></div>
<div class="nav"><button id="prev">‹</button><span id="ind"></span><button id="next">›</button></div>
<script>
(function(){
  var W=1920,H=1080,wrap=document.getElementById('slide-wrap');
  var slides=[].slice.call(wrap.children),i=0;
  function fit(){var s=Math.min(innerWidth/W,innerHeight/H);wrap.style.width=W+'px';wrap.style.height=H+'px';wrap.style.transform='scale('+s+')';wrap.style.transformOrigin='center center';}
  function show(n){i=Math.max(0,Math.min(slides.length-1,n));slides.forEach(function(s,k){s.classList.toggle('active',k===i);});document.getElementById('ind').textContent=(i+1)+' / '+slides.length;location.hash=String(i+1);}
  addEventListener('resize',fit);
  document.getElementById('prev').onclick=function(){show(i-1);};
  document.getElementById('next').onclick=function(){show(i+1);};
  addEventListener('keydown',function(e){if(e.key==='ArrowRight'||e.key==='PageDown')show(i+1);if(e.key==='ArrowLeft'||e.key==='PageUp')show(i-1);});
  fit();show(Math.max(0,(parseInt(location.hash.slice(1),10)||1)-1));
})();
</script>
</body></html>`;
}

if (typeof window !== 'undefined') { window.buildBrandDeck = buildBrandDeck; window.renderDeckHtmlFromPptx = renderDeckHtmlFromPptx; }
if (typeof module !== 'undefined') module.exports = { buildBrandDeck, renderDeckHtmlFromPptx };
