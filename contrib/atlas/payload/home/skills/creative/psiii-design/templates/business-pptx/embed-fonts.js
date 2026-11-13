/**
 * embed-fonts — вшивает шрифты YS в .pptx, чтобы дека выглядела фирменно у ЛЮБОГО
 * пользователя, а не только на машине с установленными шрифтами Яндекса.
 *
 * ЗАЧЕМ. YS Display Cond / YS Text — проприетарные шрифты. Если файл лишь ССЫЛАЕТСЯ
 * на них (typeface="YS …"), но не несёт их байты внутри пакета, то у внешнего/
 * публичного пользователя PowerPoint подставляет Calibri: тяжёлые узкие заголовки
 * становятся обычными, кегли и сетка плывут, фирменность исчезает. Все фирменные
 * гейты при этом проходят (они проверяют XML-ссылки, а не наличие байтов шрифта) —
 * поэтому баг невидим изнутри Яндекса и доезжает до публичного пользователя.
 * Лечится только встраиванием шрифтов в сам файл (Правило 87).
 *
 * ЧТО ДЕЛАЕТ. Кладёт TTF как части /ppt/fonts/fontN.fntdata, регистрирует
 * Default content-type для fntdata, добавляет relationships в
 * ppt/_rels/presentation.xml.rels, вставляет <p:embeddedFontLst> в presentation.xml
 * и ставит embedTrueTypeFonts="1" + saveSubsetFonts="0" на <p:presentation>.
 * Идемпотентно: если шрифты уже вшиты — ничего не делает.
 *
 * Базовый путь — запечь шрифты прямо в source.pptx: тогда КАЖДЫЙ путь сборки
 * (buildBrandPptx / buildBrandDeck / finalizePptx / rebrandPptxInPlace) наследует
 * вшитые шрифты бесплатно, потому что все они стартуют из этого шаблона.
 *
 * Использование (внутри run_script, JSZip подгружен):
 *   eval(await readFile('<ds>/templates/business-pptx/embed-fonts.js'));
 *   const zip = await JSZip.loadAsync(await readFileBinary('<ds>/templates/business-pptx/source.pptx'));
 *   const ld = async f => { const b = await readFileBinary('<ds>/assets/fonts/'+f); return b instanceof Uint8Array ? b : new Uint8Array(await b.arrayBuffer()); };
 *   await embedFonts({ JSZip, zip, loadFont: ld });   // мутирует zip на месте
 *   const out = await zip.generateAsync({ type:'blob', compression:'DEFLATE' });
 *
 * loadFont(filename) → Promise<Uint8Array> — отдаёт байты TTF по имени файла из assets/fonts.
 */

// Карта фирменных шрифтов: имя гарнитуры (как оно встречается в typeface="…")
// → файл(ы) TTF по начертаниям. Имя ОБЯЗАНО точно совпадать с тем, что стоит в
// ранах/теме, иначе PowerPoint не подхватит вшитый шрифт. Перечислены все имена,
// что реально встречаются в source.pptx и в собранных деках (включая "YS Text",
// которым генераторы помечают раны тела).
const PSIII_FONT_MAP = [
  { name: 'YS Display Cond Heavy',           regular: 'YSDisplayCond-Heavy.ttf' },
  { name: 'YS Display Cond Heavy Condensed', regular: 'YSDisplayCond-Heavy.ttf' },
  { name: 'YS Text',                         regular: 'YSText-Regular.ttf', bold: 'YSText-Bold.ttf' },
  { name: 'YS Text Regular',                 regular: 'YSText-Regular.ttf' },
  { name: 'YS Text Medium',                  regular: 'YSText-Medium.ttf' },
  { name: 'YS Text Light',                   regular: 'YSText-Light.ttf' },
  { name: 'YS Text Bold',                    regular: 'YSText-Bold.ttf' },
];

async function embedFonts({ JSZip, zip, loadFont, fontMap }) {
  const map = fontMap || PSIII_FONT_MAP;

  let pres = await zip.file('ppt/presentation.xml').async('string');
  // идемпотентность: уже вшито — выходим
  if (/<p:embeddedFontLst>/.test(pres)) return { embedded: 0, skipped: true };

  // 1. собрать уникальные TTF (дедуп по имени файла) → fontN.fntdata
  const fileToPart = {};       // 'YSText-Regular.ttf' -> 'font1.fntdata'
  let fontN = 0;
  const ensurePart = async (file) => {
    if (fileToPart[file]) return fileToPart[file];
    const bytes = await loadFont(file);
    const part = 'font' + (++fontN) + '.fntdata';
    zip.file('ppt/fonts/' + part, bytes);
    fileToPart[file] = part;
    return part;
  };

  // 2. для каждой гарнитуры — relationship на каждое начертание; собрать embeddedFontLst
  let prels = await zip.file('ppt/_rels/presentation.xml.rels').async('string');
  // найти максимальный существующий rId, чтобы не пересечься
  let maxId = 0;
  for (const m of prels.matchAll(/Id="rId(\d+)"/g)) maxId = Math.max(maxId, +m[1]);
  const FONT_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/font';
  let newRels = '';
  let lst = '<p:embeddedFontLst>';
  const SLOTS = ['regular', 'bold', 'italic', 'boldItalic'];
  for (const fam of map) {
    let entry = '';
    for (const slot of SLOTS) {
      if (!fam[slot]) continue;
      const part = await ensurePart(fam[slot]);
      const rid = 'rId' + (++maxId);
      newRels += `<Relationship Id="${rid}" Type="${FONT_REL}" Target="fonts/${part}"/>`;
      entry += `<p:${slot} r:id="${rid}"/>`;
    }
    if (!entry) continue;
    const tf = fam.name.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
    lst += `<p:embeddedFont><p:font typeface="${tf}"/>${entry}</p:embeddedFont>`;
  }
  lst += '</p:embeddedFontLst>';

  prels = prels.replace('</Relationships>', newRels + '</Relationships>');
  zip.file('ppt/_rels/presentation.xml.rels', prels);

  // 3. content-type для fntdata (Default, не Override)
  let ct = await zip.file('[Content_Types].xml').async('string');
  if (!/Extension="fntdata"/.test(ct)) {
    ct = ct.replace('</Types>',
      '<Default Extension="fntdata" ContentType="application/x-fontdata"/></Types>');
    zip.file('[Content_Types].xml', ct);
  }

  // 4. presentation.xml: атрибут встраивания + вставка embeddedFontLst в правильное
  //    место по схеме CT_Presentation (после notesSz / sldSz, до defaultTextStyle/extLst)
  if (/embedTrueTypeFonts=/.test(pres))
    pres = pres.replace(/embedTrueTypeFonts="[^"]*"/, 'embedTrueTypeFonts="1"');
  else
    pres = pres.replace(/<p:presentation\b([^>]*?)(\/?)>/,
      (m, attrs, sl) => `<p:presentation${attrs} embedTrueTypeFonts="1" saveSubsetFonts="0"${sl}>`);
  if (!/saveSubsetFonts=/.test(pres))
    pres = pres.replace(/embedTrueTypeFonts="1"/, 'embedTrueTypeFonts="1" saveSubsetFonts="0"');

  if (/<p:notesSz\b[^>]*\/>/.test(pres))
    pres = pres.replace(/(<p:notesSz\b[^>]*\/>)/, '$1' + lst);
  else if (/<p:sldSz\b[^>]*\/>/.test(pres))
    pres = pres.replace(/(<p:sldSz\b[^>]*\/>)/, '$1' + lst);
  else if (/<p:defaultTextStyle>/.test(pres))
    pres = pres.replace('<p:defaultTextStyle>', lst + '<p:defaultTextStyle>');
  else if (/<p:extLst>/.test(pres))
    pres = pres.replace('<p:extLst>', lst + '<p:extLst>');
  else
    pres = pres.replace('</p:presentation>', lst + '</p:presentation>');
  zip.file('ppt/presentation.xml', pres);

  return { embedded: fontN, families: map.length };
}

if (typeof window !== 'undefined') { window.embedFonts = embedFonts; window.PSIII_FONT_MAP = PSIII_FONT_MAP; }
if (typeof module !== 'undefined') module.exports = { embedFonts, PSIII_FONT_MAP };
