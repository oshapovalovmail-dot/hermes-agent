/**
 * finalize-pptx — приводит ЛЮБОЙ экспорт слайдов (например, из gen_pptx) к
 * фирменному стандарту ПСиИИ. БЕЗ ИСКЛЮЧЕНИЙ применяй после каждого экспорта,
 * иначе теряются размер слайда, направляющие, тема и 18 макетов.
 *
 * Что делает (правила 2, 3, 10, 11 дизайн-системы):
 *  1. Собирает файл НА ОСНОВЕ шаблона `templates/business-pptx/source.pptx`
 *     (в нём уже корректны мастер, 18 макетов, тема F2F2F2 + шрифты YS,
 *     116 направляющих, content-types) — удаляет слайды-примеры шаблона.
 *  2. Вставляет твои слайды из сырого экспорта, привязывая каждый к макету.
 *  3. Заливает направляющие в presentation-список ({EFAFB233}) — иначе их не
 *     видно в обычном виде PowerPoint.
 *  4. Выставляет размер 67,73 × 38,1 см.
 *  5. Чистит осиротевшие медиа/диаграммы/вложения по достижимости из .rels
 *     (иначе файл раздувается до десятков МБ) и битые content-type.
 *
 * Использование (внутри run_script, JSZip уже подгружен):
 *   const out = await finalizePptx({
 *     JSZip,
 *     templateBytes: await readFileBinary('<путь к source.pptx>'),
 *     rawBytes:      await readFileBinary('<путь к сырому экспорту>'),
 *     layoutByIndex: { 1:'slideLayout1.xml', 2:'slideLayout9.xml', ... }, // 1-based
 *   });
 *   await saveFile('export/deck.pptx', out);
 *
 * Карта макетов (имя → файл) в шаблоне ПСиИИ (проверено по <p:cSld name>):
 *   slideLayout1  Титульный слайд_1 (КРАСНЫЙ) slideLayout10 Цифра
 *   slideLayout2  Содержание                  slideLayout11 Тезис (КРАСНЫЙ)
 *   slideLayout3  Раздел_красный (КРАСНЫЙ)    slideLayout12 Заголовок 40 пт
 *   slideLayout4  Заголовок 96 пт             slideLayout13 Карточки_3
 *   slideLayout5  Заголовок 72 пт             slideLayout14 Карточки_2
 *   slideLayout6  Заголовок 72пт+подзаголовок slideLayout15 Карточки_цифры
 *   slideLayout7  Заголовок 60 пт             slideLayout16 Мокап
 *   slideLayout8  Заголовок 40 пт             slideLayout17 Фото
 *   slideLayout9  Пустой слайд (БЕЗ title)    slideLayout18 1_Финальный слайд (СЕРЫЙ)
 *
 * АВТО-РАСКЛАДКА (если layoutByIndex не задан — это и есть штатный путь):
 *   слайд 1        → slideLayout1  (титул, красный фон, заголовок-плейсхолдер)
 *   последний (N>1)→ slideLayout18 (финал, СЕРЫЙ фон — правило 45, не красный)
 *   полностью красный слайд в середине → slideLayout3 (раздел, красный)
 *   остальные      → slideLayout6  (контент: заголовок 72пт + подзаголовок, белый)
 * Поэтому достаточно голого вызова finalizePptx({ JSZip, templateBytes, rawBytes }) —
 * титул станет красным, финал серым, заголовки уедут в плейсхолдеры макета (72пт,
 * YS Display Cond Heavy). layoutByIndex нужен лишь чтобы переопределить конкретный
 * слайд (например, средний слайд под «Цифру» slideLayout10 или «Тезис» slideLayout11).
 */
async function finalizePptx({ JSZip, templateBytes, rawBytes, layoutByIndex, slideCount, slidesMeta, logoSlides }) {
  const CX = 24382800, CY = 13716000;            // 67,73 × 38,1 см (правило 2)
  const GUIDE_URI_PRES   = '{EFAFB233-063F-42B5-8137-9DF3F51BA10A}';
  const SECTION_URI      = '{521415D9-36F7-43E2-AB2F-B90AF26B5E84}';
  const L_TITLE = 'slideLayout1.xml', L_SECTION = 'slideLayout3.xml',
        L_CONTENT = 'slideLayout6.xml', L_FINAL = 'slideLayout18.xml', L_THESIS = 'slideLayout11.xml';

  const base = await JSZip.loadAsync(templateBytes);
  const raw  = await JSZip.loadAsync(rawBytes);

  const rawSlides = Object.keys(raw.files)
    .filter(n => /ppt\/slides\/slide\d+\.xml$/.test(n))
    .sort((a, b) => (+a.match(/\d+/)) - (+b.match(/\d+/)));
  const N = slideCount || rawSlides.length;

  // ── масштаб геометрии импортируемых слайдов ──
  // gen_pptx отдаёт слайды в своём размере (например 1920×1080 EMU); целевой
  // канвас шаблона — 67,73×38,1 см. Без масштабирования контент сидит в углу и
  // кажется мелким. Берём исходный размер из raw presentation.xml и приводим к CX/CY.
  const A = 'http://schemas.openxmlformats.org/drawingml/2006/main';
  const rawPres = await raw.file('ppt/presentation.xml').async('string');
  const rawSz = (rawPres.match(/<p:sldSz[^>]*\/>/) || [''])[0];
  const rawCX = +((rawSz.match(/cx="(\d+)"/) || [])[1] || CX);
  const rawCY = +((rawSz.match(/cy="(\d+)"/) || [])[1] || CY);
  const kx = CX / rawCX, ky = CY / rawCY, k = (kx + ky) / 2;
  const needScale = Math.abs(kx - 1) > 1e-4 || Math.abs(ky - 1) > 1e-4;
  function scaleSlide(xml) {
    if (!needScale) return xml;
    const doc = new DOMParser().parseFromString(xml, 'application/xml');
    if (doc.querySelector('parsererror')) return xml; // не трогаем, если не распарсилось
    const R = (el, a, f) => { if (el.hasAttribute(a)) el.setAttribute(a, String(Math.round(parseFloat(el.getAttribute(a)) * f))); };
    for (const el of doc.getElementsByTagName('*')) {
      const ln = el.localName, ns = el.namespaceURI;
      if (ns === A && (ln === 'off' || ln === 'chOff') && el.hasAttribute('x')) { R(el, 'x', kx); R(el, 'y', ky); }
      else if (ns === A && (ln === 'ext' || ln === 'chExt') && el.hasAttribute('cx')) { R(el, 'cx', kx); R(el, 'cy', ky); }
      else if (ln === 'rPr' || ln === 'defRPr' || ln === 'endParaRPr') { R(el, 'sz', k); }
      else if (ns === A && ln === 'ln') { R(el, 'w', k); }
      else if (ln === 'gridCol') { R(el, 'w', kx); }
      else if (ln === 'tr') { R(el, 'h', ky); }
      else if (ln === 'spcPts') { R(el, 'val', ky); }
      else if (ln === 'pPr' || /^lvl\dpPr$/.test(ln)) { R(el, 'marL', kx); R(el, 'indent', kx); }
    }
    return new XMLSerializer().serializeToString(doc);
  }

  // 1. удалить слайды-примеры и заметки шаблона
  for (const n of Object.keys(base.files)) {
    if (/ppt\/slides\/slide\d+\.xml$/.test(n) ||
        /ppt\/slides\/_rels\/slide\d+\.xml\.rels$/.test(n) ||
        /ppt\/notesSlides\//.test(n)) base.remove(n);
  }

  // 2. перенести медиа сырого экспорта (с новыми именами, чтобы не пересечься)
  const relHdr = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' +
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">';
  const layoutName = (i, sx) => {
    if (layoutByIndex && layoutByIndex[i]) return layoutByIndex[i]; // явное переопределение
    if (i === 1) return L_TITLE;                       // титул  → красный, заголовок-плейсхолдер
    if (N > 1 && i === N) return L_FINAL;              // финал  → СЕРЫЙ (правило 45)
    if (sx && isRedFullBleed(sx)) return isThesis(sx) ? L_THESIS : L_SECTION; // красный: тезис → «Тезис», иначе → «Раздел»
    return L_CONTENT;                                  // контент → заголовок 72пт + подзаголовок
  };
  // красный слайд: ТЕЗИС (целое утверждение-предложение) vs РАЗДЕЛ-перебивка
  // (короткий заголовок). Тезис должен идти на макете «Тезис» (slideLayout11), а не
  // «Раздел» (slideLayout3) — Правило 71. Различаем по длине самого крупного текста:
  // раздел — 1–3 слова («Финансы», «Команда и масштаб»), тезис — фраза.
  function isThesis(xml) {
    let best = null;
    for (const m of xml.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)) {
      const sp = m[0];
      const txt = (sp.match(/<a:t>([^<]*)<\/a:t>/g) || []).map(t => t.replace(/<\/?a:t>/g, '')).join('').trim();
      if (!txt) continue;
      const sz = Math.max(0, ...[...sp.matchAll(/sz="(\d+)"/g)].map(x => +x[1]));
      if (!best || sz > best.sz) best = { sz, txt };
    }
    if (!best) return false;
    const words = best.txt.split(/\s+/).filter(Boolean).length;
    return best.txt.length > 45 || words >= 6;
  }
  // полностью красный слайд = фон <p:bg> красный ИЛИ полноэкранная фигура с
  // СОБСТВЕННОЙ красной заливкой (не просто красный акцент внутри контент-блока)
  function isRedFullBleed(xml) {
    const bg = (xml.match(/<p:bg>[\s\S]*?<\/p:bg>/) || [''])[0];
    if (/val="accent2"|F66048/i.test(bg)) return true;
    for (const m of xml.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)) {
      const spPr = (m[0].match(/<p:spPr>[\s\S]*?<\/p:spPr>/) || [''])[0];
      const fill = (spPr.match(/<a:solidFill>[\s\S]*?<\/a:solidFill>/) || [''])[0];
      if (!/val="accent2"|F66048/i.test(fill)) continue;
      const off = spPr.match(/<a:off x="(-?\d+)" y="(-?\d+)"/), ext = spPr.match(/<a:ext cx="(\d+)" cy="(\d+)"/);
      if (off && ext && +off[1] <= 0.02 * CX && +off[2] <= 0.02 * CY && +ext[1] >= 0.96 * CX && +ext[2] >= 0.96 * CY) return true;
    }
    return false;
  }
  // снять фейковый полноэкранный фон-прямоугольник (заливка без текста на весь
  // слайд) — фон должен давать макет (титул красный, раздел красный, финал серый,
  // контент белый), а не зашитая в слайд плашка. Текстовые боксы не трогаем.
  function stripBleedBgShapes(xml) {
    return xml.replace(/<p:sp>[\s\S]*?<\/p:sp>/g, sp => {
      const hasText = (sp.match(/<a:t>([^<]*)<\/a:t>/g) || []).some(t => t.replace(/<\/?a:t>/g, '').trim());
      const spPr = (sp.match(/<p:spPr>[\s\S]*?<\/p:spPr>/) || [''])[0];
      if (hasText || !/<a:solidFill>/.test(spPr)) return sp;
      const off = spPr.match(/<a:off x="(-?\d+)" y="(-?\d+)"/), ext = spPr.match(/<a:ext cx="(\d+)" cy="(\d+)"/);
      if (off && ext && +off[1] <= 0.02 * CX && +off[2] <= 0.02 * CY && +ext[1] >= 0.96 * CX && +ext[2] >= 0.96 * CY) return '';
      return sp;
    });
  }

  // ── вставка фирменных плейсхолдеров (правило: заголовок/подзаголовок/примечание/
  //    номер всегда в плейсхолдерах макета) ──
  // slidesMeta[i-1] = { placeholders: [ {ph, idx?, lines?[], field?, num?, match?[]} ] }
  // Каждый плейсхолдер наследует позицию и формат из макета (spPr пуст). `match`
  // (строки) задаёт свободные текст-боксы из генератора, которые надо удалить,
  // чтобы не задваивать текст.
  const esc = t => String(t).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const norm = t => String(t).replace(/\u00a0/g, '').replace(/\s+/g, '').toLowerCase();
  function phSp(id, ph) {
    const phTag = `<p:ph type="${ph.ph}"${ph.idx != null ? ` idx="${ph.idx}"` : ''}/>`;
    let body;
    if (ph.field) {
      body = `<a:p><a:fld id="{C1B2A3D4-0000-4F00-9000-00000000000${id % 10}}" type="slidenum"><a:t>${esc(ph.num != null ? ph.num : '')}</a:t></a:fld></a:p>`;
    } else {
      // ph.sz (в сотых pt) пинит кегль рана; шрифт/цвет НАСЛЕДУЮТСЯ из макета
      // (не добавляем <a:latin> — инвариант title_font не ломается). Нужно только
      // когда фиксированный кегль макета (напр. титул 220pt) не подходит под текст.
      const rpr = ph.sz != null ? `<a:rPr lang="ru-RU" sz="${ph.sz}"/>` : '';
      body = (ph.lines && ph.lines.length ? ph.lines : ['']).map(t =>
        `<a:p><a:r>${rpr}<a:t>${esc(t)}</a:t></a:r></a:p>`).join('');
    }
    return `<p:sp><p:nvSpPr><p:cNvPr id="${id}" name="PH ${ph.ph}${ph.idx != null ? ph.idx : ''}"/>` +
      `<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr>${phTag}</p:nvPr></p:nvSpPr>` +
      `<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>${body}</p:txBody></p:sp>`;
  }
  function applyPlaceholders(xml, meta, slideIdx) {
    if (!meta || !meta.placeholders || !meta.placeholders.length) return xml;
    // 1. удалить свободные текст-боксы, совпадающие по тексту с плейсхолдерами
    const targets = new Set();
    for (const ph of meta.placeholders)
      for (const m of (ph.match || ph.lines || [])) if (m) targets.add(norm(m));
    xml = xml.replace(/<p:sp>[\s\S]*?<\/p:sp>/g, sp => {
      const txt = norm((sp.match(/<a:t>([^<]*)<\/a:t>/g) || []).map(t => t.replace(/<\/?a:t>/g, '')).join(''));
      return txt && targets.has(txt) ? '' : sp;
    });
    // 2. добавить плейсхолдеры перед концом дерева
    let id = 900 + slideIdx * 20;
    const add = meta.placeholders.map(ph => phSp(id++, ph)).join('');
    return xml.replace('</p:spTree>', add + '</p:spTree>');
  }

  // ── авто-повышение заголовка в плейсхолдер (правило 12) ──
  // Если макет слайда имеет title-плейсхолдер, а в слайде его нет (gen_pptx
  // отдаёт заголовок свободным текст-боксом), превращаем самый крупный верхний
  // текст-бокс в настоящий <p:ph type="title"> — текст и позицию сохраняем, но
  // он становится редактируемым полем, наследует формат и обновляется мастером.
  const _layTitleCache = {};
  async function layoutHasTitle(file) {
    if (file in _layTitleCache) return _layTitleCache[file];
    const lx = await base.file('ppt/slideLayouts/' + file).async('string').catch(() => '');
    return (_layTitleCache[file] = /<p:ph[^>]*type="title"/.test(lx));
  }
  function promoteTitle(xml, hasTitleLayout) {
    if (!hasTitleLayout) return xml;
    if (/<p:ph[^>]*type="title"/.test(xml)) return xml; // уже есть title (из slidesMeta)
    // собрать все НЕ-плейсхолдерные текст-боксы с их позицией и кеглем
    const cands = [];
    for (const m of xml.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)) {
      const sp = m[0];
      if (/<p:ph\b/.test(sp)) continue;                          // уже плейсхолдер
      const txt = (sp.match(/<a:t>([^<]*)<\/a:t>/g) || []).map(t => t.replace(/<\/?a:t>/g, '')).join('').trim();
      if (!txt) continue;
      const y = +((sp.match(/<a:off x="-?\d+" y="(-?\d+)"/) || [])[1] || 1e12);
      const x = +((sp.match(/<a:off x="(-?\d+)"/) || [])[1] || 1e12);
      const sz = Math.max(0, ...[...sp.matchAll(/sz="(\d+)"/g)].map(x => +x[1]));
      cands.push({ sp, y, x, sz, index: m.index, len: m[0].length });
    }
    if (!cands.length) return xml;
    // выбор заголовка: заголовок ВСЕГДА у верхней кромки (Правило 12: title на
    // top:77 ≈ 7% канваса; подзаголовок на ≈14%). Берём КРУПНЕЙШИЙ бокс в УЗКОЙ
    // верхней зоне (top 22%) — так кикер-лейбл над заголовком (мельче) проигрывает
    // заголовку, а крупная цифра-значение («31 000», «1 000+»), сидящая НИЖЕ зоны
    // (≈32–37%), уже не может перебить заголовок своим кеглем. Узкая зона —
    // ключ: на старой зоне top 35% цифра-значение попадала в неё и побеждала.
    // приоритет: крупнее → левее (заголовок прижат к полю left:115) → выше. Левизна
    // важна как тай-брейк: на одном верхнем уровне с заголовком может стоять такой же
    // крупный объект справа (напр. число «1997–2007» таймлайна) — настоящий заголовок
    // отличает каноничный левый край.
    const pick = pool => pool.reduce((b, c) => {
      if (!b) return c;
      if (c.sz !== b.sz) return c.sz > b.sz ? c : b;
      if (c.x !== b.x) return c.x < b.x ? c : b;
      return c.y < b.y ? c : b;
    }, null);
    // Если в верхней зоне ничего нет (заголовок посажен ниже — титул/финал),
    // берём крупнейший в верхних 60%, а в крайнем случае — крупнейший на слайде.
    let best = pick(cands.filter(c => c.y <= 0.22 * CY))
            || pick(cands.filter(c => c.y <= 0.60 * CY))
            || pick(cands);
    if (!best) return xml;
    let sp = best.sp;
    sp = sp.replace(/<p:cNvSpPr\s*\/>/, '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr>');
    sp = /<p:nvPr\s*\/>/.test(sp)
      ? sp.replace(/<p:nvPr\s*\/>/, '<p:nvPr><p:ph type="title"/></p:nvPr>')
      : sp.replace(/<p:nvPr>/, '<p:nvPr><p:ph type="title"/>');
    // снять жёстко зашитый шрифт/кегль с рантов — иначе run-level typeface
    // (напр. "YS Text" из генератора) перебивает заголовочный +mj-lt
    // (YS Display Cond Heavy) из макета/мастера. Заголовок должен НАСЛЕДОВАТЬ.
    sp = sp.replace(/<a:latin[^>]*\/>/g, '')
           .replace(/<a:ea[^>]*\/>/g, '')
           .replace(/<a:cs[^>]*\/>/g, '')
           .replace(/(<a:(?:rPr|defRPr|endParaRPr)\b[^>]*?)\s+sz="\d+"/g, '$1');
    return xml.slice(0, best.index) + sp + xml.slice(best.index + best.len);
  }

  // ── нормализация фирменности слайда ──
  // (а) фон: layouts владеют фоном (титул — красный, финал — серый F2F2F2,
  //     контент — белый). Снимаем зашитый <p:bg> слайда, чтобы всегда побеждал
  //     фон фирменного макета (правило 8/45 — финал не красный, а серый).
  function stripSlideBg(xml) { return xml.replace(/<p:bg>[\s\S]*?<\/p:bg>/, ''); }

  // (б) логотип: в фирменной модели лого живёт в макетах титула и финала, а не
  //     ставится на слайд (правило 9). Опознаём лого по хэшу картинки и убираем
  //     его со всех слайдов, кроме титула и финала.
  async function sha(u8) {
    const h = await crypto.subtle.digest('SHA-256', u8);
    return [...new Uint8Array(h)].map(b => b.toString(16).padStart(2, '0')).join('');
  }
  const mediaHash = {};
  for (const mn of Object.keys(raw.files).filter(n => /ppt\/media\//.test(n) && !raw.files[n].dir))
    mediaHash[mn] = await sha(await raw.file(mn).async('uint8array'));
  const resolveImg = t => ('ppt/slides/' + t).replace(/\/[^/]+\/\.\.\//g, '/');
  async function slideImgHashes(idx) {
    const rf = raw.file(rawSlides[idx - 1].replace(/slide(\d+)\.xml$/, '_rels/slide$1.xml.rels'));
    const out = new Map(); // embedId -> hash
    if (!rf) return out;
    const rr = await rf.async('string');
    for (const m of rr.matchAll(/Id="([^"]+)"[^>]*?Target="([^"]+)"/g)) {
      if (!/image/i.test(m[0]) || /^https?:/.test(m[2])) continue;
      const h = mediaHash[resolveImg(m[2])];
      if (h) out.set(m[1], h);
    }
    return out;
  }
  // слайды, где лого РАЗРЕШЁН: по умолчанию титул (1) и финал (N)
  const logoOk = new Set(logoSlides || [1, N]);
  // лого-хэши = пересечение картинок титула и финала (одинаковый знак на обоих),
  // fallback — картинки единственного лого-слайда
  const logoIdxs = [...logoOk].filter(i => i >= 1 && i <= N);
  const logoHashes = new Set();
  if (logoIdxs.length) {
    const sets = await Promise.all(logoIdxs.map(async i => new Set((await slideImgHashes(i)).values())));
    const base0 = sets[0] || new Set();
    for (const h of base0) if (sets.every(s => s.has(h))) logoHashes.add(h);
    if (!logoHashes.size && sets[0]) for (const h of sets[0]) logoHashes.add(h); // fallback
  }
  function removeLogoPics(xml, embedHash) {
    return xml.replace(/<p:pic>[\s\S]*?<\/p:pic>/g, pic => {
      const eid = (pic.match(/r:embed="([^"]+)"/) || [])[1];
      const h = eid && embedHash.get(eid);
      return (h && logoHashes.has(h)) ? '' : pic;
    });
  }

  for (let i = 1; i <= N; i++) {
    let slideXml = scaleSlide(await raw.file(rawSlides[i - 1]).async('string'));
    const lay = layoutName(i, slideXml);            // роль определяем ДО снятия фона (нужен красный bg)
    slideXml = applyPlaceholders(slideXml, slidesMeta && slidesMeta[i - 1], i);
    slideXml = promoteTitle(slideXml, await layoutHasTitle(lay));
    slideXml = stripSlideBg(slideXml);
    slideXml = stripBleedBgShapes(slideXml);        // снять фейковый полноэкранный фон — его даёт макет
    if (!logoOk.has(i)) slideXml = removeLogoPics(slideXml, await slideImgHashes(i));
    base.file('ppt/slides/slide' + i + '.xml', slideXml);

    // перенести картинки этого слайда + построить rels
    const rawRelsFile = raw.file(rawSlides[i - 1].replace(/slide(\d+)\.xml$/, '_rels/slide$1.xml.rels'));
    let rels = '';
    let rId = 1;
    if (rawRelsFile) {
      const rr = await rawRelsFile.async('string');
      for (const m of rr.matchAll(/Target="([^"]+)"/g)) {
        const t = m[1];
        if (/image/.test(rr.slice(Math.max(0, m.index - 120), m.index)) && !/^https?:/.test(t)) {
          const oldId = (rr.slice(0, m.index).match(/Id="([^"]+)"[^>]*$/) || [])[1];
          // пропустить картинку, на которую слайд больше не ссылается (удалённый лого)
          if (oldId && !slideXml.includes('"' + oldId + '"')) continue;
          const srcPath = ('ppt/slides/' + t).replace(/\/[^/]+\/\.\.\//g, '/');
          const ext = t.split('.').pop();
          const dst = 'ppt/media/fin' + i + '_' + rId + '.' + ext;
          const blob = await raw.file(srcPath).async('uint8array').catch(() => null);
          if (blob) {
            base.file(dst, blob);
            rels += `<Relationship Id="rId${rId}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/fin${i}_${rId}.${ext}"/>`;
            rId++;
          }
        }
      }
    }
    rels += `<Relationship Id="rIdL" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/${lay}"/>`;
    base.file('ppt/slides/_rels/slide' + i + '.xml.rels', relHdr + rels + '</Relationships>');
  }

  // 3. presentation.xml.rels — пересобрать ссылки на слайды
  let prels = await base.file('ppt/_rels/presentation.xml.rels').async('string');
  prels = prels.replace(/<Relationship[^>]*Type="[^"]*\/slide"[^>]*\/>/g, '');
  let newSlideRels = '';
  for (let i = 1; i <= N; i++)
    newSlideRels += `<Relationship Id="rIdS${i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide${i}.xml"/>`;
  prels = prels.replace('</Relationships>', newSlideRels + '</Relationships>');
  base.file('ppt/_rels/presentation.xml.rels', prels);

  // 4. presentation.xml — sldIdLst, направляющие, размер, убрать секции
  let pres = await base.file('ppt/presentation.xml').async('string');
  pres = pres.replace(/<p:sldIdLst>[\s\S]*?<\/p:sldIdLst>/,
    '<p:sldIdLst>' + Array.from({ length: N }, (_, k) =>
      `<p:sldId id="${9001 + k}" r:id="rIdS${k + 1}"/>`).join('') + '</p:sldIdLst>');
  pres = pres.replace(new RegExp('<p:ext uri="\\' + SECTION_URI.slice(0, -1) + '\\}">[\\s\\S]*?<\\/p:ext>'), '');
  const tm = await base.file('ppt/slideMasters/slideMaster1.xml').async('string');
  const lst = tm.slice(tm.indexOf('<p15:sldGuideLst'), tm.indexOf('</p15:sldGuideLst>') + '</p15:sldGuideLst>'.length);
  const presGuideExt = '<p:ext uri="' + GUIDE_URI_PRES + '">' + lst + '</p:ext>';
  if (new RegExp('<p:ext uri="\\' + GUIDE_URI_PRES.slice(0, -1) + '\\}">[\\s\\S]*?<\\/p:ext>').test(pres))
    pres = pres.replace(new RegExp('<p:ext uri="\\' + GUIDE_URI_PRES.slice(0, -1) + '\\}">[\\s\\S]*?<\\/p:ext>'), presGuideExt);
  else if (/<p:extLst>/.test(pres)) pres = pres.replace('</p:extLst>', presGuideExt + '</p:extLst>');
  else pres = pres.replace('</p:presentation>', '<p:extLst>' + presGuideExt + '</p:extLst></p:presentation>');
  pres = pres.replace(/<p:sldSz[^>]*\/>/, `<p:sldSz cx="${CX}" cy="${CY}"/>`);
  base.file('ppt/presentation.xml', pres);

  // 5. удалить осиротевшие части по достижимости из .rels
  const resolve = (rf, t) => {
    if (/^https?:/.test(t)) return null;
    const dir = rf.replace(/\/_rels\/[^/]+$/, '');
    const out = [];
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
  for (const name of Object.keys(base.files)) {
    if (base.files[name].dir) continue;
    if (pruneRe.test(name) && !live.has(name)) base.remove(name);
  }
  for (const name of Object.keys(base.files)) {
    if (/\.rels$/.test(name)) {
      const owner = name.replace(/_rels\//, '').replace(/\.rels$/, '');
      if (pruneRe.test(owner) && !base.files[owner]) base.remove(name);
    }
  }

  // content-types: убрать висящие override, добавить свои слайды
  let ct = await base.file('[Content_Types].xml').async('string');
  ct = ct.replace(/<Override PartName="\/ppt\/slides\/slide\d+\.xml"[^>]*\/>/g, '');
  ct = ct.replace(/<Override PartName="\/ppt\/notesSlides\/notesSlide\d+\.xml"[^>]*\/>/g, '');
  ct = ct.replace(/<Override PartName="([^"]+)"[^>]*\/>/g, (m, p) => base.files[p.slice(1)] ? m : '');
  let so = '';
  for (let i = 1; i <= N; i++)
    so += `<Override PartName="/ppt/slides/slide${i}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>`;
  ct = ct.replace('</Types>', so + '</Types>');
  base.file('[Content_Types].xml', ct);

  // 6. САМОПРОВЕРКА (правило: результат стабильно фирменный) — если хоть один
  //    инвариант нарушен, бросаем ошибку и НЕ отдаём файл. Так «слетевший»
  //    экспорт (размер/сетка/тема/макеты) физически не может выйти из функции.
  const checks = await checkBrand(base);
  const failed = Object.entries(checks).filter(([, ok]) => !ok).map(([k]) => k);
  if (failed.length) {
    throw new Error('finalizePptx: результат не прошёл фирменную проверку — ' +
      failed.join(', ') + '. Файл НЕ отдан. Проверь, что templateBytes — это ' +
      'templates/business-pptx/source.pptx, а не сырой экспорт.');
  }

  return base.generateAsync({
    type: 'blob',
    mimeType: 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    compression: 'DEFLATE', compressionOptions: { level: 6 },
  });
}

/**
 * checkBrand(zip) — проверяет 14 фирменных инвариантов на УЖЕ ЗАГРУЖЕННОМ JSZip.
 * Возвращает { size, guides_pres, guides_master, layouts18, theme_red,
 * theme_fonts, theme_name, titles_in_ph, title_font, no_slide_bg, logo_scope,
 * title_slide_red, final_slide_gray, headings_have_layout } —
 * каждый true/false. Внутренняя, без I/O.
 */
async function checkBrand(zip) {
  const names = Object.keys(zip.files).filter(n => !zip.files[n].dir);
  const get = async n => (zip.file(n) ? zip.file(n).async('string') : '');
  const pres = await get('ppt/presentation.xml');
  const theme = await get('ppt/theme/theme1.xml');
  const master = await get('ppt/slideMasters/slideMaster1.xml');
  // шрифты YS вшиты в пакет (правило 87): без этого у внешнего/публичного
  // пользователя PowerPoint подставит Calibri и фирменность развалится, хотя все
  // прочие инварианты (ссылки на тему/шрифт) пройдут. Проверяем БАЙТЫ, не ссылки:
  // объявлен embeddedFontLst + включён embedTrueTypeFonts + физически лежат fntdata.
  const fontsEmbedded = /<p:embeddedFontLst>/.test(pres)
    && /embedTrueTypeFonts="1"/.test(pres)
    && names.some(n => /ppt\/fonts\/.+\.fntdata$/.test(n));
  // каждый слайд, чей макет имеет title-плейсхолдер, должен иметь title-плейсхолдер
  // (правило 12: заголовки — в плейсхолдерах, иначе их нельзя редактировать как поля)
  let titlesInPh = true;
  const _lc = {};
  const layHasTitle = async f => (f in _lc) ? _lc[f] : (_lc[f] = /<p:ph[^>]*type="title"/.test(await get('ppt/slideLayouts/' + f)));
  for (const sn of names.filter(n => /ppt\/slides\/slide\d+\.xml$/.test(n))) {
    const rx = await get(sn.replace(/slide(\d+)\.xml$/, '_rels/slide$1.xml.rels'));
    const lf = (rx.match(/slideLayouts\/(slideLayout\d+\.xml)/) || [])[1];
    if (!lf || !(await layHasTitle(lf))) continue;
    if (!/<p:ph[^>]*type="title"/.test(await get(sn))) { titlesInPh = false; break; }
  }
  // у каждого title-плейсхолдера НЕ должно быть run-level latin-шрифта — иначе
  // он перебивает заголовочный +mj-lt (YS Display Cond Heavy) из макета/мастера
  let titleFontClean = true;
  for (const sn of names.filter(n => /ppt\/slides\/slide\d+\.xml$/.test(n))) {
    const sx = await get(sn);
    const tsp = sx.match(/<p:sp>(?:(?!<\/p:sp>)[\s\S])*?type="title"[\s\S]*?<\/p:sp>/);
    if (tsp && /<a:latin[^>]*typeface=/.test(tsp[0])) { titleFontClean = false; break; }
  }
  // ни один слайд не несёт собственный <p:bg> — фон владеют макеты (правило 8/45)
  let noSlideBg = true;
  const slideNames = names.filter(n => /ppt\/slides\/slide\d+\.xml$/.test(n));
  for (const sn of slideNames) { if (/<p:bg>/.test(await get(sn))) { noSlideBg = false; break; } }
  // логотип только на титуле и финале (правило 9): картинка, повторяющаяся на
  // ≥2 слайдах (фирменный знак), не должна стоять на «средних» слайдах
  let logoScope = true;
  const idx = sn => +sn.match(/slide(\d+)\.xml$/)[1];
  const sorted = slideNames.slice().sort((a, b) => idx(a) - idx(b));
  const first = sorted[0] && idx(sorted[0]), last = sorted.length && idx(sorted[sorted.length - 1]);
  const hashSlides = {}; // imgHash -> Set(slideIndex)
  const mediaHashC = {};
  for (const mn of names.filter(n => /ppt\/media\//.test(n))) {
    const u8 = await (zip.file(mn) ? zip.file(mn).async('uint8array') : Promise.resolve(null));
    if (u8) { const h = await crypto.subtle.digest('SHA-256', u8); mediaHashC[mn] = [...new Uint8Array(h)].map(b => b.toString(16).padStart(2, '0')).join(''); }
  }
  for (const sn of sorted) {
    const rx = await get(sn.replace(/slide(\d+)\.xml$/, '_rels/slide$1.xml.rels'));
    for (const m of rx.matchAll(/Target="([^"]+)"/g)) {
      if (/^https?:/.test(m[1])) continue;
      const p = ('ppt/slides/' + m[1]).replace(/\/[^/]+\/\.\.\//g, '/');
      const h = mediaHashC[p]; if (!h) continue;
      (hashSlides[h] = hashSlides[h] || new Set()).add(idx(sn));
    }
  }
  // Логотип нарушает рамки (Правило 9), только если КАРТИНКА С ТИТУЛА/ФИНАЛА
  // (фирменный знак) появляется ещё и на «среднем» слайде. Картинки, которые
  // повторяются лишь между средними слайдами (иконки/логотипы сервисов по
  // Правилу 69 — напр. Такси на слайдах 2 и 4), логотипом НЕ считаются и
  // нарушением не являются.
  for (const h in hashSlides) {
    const ids = hashSlides[h];
    const onEdge = ids.has(first) || ids.has(last);
    if (!onEdge) continue;                       // не знак с титула/финала — контентная картинка
    for (const id of ids) if (id !== first && id !== last) { logoScope = false; break; }
    if (!logoScope) break;
  }
  // ── роль фона по макету слайда (правила 8/45): титул КРАСНЫЙ, финал СЕРЫЙ ──
  const layFileOf = async sn => {
    const rx = await get(sn.replace(/slide(\d+)\.xml$/, '_rels/slide$1.xml.rels'));
    return (rx.match(/slideLayouts\/(slideLayout\d+\.xml)/) || [])[1];
  };
  const bgKind = async file => {
    if (!file) return 'inherit';
    const bg = ((await get('ppt/slideLayouts/' + file)).match(/<p:bg>[\s\S]*?<\/p:bg>/) || [''])[0];
    if (/val="accent2"|F66048/i.test(bg)) return 'red';
    if (/val="(bg2|lt2)"|F2F2F2/i.test(bg)) return 'gray';
    if (/val="(bg1|lt1)"|FFFFFF/i.test(bg)) return 'white';
    return bg ? 'other' : 'inherit';
  };
  const firstSn = sorted[0], lastSn = sorted[sorted.length - 1];
  const titleSlideRed = sorted.length ? (await bgKind(await layFileOf(firstSn))) === 'red' : true;
  const finalSlideGray = sorted.length <= 1 ? true : (await bgKind(await layFileOf(lastSn))) === 'gray';
  // ── заголовки не теряются на макете без title (закрывает лазейку «всё на Пустом
  //    слайде»): если у слайда есть крупный верхний НЕ-плейсхолдерный текст, его
  //    макет ОБЯЗАН иметь title-плейсхолдер (иначе заголовок не уедет в поле) ──
  let headingsHaveLayout = true;
  for (const sn of slideNames) {
    const lf = await layFileOf(sn);
    if (lf && (await layHasTitle(lf))) continue;       // макет с title — ок
    if (lf === 'slideLayout9.xml') continue;           // «Пустой слайд» — осознанный выбор (Правило 53)
    const sx = await get(sn);
    let bigTop = false;
    for (const m of sx.matchAll(/<p:sp>[\s\S]*?<\/p:sp>/g)) {
      const sp = m[0];
      if (/<p:ph\b/.test(sp)) continue;                // уже плейсхолдер
      const txt = (sp.match(/<a:t>([^<]*)<\/a:t>/g) || []).map(t => t.replace(/<\/?a:t>/g, '')).join('').trim();
      if (!txt) continue;
      const y = +((sp.match(/<a:off x="-?\d+" y="(-?\d+)"/) || [])[1] || 1e12);
      const sz = Math.max(0, ...[...sp.matchAll(/sz="(\d+)"/g)].map(x => +x[1]));
      if (y <= 0.30 * 13716000 && sz >= 3600) { bigTop = true; break; }
    }
    if (bigTop) { headingsHaveLayout = false; break; }
  }
  return {
    size:          /cx="24382800"\s+cy="13716000"/.test(pres),       // правило 2
    guides_pres:   /EFAFB233-063F-42B5-8137-9DF3F51BA10A/.test(pres),// правило 3
    guides_master: /sldGuideLst/.test(master),                        // правило 3
    layouts18:     names.filter(n => /slideLayout\d+\.xml$/.test(n)).length === 18, // правило 11
    theme_red:     /F66048/i.test(theme),                             // правило 10
    theme_fonts:   /YS (Display|Text)/.test(theme),                   // правило 10
    theme_name:    /clrScheme name="F2F2F2"/.test(theme),             // правило 10
    titles_in_ph:  titlesInPh,                                        // правило 12
    title_font:    titleFontClean,                                    // правило 10/12
    no_slide_bg:   noSlideBg,                                         // правило 8/45
    logo_scope:    logoScope,                                         // правило 9
    title_slide_red:  titleSlideRed,                                  // правило 8 (титул красный)
    final_slide_gray: finalSlideGray,                                 // правило 45 (финал серый)
    headings_have_layout: headingsHaveLayout,                         // правило 12 (заголовок в поле)
    fonts_embedded:   fontsEmbedded,                                  // правило 87 (шрифты YS вшиты в файл)
  };
}

/**
 * assertBrandPptx({ JSZip, bytes }) — публичная проверка ГОТОВОГО файла.
 * Прогони ПОСЛЕ любого экспорта/финализации. Возвращает { ok, checks, failed }.
 * Если ok === false — файл нельзя отдавать пользователю, нужно (пере)финализировать.
 *   const v = await assertBrandPptx({ JSZip, bytes: await readFileBinary('export/deck.pptx') });
 *   if (!v.ok) throw new Error('Не фирменный PPTX: ' + v.failed.join(', '));
 */
async function assertBrandPptx({ JSZip, bytes }) {
  const u8 = bytes instanceof Uint8Array ? bytes
    : (bytes.arrayBuffer ? new Uint8Array(await bytes.arrayBuffer()) : bytes);
  const zip = await JSZip.loadAsync(u8);
  const checks = await checkBrand(zip);
  const failed = Object.entries(checks).filter(([, ok]) => !ok).map(([k]) => k);
  return { ok: failed.length === 0, checks, failed };
}

/* ════════════════════════════════════════════════════════════════════════
 *  checkDesignDiscipline(zip) — проверки ВЁРСТКИ КОНТЕНТА (не оболочки).
 *  Отдельно от checkBrand: фирменная оболочка (размер/тема/макеты) ≠ дисциплина
 *  вёрстки. Гоняй ПОСЛЕ оболочечного гейта на деке, которую СОБРАЛ агент
 *  (buildBrandPptx / HTML-экспорт) — её источник агент может починить. На пути
 *  ВОССТАНОВЛЕНИЯ чужого raw-файла как hard-gate можно не применять (контент
 *  чужой, фигуры двигать нельзя) — но результат всё равно полезно показать.
 *  Возвращает { bottom_safe, card_radius, details }:
 *    • bottom_safe (Правило 6): ни одна КОНТЕНТНАЯ фигура не опускается ниже
 *      линии колонтитула минус 3 см (1 080 000 EMU). Плейсхолдеры и элементы,
 *      стоящие на самой линии колонтитула (чроме), не считаются.
 *    • card_radius (Правила 55/26): все «карточные» скругления (roundRect, кроме
 *      пилюль ≈50%) дают близкий АБСОЛЮТНЫЙ радиус — единый язык карточек (≤2
 *      группы радиусов с допуском ±6px к высоте 1080).
 */
async function checkDesignDiscipline(zip) {
  const get = async n => (zip.file(n) ? zip.file(n).async('string') : '');
  const names = Object.keys(zip.files).filter(n => !zip.files[n].dir);
  const slideNames = names.filter(n => /ppt\/slides\/slide\d+\.xml$/.test(n));
  const pres = await get('ppt/presentation.xml');
  const CYm = +((pres.match(/<p:sldSz[^>]*cy="(\d+)"/) || [])[1]) || 13716000;
  const footerEMU = Math.round(979 / 1080 * CYm);
  const limit = footerEMU - 1080000;            // 3 см воздуха (Правило 6)

  // фон по макету: на красном/сером (титул/раздел/финал) колонтитула НЕТ, нижнюю
  // границу там не проверяем (Правило 5) — только на белых контентных слайдах
  const layBg = async sn => {
    const rx = await get(sn.replace(/slide(\d+)\.xml$/, '_rels/slide$1.xml.rels'));
    const lf = (rx.match(/slideLayouts\/(slideLayout\d+\.xml)/) || [])[1];
    if (!lf) return 'inherit';
    const bg = ((await get('ppt/slideLayouts/' + lf)).match(/<p:bg>[\s\S]*?<\/p:bg>/) || [''])[0];
    if (/val="accent2"|F66048/i.test(bg)) return 'red';
    if (/val="(bg2|lt2)"|F2F2F2/i.test(bg)) return 'gray';
    return 'white';
  };

  const overflow = [];                          // {slide, bottomPx}
  const cardRadii = [];                         // px-радиусы КРУПНЫХ карточек (мелкие плашки — исключение, Правило 55)
  const sharpCards = [];                        // {slide, wPx, hPx} — крупные заливные карточки ОСТРЫМ rect (Правило 55)
  const offRed = [];                            // {slide, hex} — красный не фирменный #F66048 (Правило 10/14)
  const periodViol = [];                        // {slide, text} — одиночное предл. с точкой (Правило 51)
  let titleAgenda = false;                      // агенда/содержание на ТИТУЛЬНОМ слайде
  const firstIdx = Math.min(...slideNames.map(n => +n.match(/slide(\d+)/)[1]));
  const isBrandRed = hex => {                    // в допуске к #F66048 (246,96,72)
    const r = parseInt(hex.slice(0,2),16), g = parseInt(hex.slice(2,4),16), b = parseInt(hex.slice(4,6),16);
    return Math.abs(r-246)<=18 && Math.abs(g-96)<=22 && Math.abs(b-72)<=22;
  };
  for (const sn of slideNames) {
    const si = +sn.match(/slide(\d+)/)[1];
    const sx = await get(sn);
    const isContent = (await layBg(sn)) === 'white';

    // — АГЕНДА НА ТИТУЛЕ: на первом слайде не должно быть списка-содержания.
    //   Признак — ≥3 числовых метки-пункта («01»,«02»,«03»…). Содержание — отдельный
    //   макет «Содержание» (slideLayout2), а не титул (Правило 11).
    if (si === firstIdx) {
      const labels = (sx.match(/<a:t>([^<]*)<\/a:t>/g) || [])
        .map(t => t.replace(/<\/?a:t>/g, '').trim())
        .filter(t => /^0?\d{1,2}$/.test(t));
      if (labels.length >= 3) titleAgenda = true;
    }

    // — ТОЧКА В КОНЦЕ ОДИНОЧНОГО ПРЕДЛОЖЕНИЯ (Правило 51), по-абзацно —
    for (const pm of sx.matchAll(/<a:p>[\s\S]*?<\/a:p>/g)) {
      const txt = (pm[0].match(/<a:t>([^<]*)<\/a:t>/g) || []).map(t => t.replace(/<\/?a:t>/g, '')).join('').trim();
      if (txt.length < 8) continue;                       // короткие метки/числа — мимо
      if (!/[а-яёa-z0-9»)«"']\.\s*$/i.test(txt)) continue;   // не оканчивается точкой
      if (/\.\.\.\s*$/.test(txt) || /[!?]\s*$/.test(txt)) continue;        // многоточие / ? !
      const core = txt.replace(/\.\s*$/, '');
      const boundaries = (core.match(/[.!?]\s+[А-ЯA-Z«"(]/g) || []).length; // внутренние границы предложений
      if (boundaries === 0) periodViol.push({ slide: si, text: txt.slice(-44) });  // одно предл. + точка
    }

    for (const m of sx.matchAll(/<p:(sp|pic|graphicFrame)>[\s\S]*?<\/p:\1>/g)) {
      const blk = m[0];
      const off = blk.match(/<a:off x="(-?\d+)" y="(-?\d+)"\/>/);
      const ext = blk.match(/<a:ext cx="(\d+)" cy="(\d+)"\/>/);
      if (!off || !ext) continue;
      const x = +off[1], y = +off[2], w = +ext[1], h = +ext[2], bottom = y + h;
      if (isContent && !/<p:ph\b/.test(blk) && y < footerEMU - 300000 && bottom > limit + 150000)
        overflow.push({ slide: si, bottomPx: Math.round(bottom / CYm * 1080) });
      const adj = blk.match(/prst="roundRect"[\s\S]{0,80}?<a:gd name="adj" fmla="val (\d+)"/);
      if (adj) {
        const frac = +adj[1] / 100000;          // доля короткой стороны
        const minPx = Math.min(w, h) / CYm * 1080;
        if (frac < 0.40 && minPx > 250)         // пилюли (~0.5) и мелкие внутренние плашки — мимо
          cardRadii.push(Math.round(frac * Math.min(w, h) / CYm * 1080));
      }
      // — КАРТОЧКА БЕЗ СКРУГЛЕНИЯ (Правило 55): крупный ЗАЛИВНОЙ контейнер-
      //   прямоугольник с острыми углами. Это и есть дыра старого card_radius:
      //   он проверял КОНСИСТЕНТНОСТЬ существующих roundRect, но НЕ ловил
      //   «скругления нет вовсе» (roundRect=0 ⇒ вакуумный pass).
      if (m[1] === 'sp') {
        const spPr = (blk.match(/<p:spPr>[\s\S]*?<\/p:spPr>/) || [''])[0];
        const fillM = spPr.match(/<a:solidFill>\s*<a:srgbClr val="([0-9A-Fa-f]{6})"/);
        const wPx = w / CYm * 1080, hPx = h / CYm * 1080;
        const fullBleed = x <= 0.02 * 24382800 && y <= 0.02 * CYm && w >= 0.96 * 24382800 && h >= 0.96 * CYm;
        if (fillM && !fullBleed && wPx >= 200 && hPx >= 80) {   // карточка-контейнер (не линия/чип)
          if (!/prst="roundRect"/.test(spPr))
            sharpCards.push({ slide: si, wPx: Math.round(wPx), hPx: Math.round(hPx) });
          const hex = fillM[1].toUpperCase();
          // красная карточка, но не фирменный красный (R»G,B и вне допуска)
          const r = parseInt(hex.slice(0,2),16), g = parseInt(hex.slice(2,4),16), b = parseInt(hex.slice(4,6),16);
          if (r > 200 && g < 120 && b < 120 && !isBrandRed(hex)) offRed.push({ slide: si, hex: '#' + hex });
        }
      }
    }
  }
  const bottom_safe = overflow.length === 0;
  // Правило 55: радиус контентной карточки — каноничные ≈45px (1,6 см) на 1920×1080, ±6px
  const uniq = [...new Set(cardRadii)].sort((a, b) => a - b);
  const card_radius = cardRadii.every(r => r >= 39 && r <= 51);
  const cards_rounded = sharpCards.length === 0;                  // Правило 55 (скругление есть вообще)
  const title_clean = !titleAgenda;                               // агенда не на титуле (Правило 11)
  const single_sentence_no_period = periodViol.length === 0;      // Правило 51
  const accent_red_brand = offRed.length === 0;                   // красный только #F66048 (Правило 10/14)
  return { bottom_safe, card_radius, cards_rounded, title_clean, single_sentence_no_period, accent_red_brand,
    details: { bottomLimitPx: Math.round(limit / CYm * 1080), overflow, cardRadiiPx: uniq, canonicalPx: 45,
      sharpCards, periodViol: periodViol.slice(0, 8), offRed } };
}

/**
 * assertDesignDiscipline({ JSZip, bytes }) — гейт дисциплины вёрстки для деки,
 * которую собрал агент. ok:false ⇒ почини источник (нижняя граница / единый
 * радиус карточек) и пересобери, потом отдавай. Возвращает { ok, checks, failed }.
 */
async function assertDesignDiscipline({ JSZip, bytes }) {
  const u8 = bytes instanceof Uint8Array ? bytes
    : (bytes.arrayBuffer ? new Uint8Array(await bytes.arrayBuffer()) : bytes);
  const zip = await JSZip.loadAsync(u8);
  const checks = await checkDesignDiscipline(zip);
  const failed = ['bottom_safe', 'card_radius', 'cards_rounded', 'title_clean',
    'single_sentence_no_period', 'accent_red_brand'].filter(k => !checks[k]);
  return { ok: failed.length === 0, checks, failed };
}

// доступно и как глобал, и как экспорт модуля
if (typeof window !== 'undefined') { window.finalizePptx = finalizePptx; window.assertBrandPptx = assertBrandPptx; window.assertDesignDiscipline = assertDesignDiscipline; window.checkDesignDiscipline = checkDesignDiscipline; }
if (typeof module !== 'undefined') module.exports = { finalizePptx, assertBrandPptx, checkBrand, checkDesignDiscipline, assertDesignDiscipline };
