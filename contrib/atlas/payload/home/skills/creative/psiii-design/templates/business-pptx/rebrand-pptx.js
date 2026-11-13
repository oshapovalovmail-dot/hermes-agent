/* ════════════════════════════════════════════════════════════════════════
 *  rebrand-pptx.js — рестайл ГОТОВОГО чужого .pptx к теме ПСиИИ НА МЕСТЕ.
 *
 *  Назначение (Правило 84): пользователь принёс свой .pptx и просит «привести к
 *  дизайн-системе». Контент неприкосновенен — слайды, текст, картинки, кастомные
 *  макеты НЕ трогаем (Правила 23/83/84). Меняем ТОЛЬКО фирменную оболочку темы:
 *    • цветовая схема  → палитра ПСиИИ (с акцентом #F66048);
 *    • шрифты          → YS Display Cond Heavy (major) / YS Text Regular (minor);
 *    • размер слайда   → 67,73 × 38,1 см (Правило 2);
 *    • направляющие    → фирменная сетка p15 в presentation и в каждом мастере (Правило 3).
 *  Цвета/шрифты заливаются во ВСЕ темы файла (у импортированных дек их много).
 *
 *  Это НЕ finalizePptx. finalizePptx пересобирает деку на наших 18 макетах
 *  (титул-красный/финал-серый/...) — он для дек, СВЁРСТАННЫХ в нашем шаблоне, и
 *  для чужой деки уничтожил бы кастомные макеты и потребовал бы заново расставить
 *  все картинки. rebrandPptxInPlace ничего не пересобирает: сколько слайдов и
 *  картинок вошло — столько и вышло.
 *
 *  Использование (внутри run_script, JSZip уже загружен):
 *    eval(await readFile('<ds>/templates/business-pptx/rebrand-pptx.js'));
 *    const out = await rebrandPptxInPlace({
 *      JSZip,
 *      templateBytes: await readFileBinary('<ds>/templates/business-pptx/source.pptx'),
 *      draftBytes:    await readFileBinary('uploads/<draft-ascii>.pptx'), // ASCII-имя! (Правило 85)
 *    });
 *    const v = await assertIngestRebrand({ JSZip, bytes: out, draftBytes });
 *    if (!v.ok) throw new Error('рестайл не прошёл: ' + v.failed.join(', '));
 *    await saveFile('export/deck.pptx', out); // отдать карточкой в чат (Правило 86)
 * ════════════════════════════════════════════════════════════════════════ */

async function rebrandPptxInPlace({ JSZip, templateBytes, draftBytes }) {
  const CX = 24382800, CY = 13716000;                 // Правило 2
  const GUIDE_URI_PRES = '{EFAFB233-063F-42B5-8137-9DF3F51BA10A}';
  const GUIDE_URI_MASTER = '{27BBF7A9-308A-43DC-89C8-2F10F3537804}';
  const P15_NS = 'http://schemas.microsoft.com/office/powerpoint/2012/main';

  // — фирменные блоки берём из самого шаблона (всегда в синхроне) —
  const tpl = await JSZip.loadAsync(templateBytes);
  const tplTheme = await tpl.file('ppt/theme/theme1.xml').async('string');
  const brandClr = (tplTheme.match(/<a:clrScheme[\s\S]*?<\/a:clrScheme>/) || [])[0];
  const brandFont = (tplTheme.match(/<a:fontScheme[\s\S]*?<\/a:fontScheme>/) || [])[0];
  const tplMaster = await tpl.file('ppt/slideMasters/slideMaster1.xml').async('string');
  const guideLst = tplMaster.slice(
    tplMaster.indexOf('<p15:sldGuideLst'),
    tplMaster.indexOf('</p15:sldGuideLst>') + '</p15:sldGuideLst>'.length);
  if (!brandClr || !brandFont || !guideLst)
    throw new Error('rebrandPptxInPlace: не нашёл фирменные блоки в source.pptx — проверь templateBytes');

  const base = await JSZip.loadAsync(draftBytes);
  const names = Object.keys(base.files).filter(n => !base.files[n].dir);

  // 1. ВСЕ темы: цветовая схема + шрифты → фирменные
  for (const tn of names.filter(n => /ppt\/theme\/theme\d+\.xml$/.test(n))) {
    let th = await base.file(tn).async('string');
    if (/<a:clrScheme[\s\S]*?<\/a:clrScheme>/.test(th))
      th = th.replace(/<a:clrScheme[\s\S]*?<\/a:clrScheme>/, brandClr);
    if (/<a:fontScheme[\s\S]*?<\/a:fontScheme>/.test(th))
      th = th.replace(/<a:fontScheme[\s\S]*?<\/a:fontScheme>/, brandFont);
    base.file(tn, th);
  }

  // вспом.: вставить/заменить guide-ext с нужным URI в произвольный extLst-контейнер
  const ensureP15 = (xml, rootTag) =>
    new RegExp('xmlns:p15=').test(xml) ? xml
      : xml.replace(rootTag, rootTag.replace(/>$/, ` xmlns:p15="${P15_NS}">`));
  const reExt = uri => new RegExp('<p:ext uri="\\' + uri.slice(0, -1) + '\\}">[\\s\\S]*?<\\/p:ext>');

  // 2. presentation.xml: размер + направляющие (presentation-уровень)
  {
    let pres = await base.file('ppt/presentation.xml').async('string');
    const rootTag = (pres.match(/<p:presentation\b[^>]*>/) || [])[0];
    if (rootTag) pres = ensureP15(pres, rootTag);
    const ext = '<p:ext uri="' + GUIDE_URI_PRES + '">' + guideLst + '</p:ext>';
    if (reExt(GUIDE_URI_PRES).test(pres)) pres = pres.replace(reExt(GUIDE_URI_PRES), ext);
    else if (/<p:extLst>/.test(pres)) pres = pres.replace('</p:extLst>', ext + '</p:extLst>');
    else pres = pres.replace('</p:presentation>', '<p:extLst>' + ext + '</p:extLst></p:presentation>');
    if (/<p:sldSz[^>]*\/>/.test(pres)) pres = pres.replace(/<p:sldSz[^>]*\/>/, `<p:sldSz cx="${CX}" cy="${CY}"/>`);
    else pres = pres.replace('</p:presentation>', `<p:sldSz cx="${CX}" cy="${CY}"/></p:presentation>`);
    base.file('ppt/presentation.xml', pres);
  }

  // 3. КАЖДЫЙ мастер: направляющие (master-уровень)
  for (const mn of names.filter(n => /ppt\/slideMasters\/slideMaster\d+\.xml$/.test(n))) {
    let m = await base.file(mn).async('string');
    const rootTag = (m.match(/<p:sldMaster\b[^>]*>/) || [])[0];
    if (rootTag) m = ensureP15(m, rootTag);
    const ext = '<p:ext uri="' + GUIDE_URI_MASTER + '">' + guideLst + '</p:ext>';
    if (reExt(GUIDE_URI_MASTER).test(m)) m = m.replace(reExt(GUIDE_URI_MASTER), ext);
    else if (/<p:extLst>/.test(m)) m = m.replace('</p:extLst>', ext + '</p:extLst>');
    else m = m.replace('</p:sldMaster>', '<p:extLst>' + ext + '</p:extLst></p:sldMaster>');
    base.file(mn, m);
  }

  // 4. ВШИТЬ ШРИФТЫ YS (Правило 87). Драфт пользователя их не несёт, а рестайл
  //    меняет шрифты темы на YS — без вшитых байтов у внешнего/публичного
  //    пользователя PowerPoint подставит Calibri и фирменность развалится.
  //    Переносим уже вшитые шрифты ПРЯМО ИЗ ШАБЛОНА (он их несёт) — байты
  //    загружать не нужно. Копируем font-части, их relationships и embeddedFontLst.
  {
    let pres = await base.file('ppt/presentation.xml').async('string');
    const tplPres = await tpl.file('ppt/presentation.xml').async('string');
    const fontLst = (tplPres.match(/<p:embeddedFontLst>[\s\S]*?<\/p:embeddedFontLst>/) || [])[0];
    const tplPrels = await tpl.file('ppt/_rels/presentation.xml.rels').async('string');
    if (fontLst && !/<p:embeddedFontLst>/.test(pres)) {
      // 4a. перенести font-части шаблона (ppt/fonts/*.fntdata)
      for (const fn of Object.keys(tpl.files).filter(n => /ppt\/fonts\/.+\.fntdata$/.test(n)))
        base.file(fn, await tpl.file(fn).async('uint8array'));
      // 4b. перенести font-relationships, не пересекаясь по rId с драфтом
      let maxId = 0;
      for (const m of pres.matchAll(/r:id="rId(\d+)"/g)) maxId = Math.max(maxId, +m[1]);
      let bprels = await base.file('ppt/_rels/presentation.xml.rels').async('string');
      for (const m of bprels.matchAll(/Id="rId(\d+)"/g)) maxId = Math.max(maxId, +m[1]);
      const idMap = {}; let newRels = '';
      for (const m of tplPrels.matchAll(/<Relationship Id="([^"]+)"[^>]*Type="[^"]*\/font"[^>]*Target="([^"]+)"[^>]*\/>/g)) {
        const nid = 'rId' + (++maxId); idMap[m[1]] = nid;
        newRels += `<Relationship Id="${nid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/font" Target="${m[2]}"/>`;
      }
      bprels = bprels.replace('</Relationships>', newRels + '</Relationships>');
      base.file('ppt/_rels/presentation.xml.rels', bprels);
      // 4c. перенумеровать r:id внутри embeddedFontLst под новые rId
      let lst = fontLst.replace(/r:id="([^"]+)"/g, (mm, id) => `r:id="${idMap[id] || id}"`);
      // 4d. вставить список + включить встраивание (порядок по схеме CT_Presentation)
      const rootTag = (pres.match(/<p:presentation\b[^>]*>/) || [])[0];
      if (rootTag && !/embedTrueTypeFonts=/.test(rootTag))
        pres = pres.replace(rootTag, rootTag.replace(/>$/, ' embedTrueTypeFonts="1" saveSubsetFonts="0">'));
      else if (/embedTrueTypeFonts=/.test(pres))
        pres = pres.replace(/embedTrueTypeFonts="[^"]*"/, 'embedTrueTypeFonts="1"');
      if (/<p:notesSz\b[^>]*\/>/.test(pres)) pres = pres.replace(/(<p:notesSz\b[^>]*\/>)/, '$1' + lst);
      else if (/<p:sldSz\b[^>]*\/>/.test(pres)) pres = pres.replace(/(<p:sldSz\b[^>]*\/>)/, '$1' + lst);
      else pres = pres.replace('</p:presentation>', lst + '</p:presentation>');
      base.file('ppt/presentation.xml', pres);
      // 4e. content-type для fntdata
      let ct = await base.file('[Content_Types].xml').async('string');
      if (!/Extension="fntdata"/.test(ct)) {
        ct = ct.replace('</Types>', '<Default Extension="fntdata" ContentType="application/x-fontdata"/></Types>');
        base.file('[Content_Types].xml', ct);
      }
    }
  }

  return await base.generateAsync({
    type: 'blob',
    mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    compression: 'DEFLATE', compressionOptions: { level: 6 },
  });
}

/* Лёгкий гейт ДЛЯ ИНГЕСТ-РЕСТАЙЛА (не путать с assertBrandPptx для наших-шаблонных
 * дек). Проверяет, что оболочка фирменная И контент не потерян относительно драфта:
 *   size, guides_pres, guides_master, theme_red, theme_fonts, fonts_embedded,
 *   slides_preserved (число слайдов = драфт),
 *   media_preserved (число картинок ≥ драфт — СЛАБЫЙ, считает только количество),
 *   media_content_preserved (КАЖДАЯ картинка драфта присутствует в выдаче по SHA-256).
 * Именно media_content_preserved ловит «скриншоты драфта заменили на иконки»: при
 * пересборке число медиа может быть большим (много иконок), а реальные картинки
 * драфта всё равно потеряны — похэшевое сравнение это ловит. Рестайл на месте копирует
 * байты драфта вербатим — хэши совпадают; пересборка перекодирует — хэши расходятся,
 * и гейт краснеет. Это и есть энфорсмент Правил 83/84: только реальная сохранность
 * картинок проходит. draftBytes обязателен. */
async function assertIngestRebrand({ JSZip, bytes, draftBytes }) {
  const sha = async u8 => {
    const h = await crypto.subtle.digest('SHA-256', u8);
    return [...new Uint8Array(h)].map(b => b.toString(16).padStart(2, '0')).join('');
  };
  const load = async b => {
    const z = await JSZip.loadAsync(b);
    const ns = Object.keys(z.files).filter(n => !z.files[n].dir);
    const mediaNames = ns.filter(n => /ppt\/media\//.test(n));
    const hashes = new Set();
    for (const mn of mediaNames) hashes.add(await sha(await z.file(mn).async('uint8array')));
    return {
      slides: ns.filter(n => /ppt\/slides\/slide\d+\.xml$/.test(n)).length,
      media: mediaNames.length,
      hashes,
      pres: z.file('ppt/presentation.xml') ? await z.file('ppt/presentation.xml').async('string') : '',
      theme: z.file('ppt/theme/theme1.xml') ? await z.file('ppt/theme/theme1.xml').async('string') : '',
      master: z.file('ppt/slideMasters/slideMaster1.xml') ? await z.file('ppt/slideMasters/slideMaster1.xml').async('string') : '',
    };
  };
  const out = await load(bytes);
  const draft = draftBytes ? await load(draftBytes) : null;
  const checks = {
    size:            /cx="24382800"\s+cy="13716000"/.test(out.pres),
    guides_pres:     /EFAFB233-063F-42B5-8137-9DF3F51BA10A/.test(out.pres),
    guides_master:   /sldGuideLst/.test(out.master),
    theme_red:       /F66048/i.test(out.theme),
    theme_fonts:     /YS Display Cond|YS Text/i.test(out.theme),
    fonts_embedded:  /<p:embeddedFontLst>/.test(out.pres) && /embedTrueTypeFonts="1"/.test(out.pres),
    slides_preserved: draft ? out.slides === draft.slides : out.slides > 0,
    media_preserved:  draft ? out.media >= draft.media : true,
    media_content_preserved: draft ? [...draft.hashes].every(h => out.hashes.has(h)) : true,
  };
  const missing = draft ? [...draft.hashes].filter(h => !out.hashes.has(h)).length : 0;
  const failed = Object.entries(checks).filter(([, ok]) => !ok).map(([k]) => k);
  return { ok: failed.length === 0, checks, failed,
           counts: { slides: out.slides, media: out.media, draftSlides: draft && draft.slides,
             draftMedia: draft && draft.media, draftImagesMissing: missing } };
}

if (typeof module !== 'undefined' && module.exports)
  module.exports = { rebrandPptxInPlace, assertIngestRebrand };
