/**
 * export-deck — ДЕТЕРМИНИРОВАННЫЙ мост «свёрстанная дека → фирменный PPTX».
 *
 * Проблема, которую он решает: до него ассистент собирал `slidesMeta`/`layoutByIndex`
 * вручную (какой текст в какой плейсхолдер, какой слайд на каком макете) — и ошибался
 * (плейсхолдеры разъезжались, слайды пустели). Здесь сопоставление берётся НЕ из головы
 * ассистента, а из САМОЙ РАЗМЕТКИ деки: каждый слайд несёт `data-layout`, каждый элемент
 * чроме — `data-ph`. Хелпер читает их и собирает мету сам. Тело слайда (графики,
 * карточки, таймлайны) НЕ трогается — оно захватывается gen_pptx как нативные объекты,
 * поэтому пустых слайдов не бывает, а чроме садится в плейсхолдеры по маркеру, а не по
 * эвристике, поэтому ничего не разъезжается.
 *
 * Контракт разметки (кладётся в деку ПРИ СБОРКЕ; в шаблоне уже проставлен):
 *   <section data-layout="title|content|section|thesis|stat|heading|heading96|
 *                          blank|contents|cards2|cards3|photo|mockup|final"> … </section>
 *   внутри — элементы чроме:
 *     data-ph="title"     — заголовок (любого размера; кегль наследуется из макета)
 *     data-ph="subtitle"  — подзаголовок            → body#11
 *     data-ph="note"      — примечание-колонтитул   → body#10
 *     data-ph="num"       — номер слайда            → sldNum#4 (авто-поле)
 *     data-ph="name"      — имя (титул/финал)        → body#12
 *     data-ph="role"      — должность (титул/финал)  → body#13
 *   Тело (всё остальное) маркеров НЕ несёт — едет нативными объектами.
 *
 * Использование (внутри run_script; finalize-pptx.js уже загружен):
 *   eval(await readFile('<ds>/templates/business-pptx/export-deck.js'));
 *   const html = await readFile('<путь к деке>.html');         // исходная разметка
 *   const { layoutByIndex, slidesMeta } = buildExportMeta(html);
 *   const out = await finalizePptx({ JSZip, templateBytes, rawBytes, slidesMeta, layoutByIndex });
 *   // далее assertBrandPptx → save → present (как обычно)
 *
 * Деградация: если в деке нет маркеров (legacy-драфт), buildExportMeta вернёт пустые
 * layoutByIndex/slidesMeta — finalize отработает на эвристиках (авто-заголовок,
 * авто-раскладка тезиса). Маркеры лишь делают результат ТОЧНЫМ и предсказуемым.
 */
(function (root) {
  // data-layout → файл макета шаблона ПСиИИ
  const LAYOUT = {
    title:    'slideLayout1.xml',   // КРАСНЫЙ титул (220pt + имя/должность)
    content:  'slideLayout6.xml',   // белый, заголовок 72 + подзаголовок
    section:  'slideLayout3.xml',   // КРАСНЫЙ раздел-перебивка (короткий заголовок)
    thesis:   'slideLayout11.xml',  // КРАСНЫЙ тезис (фраза)
    stat:     'slideLayout10.xml',  // белый «Цифра»
    heading:  'slideLayout5.xml',   // белый, заголовок 72
    heading96:'slideLayout4.xml',   // белый, заголовок 96
    blank:    'slideLayout9.xml',   // пустой (без title)
    contents: 'slideLayout2.xml',   // содержание
    cards2:   'slideLayout14.xml',
    cards3:   'slideLayout13.xml',
    photo:    'slideLayout17.xml',
    mockup:   'slideLayout16.xml',
    final:    'slideLayout18.xml',  // СЕРЫЙ финал (220pt + имя/должность)
  };
  // data-ph → плейсхолдер макета
  const PH = {
    title:    { ph: 'title' },                       // без idx; кегль/цвет из макета
    subtitle: { ph: 'body', idx: 11 },
    note:     { ph: 'body', idx: 10 },
    num:      { ph: 'sldNum', idx: 4, field: true }, // авто-поле slidenum
    name:     { ph: 'body', idx: 12 },
    role:     { ph: 'body', idx: 13 },
  };

  function textOf(el) {
    // <br> → перенос строки; схлопываем пробелы; &nbsp; нормализует finalize по match
    const html = el.innerHTML.replace(/<br\s*\/?>/gi, '\n');
    const tmp = el.ownerDocument.createElement('div');
    tmp.innerHTML = html;
    return (tmp.textContent || '').replace(/[ \t]+/g, ' ').replace(/\s*\n\s*/g, '\n').trim();
  }

  function buildExportMeta(html) {
    if (typeof DOMParser === 'undefined')
      throw new Error('buildExportMeta: нужен DOMParser (запускай в run_script/браузере).');
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const sections = Array.from(doc.querySelectorAll('[data-layout]'));
    const layoutByIndex = {};
    const slidesMeta = [];
    sections.forEach((sec, i) => {
      const lay = LAYOUT[(sec.getAttribute('data-layout') || '').trim()];
      if (lay) layoutByIndex[i + 1] = lay;
      const placeholders = [];
      sec.querySelectorAll('[data-ph]').forEach((el) => {
        const spec = PH[(el.getAttribute('data-ph') || '').trim()];
        if (!spec) return;
        const text = textOf(el);
        if (!text) return;
        const lines = text.split('\n');
        if (spec.field) placeholders.push(Object.assign({}, spec, { match: [text] }));
        else placeholders.push(Object.assign({}, spec, { lines, match: [text] }));
      });
      slidesMeta.push(placeholders.length ? { placeholders } : null);
    });
    return { layoutByIndex, slidesMeta, slideCount: sections.length };
  }

  root.buildExportMeta = buildExportMeta;
  if (typeof module !== 'undefined') module.exports = { buildExportMeta };
})(typeof window !== 'undefined' ? window : globalThis);
