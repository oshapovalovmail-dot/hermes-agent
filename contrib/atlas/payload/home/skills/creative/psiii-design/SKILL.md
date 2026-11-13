---
name: psiii-design
description: Use when generating branded interfaces, HTML artifacts, mockups, decks,
  or editable PPTX exports for ПСиИИ (Яндекс · Поисковые сервисы и ИИ). Enforces the
  ПСиИИ design system, mandatory PPTX finalization gates, brand template usage, UI
  kit, icons, colors, typography, and export verification.
version: 1.0.0
author: Hermes Agent
license: MIT
platforms:
- macos
- linux
metadata:
  hermes:
    tags:
    - design-system
    - presentations
    - pptx
    - yandex
    - psiii
    - branding
    related_skills:
    - powerpoint
    - pptx-author
    - sketch
    - popular-web-designs
    visibility: global
    aliases: []
user-invocable: true
---
> ⛔ **СТОП-ГЕЙТ ЭКСПОРТА. Прочитай до того, как отдашь любой PPTX.**
> Если пользователь просит презентацию/слайды/PPTX или экспорт — это ВСЕГДА
> означает полный конвейер в одном ходе:
>
> 1. `gen_pptx` с **`save_to_project_path: 'export/_raw.pptx'`** — НИКОГДА без него.
>    Без `save_to_project_path` инструмент СКАЧИВАЕТ сырой файл пользователю — это и
>    есть ошибка «отдал сразу неправильный». С `save_to_project_path` сырой файл
>    уходит в проект (не к пользователю), под финализацию.
> 2. `finalizePptx({ templateBytes: source.pptx, rawBytes: export/_raw.pptx })`.
> 3. `assertBrandPptx` → только при `ok:true`.
> 4. `saveFile('export/deck.pptx')` и **отдать файл карточкой на скачивание в чат**
>    (`present_fs_item_for_download`), под ASCII-именем — не скачиванием напрямую.
>
> **Правило: любой экспорт сначала проходит гейт, и файл не скачивается, а
> формируется и отдаётся карточкой в чат — для всех, включая публичного
> пользователя** (Правило 86 в `guidelines/rules.md`).
>
> **Сырой результат `gen_pptx` отдавать/скачивать/показывать пользователю
> запрещено** — он нефирменный (13,33″, тема Office, без направляющих, 1 макет,
> финал красный, заголовок не тот). `gen_pptx` без `save_to_project_path`, `gen_pptx`
> как последний шаг, download сырого файла, `present_fs_item_for_download` на
> `export/_raw.pptx` — всё это нарушение гейта. Между шагом 1 и шагом 4 не завершай
> ход. Готовый код шагов 2–4 — `templates/business-pptx/finalize-pptx.js` (сниппет
> ниже). Это не опция — без `assertBrandPptx({ok:true})` файл не выдаётся.
>
> **Дека, которую собрал агент, проходит ВТОРОЙ гейт — дисциплину вёрстки.**
> `assertBrandPptx` проверяет фирменную оболочку, но не вёрстку. Для собранной агентом
> деки добавь `assertDesignDiscipline({ JSZip, bytes })` (тот же `finalize-pptx.js`),
> 6 инвариантов вёрстки: `bottom_safe` (Правило 6), `card_radius` + `cards_rounded`
> (Правило 55 — крупные карточки скруглены на ≈45px, не острым `rect`), `title_clean`
> (Правило 11 — агенда не на титуле), `single_sentence_no_period` (Правило 51),
> `accent_red_brand` (Правило 10/14 — красный только `#F66048`). `ok:false` ⇒ почини
> источник и пересобери. На восстановлении
> чужого raw-файла как hard-gate не применяй — но нарушения покажи пользователю.
>
> **Особый случай — кнопка Share → Export → PowerPoint (Editable).** Она НЕ
> конвертирует и НЕ скачивает файл сама: нажатие присылает тебе, ассистенту, запрос на экспорт вместе с
> типовым скиллом «Editable PPTX Export», чей шаг 3 — «вызови `gen_pptx` (он сам
> скачает файл)». В ПСиИИ-проекте этот шаг ПЕРЕОПРЕДЕЛЯЕТСЯ гейтом выше: вызывай
> `gen_pptx` **с `save_to_project_path: 'export/_raw.pptx'`** (не давай ему скачивать),
> затем шаги 2–4, и **выложи готовый фирменный файл в чат карточкой на скачивание**
> (`present_fs_item_for_download` на `export/deck.pptx`). Так привычный путь
> пользователя сохраняется — «нажал кнопку → получил файл», — но файл фирменный.
> Типовой скилл даёт механику захвата (selector/showJs/resetTransformSelector/шрифты)
> — бери её, но НИКОГДА не отдавай его сырой результат и не давай `gen_pptx` скачать
> файл напрямую. «Скачать сразу из `gen_pptx`» — ровно тот баг, из-за которого
> публичный пользователь получает нефирменный файл (13,33″, тема Office, 1 макет,
> красный финал).

Read the `readme.md` file within this skill, and explore the other available files.

> 📦 **Результат деки = фирменный `.pptx`, который собрал АССИСТЕНТ.** Когда строишь
> презентацию в проекте-потребителе, твоя работа не заканчивается на HTML-превью:
> проактивно выдай пользователю готовый редактируемый `.pptx` в фирменном шаблоне
> (через `buildBrandPptx` — путь по умолчанию, либо `gen_pptx`→`finalizePptx` для уже
> свёрстанной HTML-деки) и отдай его на скачивание. Это и есть «правильный шаблон для
> дальнейшей самостоятельной работы».
> **Кнопка Share → Export → PowerPoint — не путь.** Она конвертирует HTML мимо
> шаблона (13,33″, тема Office, 1 макет, красный финал) и не проходит фирменную
> проверку. Если пользователь спрашивает про экспорт или Share→Export — объясни, что
> фирменный файл собирает ассистент, и собери его сам. Никогда не предлагай кнопку
> Share→Export как способ получить фирменную деку.

This is a **presentation design system** for the Yandex *Search Services & AI*
business group (ПСиИИ). The look is minimalist: white canvas, ink-on-white type,
one hot Yandex-red accent (`#F66048`), YS Display Cond Heavy titles + YS Text body,
a strict grid, sharp corners.

**The presentation base is the original PowerPoint file** —
`templates/business-pptx/source.pptx`, included unchanged (18 named layouts, brand
theme, 116 modern guides, 67,73 × 38,1 cm). Build decks **directly in that PPTX**
(duplicate its ready layouts, fill in text/numbers); never recreate it from scratch —
that keeps fonts, grid and colors identical to the template. The `.pptx` is a zip of
XML, so it can be edited programmatically (swap `<a:t>` text, clone slides) and
repackaged into a working PowerPoint file.

## ✅ Железобетонный путь (рекомендуется): сборка прямо в шаблоне

> **WYSIWYG-путь: `buildBrandDeck` — один спец → и .pptx, и HTML-превью, идентичные.**
> `templates/business-pptx/build-deck.js` (`buildBrandDeck({ JSZip, templateBytes,
> slides, assetsBase })`) возвращает `{ pptx, html }`: собирает файл через
> `buildBrandPptx`, затем рендерит HTML-превью **из того же .pptx** (фон + декор +
> геометрия макета каждого слайда + текст плейсхолдеров). Превью и выгрузка берутся из
> **одного источника** (`slides`) и совпадают **по построению** — нет второго рендера и
> нет `gen_pptx`, расходиться нечему. Карточки/подложки берут форму и **единый радиус**
> из макета, фон/шрифт/кегль/цвет — тоже из макета, поэтому правила (включая нижнюю
> границу и радиус карточек) соблюдаются автоматически. Это **рекомендованный путь для
> публичного пользователя**, когда нужно, чтобы «то, что вижу в превью» и «что в файле»
> были одинаковыми. `assetsBase` — путь к корню ДС от места сохранения превью
> (в потребителе `_ds/<папка>` или `../_ds/<папка>`; шрифты тянутся из `tokens/fonts.css`).
> Гоняй на результате оба гейта: `assertBrandPptx(pptx)` + `assertDesignDiscipline(pptx)`.
> После XML-гейтов сделай визуальный smoke-check хотя бы обложки: на macOS можно
> `qlmanage -t -s 1600 -o <qa_dir> export/deck.pptx`, затем проверить thumbnail на
> обрезанный заголовок, наложения, неправильный фон, пропавший логотип или фантомный
> квадрат. Отдельно проверь нижние `name`/`role` строки на титуле/финале: длинные
> подписи в этих плейсхолдерах легко накладываются друг на друга, хотя XML-гейты
> проходят; держи их короткими, длинный framing выноси на отдельный тезисный слайд.
> Гейты ловят инварианты файла, но не все renderer-артефакты — не отдавай
> деку, пока видимый дефект не убран. Локальный Node-паттерн, footer-overlap и logo
> pitfall см. `references/pptx-local-build-and-visual-qa.md`.
> Тело слайда выражается типами `slides[]` (title/section/content/stat/cards/contents/
> thesis/heading/final/blank/photo/mockup) — для произвольной свободной вёрстки см.
> HTML-путь ниже.

**Самый надёжный экспорт — вообще не использовать `gen_pptx`/кнопку.** Собирай деку
из текстового описания прямо в `source.pptx` через
`templates/business-pptx/build-pptx.js` (`buildBrandPptx`): текст ложится в готовые
плейсхолдеры фирменных макетов, размер/тема/шрифты/18 макетов/направляющие
наследуются из шаблона. Фирменность гарантирована **по построению** — нет сырого
файла, который мог бы «утечь» к пользователю, и не от чего зависеть (ни от агента,
ни от кнопки Share→Export).

**Путь по умолчанию для деки — `buildBrandDeck` (build-deck.js).** Он оборачивает
`buildBrandPptx` и из ОДНОГО спека `slides[]` отдаёт `{ pptx, html }`: фирменный файл
**и** HTML-превью, отрисованное из того же .pptx. Превью и выгрузка идентичны по
построению (один источник, один рендер, без `gen_pptx`) — это и есть «превью = файл»
для публичного пользователя. Простой `buildBrandPptx` используй, только если превью не
нужно.

```
// внутри run_script
const s=document.createElement('script');
s.src='https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js';
await new Promise((r,j)=>{s.onload=r;s.onerror=j;document.head.appendChild(s);});
eval(await readFile('<ds>/templates/business-pptx/finalize-pptx.js')); // checkBrand/assertBrandPptx/assertDesignDiscipline
eval(await readFile('<ds>/templates/business-pptx/build-pptx.js'));    // buildBrandPptx
eval(await readFile('<ds>/templates/business-pptx/build-deck.js'));    // buildBrandDeck
const slides = [
  { type:'title',   title:'Заголовок', name:'Имя Фамилия', role:'Должность' },
  { type:'section', title:'Раздел', kicker:'01' },
  { type:'content', title:'Заголовок слайда', subtitle:'Подзаголовок', note:'Примечание' },
  { type:'stat',    title:'86%', caption:'что за цифра' },
  { type:'cards3',  title:'Три пункта', cards:[{title:'A',text:'…'},{title:'B',text:'…'},{title:'C',text:'…'}] },
  { type:'final',   title:'Спасибо', name:'Имя Фамилия', role:'Должность' },
];
const { pptx, html } = await buildBrandDeck({
  JSZip,
  templateBytes: await readFileBinary('<ds>/templates/business-pptx/source.pptx'),
  slides,
  assetsBase: '<ds>',              // путь к корню ДС от места сохранения превью (потребитель: '_ds/<папка>')
});
// ДВА гейта перед выдачей:
const bytes = new Uint8Array(await pptx.arrayBuffer());
const v1 = await assertBrandPptx({ JSZip, bytes });            // фирменная оболочка
const v2 = await assertDesignDiscipline({ JSZip, bytes });    // вёрстка (нижняя граница, радиус карточек)
if (!v1.ok || !v2.ok) throw new Error('гейт: ' + [...v1.failed, ...v2.failed].join(', '));
await saveFile('export/deck.pptx', pptx);     // выгрузка — отдаём пользователю
await saveFile('decks/preview.html', html);   // превью — то же самое визуально
```

Типы слайдов и поля — в шапке `build-pptx.js`: `title`/`final` (красный/серый,
title+name+role), `section`/`thesis` (красный), `content`/`heading`/`heading96`/`stat`/
`cards2`/`cards3`/`contents`/`blank` (белые), `photo`/`mockup` (белые, с картинкой).
Картинка: `image:{ data, ext }`, где `data` = `await readFileBinary('uploads/…')`
(Uint8Array/Blob), `ext` = `'png'|'jpeg'|'webp'` — фото наследует позицию и
скруглённую рамку из макета. Любой слайд можно задать сырьём:
`{ layout:'slideLayout7.xml', placeholders:[{ph:'title',lines:['…']}], pics:[{idx,image}] }`.

## 📥 Пользователь принёс готовый .pptx и просит «привести к дизайн-системе»

Это ОТДЕЛЬНЫЙ путь — **рестайл темы НА МЕСТЕ**, не пересборка. Контент чужой деки
неприкосновенен (Правила 23/83/84): слайды, текст, картинки, кастомные макеты НЕ
трогаем — меняем только оболочку темы (цвета+шрифты+размер+направляющие).

```
// внутри run_script (JSZip загружен как в примерах выше)
eval(await readFile('<ds>/templates/business-pptx/rebrand-pptx.js'));
const draftBytes = await readFileBinary('uploads/<draft-ASCII>.pptx'); // ASCII-имя! Правило 85
const out = await rebrandPptxInPlace({
  JSZip,
  templateBytes: await readFileBinary('<ds>/templates/business-pptx/source.pptx'),
  draftBytes,
});
const v = await assertIngestRebrand({ JSZip, bytes: out, draftBytes });
if (!v.ok) throw new Error('рестайл не прошёл: ' + v.failed.join(', ')); // media_content_preserved/media_preserved/slides_preserved = контент потерян
await saveFile('export/deck.pptx', out); // отдать карточкой в чат, Правило 86
```

⛔ **НЕ гони ингест-деку через `gen_pptx`/`finalizePptx`/`buildBrandPptx`** — они
пересобирают деку на наших 18 макетах и роняют картинки (реальный инцидент: из 135
картинок осталось 7, плюс сырой 13,33″/Office). Гейт ингеста — `assertIngestRebrand`
(сверяет сохранность слайдов/картинок с драфтом), НЕ `assertBrandPptx`. Подробности —
Правило 84.

## ⚠ Запасной путь — экспорт HTML-деки (`gen_pptx` → finalize)

Если дека уже свёрстана в HTML и проще её захватить, чем переписывать в `slides[]`:
**сырой экспорт ВСЕГДА нефирменный и никогда не отдаётся пользователю.**
Генераторы PPTX (`gen_pptx` и т.п.) выдают файл с дефолтным размером (13,33″),
без направляющих, с темой «Office» и с одним макетом вместо 18 — именно так
«слетают» сетка, размер, цвета и макеты, а финал получается красным.
**Шаг 1 — обязательно зови `gen_pptx` с `save_to_project_path`** (иначе сырой файл
скачается пользователю). **Шаг 2 — прогони сырой файл через `finalize-pptx.js`**
и проверь `assertBrandPptx`. Без этого файл нельзя отдавать и с ним нельзя
работать дальше.

`finalizePptx` **сам проверяет свой результат** и бросает ошибку, если хоть один из 15
инвариантов (размер, направляющие в presentation и мастере, 18 макетов, тема
`F2F2F2`/`F66048`, шрифты YS, заголовки в плейсхолдерах и без зашитого шрифта,
без зашитого фона слайда, логотип только на титуле и финале, титул на КРАСНОМ
макете, финал на СЕРОМ макете, заголовок не потерян на макете без title,
шрифты YS вшиты в файл)
нарушен — «слетевший» файл физически не выйдет из функции.
Если функция бросила ошибку — почти всегда `templateBytes` указан не на
`source.pptx`, а на сырой экспорт.

```
// ШАГ 1 — экспорт В ПРОЕКТ, не пользователю. Дека должна быть открыта в превью
// (show_to_user). Вызови инструмент gen_pptx С ПАРАМЕТРОМ save_to_project_path:
//   gen_pptx({ ..., save_to_project_path: 'export/_raw.pptx' })
// Без save_to_project_path gen_pptx СКАЧАЕТ сырой нефирменный файл пользователю —
// это запрещено. Файл export/_raw.pptx — временный, пользователю его не отдаём.

// ШАГИ 2–4 — внутри run_script:
const s=document.createElement('script');
s.src='https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js';
await new Promise((r,j)=>{s.onload=r;s.onerror=j;document.head.appendChild(s);});
eval(await readFile('<ds>/templates/business-pptx/finalize-pptx.js')); // finalizePptx + assertBrandPptx
eval(await readFile('<ds>/templates/business-pptx/export-deck.js'));    // buildExportMeta
// ДЕТЕРМИНИРОВАННЫЙ ПУТЬ. Разметка деки сама несёт сопоставление: каждый <section>
// помечен data-layout, каждый элемент чроме — data-ph (title/subtitle/note/num/
// name/role). buildExportMeta читает их и собирает layoutByIndex + slidesMeta САМ —
// ассистент НИЧЕГО не сопоставляет руками. Именно ручное сопоставление давало
// «пустые слайды» (buildBrandPptx не вмещал тело) и «разъехавшиеся плейсхолдеры»
// (опечатка в индексе/тексте). Тело (графики, карточки) едет нативными объектами
// из gen_pptx — поэтому пустых слайдов не бывает.
//
// Дека ОБЯЗАНА нести маркеры. Шаблоны ПСиИИ (`templates/<slug>/…dc.html`) их уже
// несут — потребитель стартует из шаблона и наследует их бесплатно. Если строишь
// деку-драфт с нуля — проставь их при сборке (data-layout на секции, data-ph на
// заголовок/подзаголовок/примечание/номер/имя/должность).
//
// run_script.readFile НЕ читает пути с кириллицей/пробелами — если имя деки такое,
// сначала copy_files в ASCII-имя (напр. decks/_export-src.html) и читай его.
const html = await readFile('<путь к деке, ASCII>.html');
const { layoutByIndex, slidesMeta } = buildExportMeta(html);
const out = await finalizePptx({
  JSZip,
  templateBytes: await readFileBinary('<ds>/templates/business-pptx/source.pptx'),
  rawBytes:      await readFileBinary('export/_raw.pptx'), // сырой файл из шага 1
  slidesMeta, layoutByIndex,
});
// Жёсткий гейт: не сохраняем и не отдаём, пока не прошла проверка.
const v = await assertBrandPptx({ JSZip, bytes: out });
if (!v.ok) throw new Error('Нефирменный PPTX: ' + v.failed.join(', '));
await saveFile('export/deck.pptx', out);
// ШАГ 4 — пользователю отдаём ТОЛЬКО export/deck.pptx (present_fs_item_for_download),
// никогда export/_raw.pptx.
```

Проверка `assertBrandPptx` возвращает `{ ok, checks, failed }` по 15 инвариантам:
`size`, `guides_pres`, `guides_master`, `layouts18`, `theme_red`, `theme_fonts`,
`theme_name`, `titles_in_ph`, `title_font`, `no_slide_bg`, `logo_scope`,
`title_slide_red` (титул на красном макете), `final_slide_gray` (финал на СЕРОМ
макете, не красном), `headings_have_layout` (заголовок не «потерян» на макете
без title), `fonts_embedded` (шрифты YS вшиты в файл — Правило 89; без этого у
публичного пользователя PowerPoint подставит Calibri). `ok:false` — файл отдавать нельзя, нужно (пере)финализировать. Эту же
проверку прогоняй на ЛЮБОМ уже готовом .pptx (даже чужом) — если `ok:false`,
прогони его через `finalizePptx` (как `rawBytes`), чтобы восстановить фирменность.

### Рекомендованный подход к вёрстке (Правила 47–49): чроме — в плейсхолдеры, тело — свободное

Лучший результат для редактирования — когда служебные элементы лежат в **родных
плейсхолдерах** шаблона, а контент свободен. Как это делать:
- Верстай деку в HTML на канвасе 1920×1080. Для **чроме** (заголовок, подзаголовок,
  примечание, номер, имя/должность) используй классы-зеркало
  `templates/business-pptx/ps-placeholders.css` — точные позиции/кегли/цвета
  плейсхолдеров шаблона (`1pt = 1px`). Тогда **превью совпадает с выгрузкой** (WYSIWYG).
- **Тело** (таблицы, графики, бар-чарты, карточки) верстай свободно по правилам
  (поля 115px, воздух, фирменные цвета/шрифты, интерлиньяж по Правилу 16).
- На выгрузке передавай в `finalizePptx` **`slidesMeta`** — по плейсхолдеру на каждый
  элемент чроме (`{ph, idx?, lines, match}`): `finalize` удалит захваченные свободные
  боксы (по `match`) и создаст вместо них настоящие `<p:ph>`, наследующие формат
  макета; тело останется нативными объектами. Базовый макет слайда задавай через
  `layoutByIndex`, выбирая «чистый» заголовочный по Правилу 49 (96/72/60/40 →
  `slideLayout4/5/7/8`) или `slideLayout6` (с подзаголовком).
- Размер крупного заголовка титула/финала — по Правилу 47 (220→180→140→120 по длине;
  пинуется через `slidesMeta`→`sz`, шрифт/цвет наследуются).

Подробности и таблицы размеров — Правила 47, 48, 49 в `guidelines/rules.md`.

После финализации проверка `assertBrandPptx` должна вернуть `ok:true` (все 14
инвариантов: размер `cx=24382800 cy=13716000`, направляющие в `presentation.xml` и в
мастере, тема `F2F2F2`, 18 макетов, шрифты YS, заголовки в плейсхолдерах,
заголовок наследует YS Display Cond Heavy, титул красный, финал СЕРЫЙ). Только тогда файл можно отдавать.

## Полный свод правил ПСиИИ

**Перед любой работой прочитай `guidelines/rules.md`** — это канонический свод всех
правил бренда (типографика, размер слайда, направляющие, положение заголовка и
колонтитула, яркие слайды, логотипы, тема и макеты при экспорте, композиция). Все
правила обязательны и в режиме проекта-потребителя.

Если строишь слайды в HTML (превью/прототип) — канвас 1920×1080, поля 115px,
заголовок на left:115 top:77 width:1690, колонтитул на top:979, яркие слайды на
красном `#F66048`. Эти же правила действуют при экспорте в PPTX.

Если строишь интерфейс (кнопки, поля, табы, иконки) — бери их из UI-кита,
не перерисовывай (Правила 73/75). Компоненты и иконки подключаются с
`window.DesignSystem_132e64` после загрузки `_ds_bundle.js` (в проекте-потребителе
— `_ds/<папка>/_ds_bundle.js`), иконки — `<Icon name="search" />` (Правило 76).

If creating other visual artifacts (mocks, throwaway prototypes), copy assets out
(`assets/fonts`, `assets/logos`, `assets/icons`) and produce static HTML the user
can view. If working on production code, copy the assets, link `styles.css`, and
read the rules here to become an expert in designing with this brand.

Key files:
- `styles.css` — the global entry (link this one file); pulls in `tokens/*`.
- `readme.md` — full brand context: content tone, visual foundations, iconography.
- `tokens/` — colors, typography, spacing/grid, `@font-face` (YS Display Cond + YS Text).
- `assets/` — `fonts/`, `logos/` (Yandex mark + wordmark, ПСиИИ wordmark), `icons/` (225-glyph line set + `Icon` компонент с поиском по имени/подписи).
- `components/` — `brand/` (Logo, SlideFooter), `core/` (Button, Tag, Badge), `uikit/` (Input, TextArea, Select, Checkbox, RadioButton, Switcher, Tabs, Tooltip, Trobber, Divider, ListItem, ContextMenu, Avatar, Modal), `slides/` (SlideFrame, SlideHeader, StatNumber, ColorSwatch).
- `ui_kits/slides/` — interactive 8-layout deck recreation.
- `templates/business-pptx/source.pptx` — канонический шаблон (18 макетов, тема,
  направляющие, размер 67,73×38,1 см) — основа и контейнер для всех дек.
- `templates/business-pptx/build-pptx.js` — **железобетонный сборщик** (`buildBrandPptx`):
  собирает деку из текстового описания прямо в шаблоне, фирменно по построению (без
  `gen_pptx`). Путь по умолчанию.
- `templates/business-pptx/build-deck.js` — **WYSIWYG-путь** (`buildBrandDeck`): один
  спец `slides[]` → `{ pptx, html }`, где HTML-превью отрисовано из того же .pptx —
  превью и выгрузка идентичны по построению. Для публичного пользователя, когда нужно
  «превью = файл».
- `templates/business-pptx/finalize-pptx.js` — скрипт финализации HTML-экспорта (запасной путь).
- `templates/business-pptx/rebrand-pptx.js` — рестайл готового чужого `.pptx` к бренду
  НА МЕСТЕ (`rebrandPptxInPlace` + `assertIngestRebrand`): тема/размер/направляющие
  меняются, слайды/текст/картинки — нет. Путь для «приведи мой pptx к дизайн-системе» (Правило 84).
- `references/pptx-local-build-and-visual-qa.md` — локальный Node-паттерн сборки
  `buildBrandDeck`, оба гейта, Quick Look visual QA и безопасный OOXML-фикс SVG-логотипа
  через PNG + relationship rewrite (включая запрет широкого regex, который ломает соседние `<a:blip/>`).
- `references/audio-derived-presentation-rules.md` — правила из Zoom-разбора: канонический шаблон,
  native layouts/placeholders, editable charts/tables, типографика, whitespace и validation checklist.
- `guidelines/` — foundation specimen cards + photo/3D-icon prompt guidance.
- `guidelines/rules.md` — **канонический свод всех правил ПСиИИ** (обязателен к прочтению).

If the user invokes this skill without other guidance, ask what they want to build
or design, ask a few questions, then act as an expert designer who outputs HTML
artifacts **or** production code, depending on the need. Keep copy in Russian,
sentence case, plain and declarative — no emoji, no exclamation marks.
