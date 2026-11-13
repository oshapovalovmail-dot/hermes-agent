/**
 * build-pptx — ЖЕЛЕЗОБЕТОННЫЙ путь к фирменному PPTX.
 *
 * Собирает презентацию ПРЯМО в шаблоне `templates/business-pptx/source.pptx`:
 * текст ложится в готовые плейсхолдеры фирменных макетов (заголовок, подзаголовок,
 * примечание, номер). Здесь НЕТ `gen_pptx`, нет захвата HTML, нечего «финализировать
 * постфактом» — размер 67,73×38,1 см, тема F2F2F2/F66048, шрифты YS, 18 макетов и
 * 116 направляющих наследуются из шаблона, а фон/шрифт/кегль заголовка дают макеты.
 * Фирменность гарантирована ПО ПОСТРОЕНИЮ, а не проверкой постфактум. (Гейт всё
 * равно прогоняется в конце — если он когда-нибудь упадёт, это баг сборщика.)
 *
 * Использование (внутри run_script; СНАЧАЛА загрузи finalize-pptx.js — он даёт
 * assertBrandPptx для финального гейта):
 *   eval(await readFile('<ds>/templates/business-pptx/finalize-pptx.js'));
 *   eval(await readFile('<ds>/templates/business-pptx/build-pptx.js'));
 *   const out = await buildBrandPptx({
 *     JSZip,
 *     templateBytes: await readFileBinary('<ds>/templates/business-pptx/source.pptx'),
 *     slides: [
 *       { type:'title',   title:'Заголовок презентации', name:'Имя Фамилия', role:'Должность' },
 *       { type:'section', title:'Название раздела', kicker:'01' },
 *       { type:'content', title:'Заголовок слайда', subtitle:'Подзаголовок', note:'Примечание' },
 *       { type:'heading', title:'Просто крупный заголовок' },
 *       { type:'stat',    title:'86%', caption:'что это за цифра', sub:'доп. строка' },
 *       { type:'thesis',  title:'Короткий тезис на красном', note:'пояснение' },
 *       { type:'cards2',  title:'Два пункта', cards:[{n:'01',text:'Первый'},{n:'02',text:'Второй'}] },
 *       { type:'cards3',  title:'Три пункта', cards:[{n:'01',text:'A'},{n:'02',text:'B'},{n:'03',text:'C'}] },
 *       { type:'final',   title:'Спасибо', name:'Имя Фамилия', role:'Должность' },
 *       // запасной люк — задать плейсхолдеры вручную под любой из 18 макетов:
 *       { layout:'slideLayout7.xml', placeholders:[ {ph:'title', lines:['…']} ] },
 *     ],
 *   });
 *   await saveFile('export/deck.pptx', out);
 *
 * Типы слайдов (type → макет → какие поля):
 *   title   → slideLayout1  (КРАСНЫЙ):  title, name(body12), role(body13)
 *   section → slideLayout3  (КРАСНЫЙ):  title, kicker(body10), note(body13)
 *   thesis  → slideLayout11 (КРАСНЫЙ):  title, note(body10)
 *   content → slideLayout6  (белый):    title, subtitle(body11), note(body10), num
 *   heading → slideLayout5  (белый,72): title, note(body10), num
 *   heading96 → slideLayout4 (белый,96): title, note(body10), num
 *   stat    → slideLayout10 (белый):    title(крупная цифра), caption(body11), note(body10)
 *   cards2  → slideLayout14 (белый):    title, cards[2] {title(заголовок),text}, num
 *   cards3  → slideLayout13 (белый):    title, cards[3] {title,text}, num
 *   contents→ slideLayout2  (белый):    heading(body11) + items[] {n,text} (пары, до 7), num
 *   photo   → slideLayout17 (белый):    title, caption(body10), note(body13), image, num
 *   mockup  → slideLayout16 (белый):    title, caption(body10), note(body13), image, num
 *   final   → slideLayout18 (СЕРЫЙ):    title, name(body12), role(body13)
 *   blank   → slideLayout9  (белый, без title): note(body10), num
 * Номер страницы (num) — авто-поле slidenum; не задавай число вручную.
 * Картинка (photo/mockup): image:{ data, ext } — data это Uint8Array/Blob/ArrayBuffer
 *   (например `await readFileBinary('uploads/foto.jpg')`), ext — 'png'|'jpeg'|'webp'.
 *   Фото наследует позицию и скруглённую рамку из макета (пустой spPr). Картинку
 *   можно добавить и в любой свой слайд через сырой люк pics:[{idx,image}].
 * Любой слайд можно задать «сырьём» через { layout, placeholders:[{ph,idx?,lines?,field?}],
 *   pics?:[{idx, image:{data,ext}}] }.
 */
async function buildBrandPptx({ JSZip, templateBytes, slides }) {
  const CX = 24382800, CY = 13716000;
  const GUIDE_URI_PRES = '{EFAFB233-063F-42B5-8137-9DF3F51BA10A}';
  const SECTION_URI    = '{521415D9-36F7-43E2-AB2F-B90AF26B5E84}';
  if (!Array.isArray(slides) || !slides.length)
    throw new Error('buildBrandPptx: slides пуст — передай массив описаний слайдов.');

  const base = await JSZip.loadAsync(templateBytes);
  const esc = t => String(t == null ? '' : t)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

  // ── описание слайда (type) → { layout, placeholders[] } ──
  // placeholders: { ph:'title'|'body'|'sldNum', idx?, lines?:[], field?:true }
  const P = (ph, idx, lines, field) => ({ ph, idx, lines, field });
  const L = (a) => a.filter(Boolean);
  function resolveSpec(sp, n, total) {
    if (sp.layout && sp.placeholders) return sp; // сырой люк
    const t = sp.type || 'content';
    const lines = v => v == null ? null : (Array.isArray(v) ? v : [v]);
    switch (t) {
      case 'title': return { layout: 'slideLayout1.xml', placeholders: L([
        P('title', null, lines(sp.title)), sp.name && P('body', 12, lines(sp.name)),
        sp.role && P('body', 13, lines(sp.role)) ]) };
      case 'section': return { layout: 'slideLayout3.xml', placeholders: L([
        P('title', null, lines(sp.title)), sp.kicker && P('body', 10, lines(sp.kicker)),
        sp.note && P('body', 13, lines(sp.note)) ]) };
      case 'thesis': return { layout: 'slideLayout11.xml', placeholders: L([
        P('title', null, lines(sp.title)), sp.note && P('body', 10, lines(sp.note)) ]) };
      case 'content': return { layout: 'slideLayout6.xml', placeholders: L([
        P('title', null, lines(sp.title)), sp.subtitle && P('body', 11, lines(sp.subtitle)),
        sp.note && P('body', 10, lines(sp.note)), P('sldNum', 4, null, true) ]) };
      case 'heading': return { layout: 'slideLayout5.xml', placeholders: L([
        P('title', null, lines(sp.title)), sp.note && P('body', 10, lines(sp.note)),
        P('sldNum', 4, null, true) ]) };
      case 'heading96': return { layout: 'slideLayout4.xml', placeholders: L([
        P('title', null, lines(sp.title)), sp.note && P('body', 10, lines(sp.note)),
        P('sldNum', 4, null, true) ]) };
      case 'stat': case 'number': return { layout: 'slideLayout10.xml', placeholders: L([
        P('title', null, lines(sp.title)), sp.caption && P('body', 11, lines(sp.caption)),
        sp.note && P('body', 10, lines(sp.note)) ]) };
      case 'cards2': return { layout: 'slideLayout14.xml', placeholders: L([
        P('title', null, lines(sp.title)), P('sldNum', 4, null, true),
        ...cardPhs(sp.cards, [[11, 13], [14, 15]]) ]) };
      case 'cards3': return { layout: 'slideLayout13.xml', placeholders: L([
        P('title', null, lines(sp.title)), P('sldNum', 4, null, true),
        ...cardPhs(sp.cards, [[11, 13], [14, 15], [16, 17]]) ]) };
      case 'contents': {
        const pairs = [[12, 13], [14, 15], [16, 17], [18, 19], [20, 21], [22, 23], [24, 25]];
        const items = (sp.items || []).slice(0, 7);
        return { layout: 'slideLayout2.xml', placeholders: L([
          sp.heading && P('body', 11, lines(sp.heading)),
          ...items.flatMap((it, k) => {
            const [numIdx, txtIdx] = pairs[k];
            const num = (it && it.n != null) ? String(it.n) : String(k + 1).padStart(2, '0');
            const txt = (it && it.text != null) ? it.text : it;
            return [P('body', numIdx, [num]), P('body', txtIdx, Array.isArray(txt) ? txt : [txt])];
          }),
          P('sldNum', 4, null, true) ]) };
      }
      case 'photo': return { layout: 'slideLayout17.xml', placeholders: L([
        P('title', null, lines(sp.title)), sp.caption && P('body', 10, lines(sp.caption)),
        sp.note && P('body', 13, lines(sp.note)), P('sldNum', 4, null, true) ]),
        pics: sp.image ? [{ idx: 15, image: sp.image }] : [] };
      case 'mockup': return { layout: 'slideLayout16.xml', placeholders: L([
        P('title', null, lines(sp.title)), sp.caption && P('body', 10, lines(sp.caption)),
        sp.note && P('body', 13, lines(sp.note)), P('sldNum', 4, null, true) ]),
        pics: sp.image ? [{ idx: 22, image: sp.image }] : [] };
      case 'blank': return { layout: 'slideLayout9.xml', placeholders: L([
        sp.note && P('body', 10, lines(sp.note)), P('sldNum', 4, null, true) ]) };
      case 'final': return { layout: 'slideLayout18.xml', placeholders: L([
        P('title', null, lines(sp.title)), sp.name && P('body', 12, lines(sp.name)),
        sp.role && P('body', 13, lines(sp.role)) ]) };
      default: throw new Error('buildBrandPptx: неизвестный type «' + t + '» на слайде ' + n);
    }
  }
  // карточки: каждая занимает пару body-плейсхолдеров [заголовок, текст]
  function cardPhs(cards, pairs) {
    const out = [];
    (cards || []).slice(0, pairs.length).forEach((c, i) => {
      const [headIdx, textIdx] = pairs[i];
      const head = c.title != null ? c.title : c.n;
      if (head != null) out.push(P('body', headIdx, Array.isArray(head) ? head : [String(head)]));
      if (c.text != null) out.push(P('body', textIdx, Array.isArray(c.text) ? c.text : [c.text]));
    });
    return out;
  }

  // ── один плейсхолдер-sp (пустой spPr → позиция/формат из макета) ──
  function phSp(id, ph) {
    const phTag = `<p:ph type="${ph.ph}"${ph.idx != null ? ` idx="${ph.idx}"` : ''}/>`;
    let body;
    if (ph.field) {
      body = `<a:p><a:fld id="{C1B2A3D4-0000-4F00-9000-0000000000${(id % 100).toString().padStart(2, '0')}}" type="slidenum"><a:t>2</a:t></a:fld></a:p>`;
    } else {
      const ls = (ph.lines && ph.lines.length ? ph.lines : ['']);
      body = ls.map(t => `<a:p><a:r><a:t>${esc(t)}</a:t></a:r></a:p>`).join('');
    }
    return `<p:sp><p:nvSpPr><p:cNvPr id="${id}" name="PH ${ph.ph}${ph.idx != null ? ph.idx : ''}"/>` +
      `<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr>${phTag}</p:nvPr></p:nvSpPr>` +
      `<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>${body}</p:txBody></p:sp>`;
  }
  // ── картинка в pic-плейсхолдер (пустой spPr → позиция/скругление из макета) ──
  function picXml(id, idx, embedId) {
    return `<p:pic><p:nvPicPr><p:cNvPr id="${id}" name="Picture ${id}"/>` +
      `<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>` +
      `<p:nvPr><p:ph type="pic" idx="${idx}"/></p:nvPr></p:nvPicPr>` +
      `<p:blipFill><a:blip r:embed="${embedId}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>` +
      `<p:spPr/></p:pic>`;
  }
  async function coerceBytes(data) {
    if (data instanceof Uint8Array) return data;
    if (data && data.arrayBuffer) return new Uint8Array(await data.arrayBuffer()); // Blob
    if (data instanceof ArrayBuffer) return new Uint8Array(data);
    throw new Error('buildBrandPptx: image.data должен быть Uint8Array/Blob/ArrayBuffer.');
  }
  function slideXml(spec, n, extraXml) {
    const sps = spec.placeholders.map((ph, k) => phSp(2 + n * 50 + k, ph)).join('');
    return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
      '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" ' +
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" ' +
      'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">' +
      '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>' +
      '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>' +
      sps + (extraXml || '') + '</p:spTree></p:cSld><p:clrMapOvr><a:overrideClrMapping ' +
      'bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" accent3="accent3" ' +
      'accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/></p:clrMapOvr></p:sld>';
  }

  // 1. убрать слайды-примеры и заметки шаблона
  for (const nm of Object.keys(base.files)) {
    if (/ppt\/slides\/slide\d+\.xml$/.test(nm) ||
        /ppt\/slides\/_rels\/slide\d+\.xml\.rels$/.test(nm) ||
        /ppt\/notesSlides\//.test(nm)) base.remove(nm);
  }

  // 2. собрать слайды + их rels (ссылка на нужный макет)
  const relHdr = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">';
  const N = slides.length;
  const usedImgExt = new Set();
  for (let i = 1; i <= N; i++) {
    const spec = resolveSpec(slides[i - 1], i, N);
    const layExists = base.file('ppt/slideLayouts/' + spec.layout);
    if (!layExists) throw new Error('buildBrandPptx: макет ' + spec.layout + ' не найден в шаблоне (слайд ' + i + ').');
    // картинки: добавить медиа, построить rels, собрать <p:pic>
    let picsXml = '', imgRels = '', imgN = 0;
    for (const pic of (spec.pics || [])) {
      if (!pic.image) continue;
      const data = await coerceBytes(pic.image.data != null ? pic.image.data : pic.image);
      const ext = (pic.image.ext || 'png').toLowerCase().replace(/^jpg$/, 'jpeg');
      usedImgExt.add(ext);
      imgN++;
      const dst = `ppt/media/build${i}_${imgN}.${ext}`;
      base.file(dst, data);
      const embedId = `rIdImg${imgN}`;
      imgRels += `<Relationship Id="${embedId}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/build${i}_${imgN}.${ext}"/>`;
      picsXml += picXml(40 + i * 50 + imgN, pic.idx, embedId);
    }
    base.file('ppt/slides/slide' + i + '.xml', slideXml(spec, i, picsXml));
    base.file('ppt/slides/_rels/slide' + i + '.xml.rels', relHdr +
      `<Relationship Id="rIdL" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/${spec.layout}"/>` +
      imgRels + '</Relationships>');
  }

  // 3. presentation.xml.rels — пересобрать ссылки на слайды
  let prels = await base.file('ppt/_rels/presentation.xml.rels').async('string');
  prels = prels.replace(/<Relationship[^>]*Type="[^"]*\/slide"[^>]*\/>/g, '');
  let newSlideRels = '';
  for (let i = 1; i <= N; i++)
    newSlideRels += `<Relationship Id="rIdS${i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide${i}.xml"/>`;
  prels = prels.replace('</Relationships>', newSlideRels + '</Relationships>');
  base.file('ppt/_rels/presentation.xml.rels', prels);

  // 4. presentation.xml — sldIdLst, размер, направляющие (гарантируем оба инварианта)
  let pres = await base.file('ppt/presentation.xml').async('string');
  pres = pres.replace(/<p:sldIdLst>[\s\S]*?<\/p:sldIdLst>/,
    '<p:sldIdLst>' + Array.from({ length: N }, (_, k) =>
      `<p:sldId id="${9001 + k}" r:id="rIdS${k + 1}"/>`).join('') + '</p:sldIdLst>');
  pres = pres.replace(new RegExp('<p:ext uri="\\' + SECTION_URI.slice(0, -1) + '\\}">[\\s\\S]*?<\\/p:ext>'), '');
  // размер (в source.pptx строка может отличаться форматом — выставляем явно)
  if (/<p:sldSz[^>]*\/>/.test(pres)) pres = pres.replace(/<p:sldSz[^>]*\/>/, `<p:sldSz cx="${CX}" cy="${CY}"/>`);
  else pres = pres.replace(/(<p:notesSz)/, `<p:sldSz cx="${CX}" cy="${CY}"/>$1`);
  // направляющие в presentation (если вдруг нет — взять из мастера)
  if (!new RegExp(GUIDE_URI_PRES.replace(/[{}]/g, '\\$&')).test(pres)) {
    const tm = await base.file('ppt/slideMasters/slideMaster1.xml').async('string');
    const a = tm.indexOf('<p15:sldGuideLst'), b = tm.indexOf('</p15:sldGuideLst>');
    if (a >= 0 && b >= 0) {
      const lst = tm.slice(a, b + '</p15:sldGuideLst>'.length);
      const ext = '<p:ext uri="' + GUIDE_URI_PRES + '">' + lst + '</p:ext>';
      if (/<p:extLst>/.test(pres)) pres = pres.replace('</p:extLst>', ext + '</p:extLst>');
      else pres = pres.replace('</p:presentation>', '<p:extLst>' + ext + '</p:extLst></p:presentation>');
    }
  }
  base.file('ppt/presentation.xml', pres);

  // 5. удалить осиротевшие медиа/диаграммы/вложения/заметки по достижимости из .rels
  const resolve = (rf, t) => {
    if (/^https?:/.test(t)) return null;
    const dir = rf.replace(/\/_rels\/[^/]+$/, ''); const out = [];
    for (const seg of (dir + '/' + t).split('/')) {
      if (seg === '..') out.pop(); else if (seg === '.' || seg === '') continue; else out.push(seg);
    }
    return out.join('/');
  };
  const live = new Set();
  for (const rf of Object.keys(base.files).filter(n => /\.rels$/.test(n) && !base.files[n].dir)) {
    const x = await base.file(rf).async('string');
    for (const m of x.matchAll(/Target="([^"]+)"/g)) { const p = resolve(rf, m[1]); if (p) live.add(p); }
  }
  const pruneRe = /^ppt\/(media|embeddings|charts|drawings|tags|notesSlides)\//;
  for (const nm of Object.keys(base.files)) {
    if (base.files[nm].dir) continue;
    if (pruneRe.test(nm) && !live.has(nm)) base.remove(nm);
  }
  for (const nm of Object.keys(base.files)) {
    if (/\.rels$/.test(nm)) {
      const owner = nm.replace(/_rels\//, '').replace(/\.rels$/, '');
      if (pruneRe.test(owner) && !base.files[owner]) base.remove(nm);
    }
  }

  // 6. content-types: слайды + чистка висящих override + дефолты картинок
  let ct = await base.file('[Content_Types].xml').async('string');
  ct = ct.replace(/<Override PartName="\/ppt\/slides\/slide\d+\.xml"[^>]*\/>/g, '');
  ct = ct.replace(/<Override PartName="\/ppt\/notesSlides\/notesSlide\d+\.xml"[^>]*\/>/g, '');
  ct = ct.replace(/<Override PartName="([^"]+)"[^>]*\/>/g, (m, p) => base.files[p.slice(1)] ? m : '');
  // дефолты для расширений картинок, которых ещё нет в [Content_Types]
  const imgMime = { png: 'image/png', jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp', svg: 'image/svg+xml' };
  let defs = '';
  for (const ext of usedImgExt) {
    if (new RegExp(`<Default Extension="${ext}"`, 'i').test(ct)) continue;
    defs += `<Default Extension="${ext}" ContentType="${imgMime[ext] || 'application/octet-stream'}"/>`;
  }
  if (defs) ct = ct.replace(/(<Types[^>]*>)/, '$1' + defs);
  let so = '';
  for (let i = 1; i <= N; i++)
    so += `<Override PartName="/ppt/slides/slide${i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>`;
  ct = ct.replace('</Types>', so + '</Types>');
  base.file('[Content_Types].xml', ct);

  // 7. ГЕЙТ. Фирменность здесь — по построению; но прогоняем те же 15 инвариантов.
  //    Если хоть один упал — это БАГ сборщика, файл не отдаём.
  if (typeof checkBrand === 'function') {
    const checks = await checkBrand(base);
    const failed = Object.entries(checks).filter(([, ok]) => !ok).map(([k]) => k);
    if (failed.length) throw new Error('buildBrandPptx: внутренняя проверка не прошла — ' +
      failed.join(', ') + '. Это баг сборщика, файл не отдан.');
  } else {
    throw new Error('buildBrandPptx: сначала загрузи finalize-pptx.js (нужен checkBrand для гейта).');
  }

  return base.generateAsync({
    type: 'blob',
    mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    compression: 'DEFLATE', compressionOptions: { level: 6 },
  });
}

if (typeof window !== 'undefined') window.buildBrandPptx = buildBrandPptx;
if (typeof module !== 'undefined') module.exports = { buildBrandPptx };
