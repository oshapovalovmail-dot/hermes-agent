# ПСиИИ Design System
### Яндекс · Поисковые сервисы и ИИ — Брендбук 2026

A **presentation design system** for the Yandex *Search Services & AI* business
group (ПСиИИ — «Поисковые сервисы и ИИ»). It exists to make on-brand slide decks:
minimalist, white-canvas, ink-on-white, with a single hot Yandex-red accent and
strict typographic + grid discipline. The brief: *«минималистичный стиль с
элементами интерфейса»* — a clean editorial style that borrows interface
furniture (icons, tags, the Yandex mark) without becoming a UI.

> This is a brand/presentation system, **not** a product app. The reusable
> components are slide-building primitives (logo, footer, stat, swatch), a
> brand-true interface kit — buttons, tags, badges plus form controls (input,
> select, checkbox, radio, switcher, tabs, tooltip, divider) and containers
> (list item, context menu, avatar) authored from the Yandex UI-kit — and the
> full 218-glyph Yandex line-icon set.

> **Canonical rules live in `guidelines/rules.md`** — always read it first; it
> applies both here and in consuming projects (linked from `SKILL.md`).

---

## Sources

These were provided and are the source of truth. The reader may not have access;
they're recorded here in case they do.

- **Figma:** «Гайд ПСиИИ (1).fig» — the brandbook itself (page «Page-1», 27 spec
  frames: title, typography, palette, icons, 3D icons, photo style, rules). All
  token values, the type scale and the icon set were extracted from it.
- **Fonts:** `YS Display Cond (3).zip`, `YS Text (4).zip` — the official Yandex
  Sans webfonts. Extracted into `assets/fonts/` (see Typography).
- **Logos:** `Лого Яндекс.svg`, `Знак Яндекс.svg`, `Лого ПСиИИ.svg` → `assets/logos/`.
- **Decks:** `Slides_CD.pptx` — a real ПСиИИ slide template (title / agenda /
  divider / big-thesis / text / two-column / stats layouts). Used to confirm
  layout, hierarchy and copy tone. (A second `Шаблон_ПСиИИ_бизнес.pptx` was
  referenced but did not arrive in the upload — see Caveats.)

---

## CONTENT FUNDAMENTALS — how copy is written

The brandbook and deck are in **Russian**. Tone is **plain, declarative,
business-direct** — Yandex house style: confident but not loud, no marketing
fluff, no exclamation marks.

- **Voice & address.** Speaks *to* the audience and gives crisp instructions.
  The brandbook's own rules use the informal imperative «ты»: *«Чётко
  придерживайся дизайн-системы»*, *«Используй только шрифты и цвета из шаблона»*.
  Deck body copy is neutral third-person product prose: *«Создавайте
  неограниченное количество креативов бесплатно прямо в интерфейсе Яндекс
  Директа»* (here the polite «вы» imperative).
- **Casing.** Sentence case everywhere — headings included. **No ALL-CAPS**, no
  Title Case. Proper nouns keep their case («Яндекс Директ», «ИИ»).
- **Headlines** are long and can wrap 2–3 lines: *«Длинный заголовок в две или
  больше строк»*. They are statements, not clickbait.
- **Labels** are short and functional: «Примечание», «Подзаголовок», «Подпись»,
  «О чём поговорим?», «Что важно сегодня?».
- **Numbers** are first-class: big bare percentages («24%», «10%») with a small
  caption underneath. Agenda items are numbered «01 02 03 …».
- **Punctuation.** Russian quotes «ёлочки», em-dashes for thesis statements
  («Важный тезис — идея, мысль…»), questions are allowed as section openers.
- **No emoji.** Iconography does the visual lifting, never emoji.

**Vibe:** calm, precise, modern, a little austere. White space is content.

---

## VISUAL FOUNDATIONS

**Background.** Pure white (`#FFFFFF`) is the default and near-universal slide
ground. Dark slides (`#1F1F20`) and the deep `#330001`/`#600100` reds appear only
as deliberate accent moments (a stat slide, a closing slide, a photo backdrop).
No gradients in layout — gradients exist only *inside* generated imagery / 3D
icons (warm orange glow on black), never as slide chrome.

**Color.** Ink-on-white with one accent. `--ink #1D0203` for titles, `#1F1F20`
for primary fills/text, `#494949` for body, `#909090` for captions. The accent is
**Yandex red `#FC3F1D`** (the mark) plus `#EE1E1C`/`#F66047` for variation — used
sparingly (the mark, a single highlighted word, a key figure). Pastels
(`#FFA787` peach, `#ADD2E6` sky) are reserved for photography and 3D-icon
treatments, not UI.

**Type.** Two families: **YS Display Cond** (condensed, Heavy/900) for titles,
section dividers, **slide headlines (H1, 96/72/60)** and big numerals — set huge
(120–220px on slide) with ultra-tight leading **0.85** and **−0.02em** tracking.
**YS Text** for H2, subtitles, body, captions and all UI. Tracking is tight; body
leading ~1.2. Hierarchy is driven by *size and weight*, not color.

**Layout & grid.** Fixed **1920×1080** canvas. **20px safe-area** margin holds
the header (business-group label top-left, small dark Yandex corner-mark
top-right) and footer. **40px content margin**; the title block sits at **y≈172**.
A 12-column grid (20px gutters) with thin `#B19494` guide lines is *always on* —
the brandbook's Rule 2 is literally «всегда используй сетку». Elements snap to it;
titles sit in fixed positions.

**Footer.** Every content slide carries a 15px, 50%-opacity line bottom-left:
«Яндекс Поисковые сервисы и ИИ» + «Брендбук 2026», and a page number bottom-right.

**Shape.** Overwhelmingly **sharp** — color swatches, image frames and panels have
**0 radius**. The only round things are the Yandex mark / avatars (full circle)
and, in the interface kit, pill buttons. Cards are flat: no borders, no shadows by
default; the look is achieved with whitespace and the grid. Shadows exist as
tokens but are used rarely and softly.

**Imagery.** Two photo directions documented in the brandbook via AI prompts:
(1) **dramatic editorial portraits** — chiaroscuro, vibrant orange/red rim light
on near-black (`#260102`) backgrounds; (2) **warm everyday** — sunny muted
palette (yellow/peach/cream), cinematic soft daylight, light grain/vignette,
"cozy, slightly dreamy". 3D icons are clean premium product renders with soft warm
internal glow on black. Overall image vibe: **warm**, high-craft, no noise.

**Motion.** Restrained. Fades and short slides (120–360ms) on standard/`ease-out`
curves. No bounces, no decorative loops. Hover = subtle opacity/!color shift;
press = slight darken (pill buttons) — never playful scaling.

---

## ICONOGRAPHY

The brandbook ships a **single proprietary line-icon set: 218 Yandex glyphs**
(`assets/icons/`). They are:

- **Filled single-color paths** (not open strokes), drawn to read as ~2px-stroke
  outline icons on a 24px grid; color via `currentColor` (default `#1F1F20`).
- A broad utility set: bell/like/lock/eye/heart, chevrons & arrows, search/edit,
  files & folders, media controls, devices, people, commerce (₽, %, card),
  weather, transport, plus brand glyphs (a Yandex «Я» mark, `i092`).
- Stored in **`assets/icons/icon-data.js`**
  (`{ viewBox, body }` per glyph) and rendered by **`Icon.jsx`**.
- **Addressed by semantic name** — `search`, `bell`, `settings`, `trash`… Type-to-filter
  the full list in the **Icons gallery card**. Render: `<Icon name="search" size={24} />`.
  A few duotone glyphs knock out detail via `--ds-icon-bg` — pass `bg="<surface>"` on dark.
- **Searchable metadata** — `ICON_META[name] = [ruLabel, groupCode, keywords]` plus
  `ICON_GROUPS` (code→Russian category). The gallery card searches name + Russian label
  + keywords and groups by category; click any icon to copy its `<Icon>` snippet.

There is also a separate **3D-icon** direction (premium render style) documented in
the brandbook but supplied as generated raster art, not vectors — recreate via the
prompt in `guidelines/`, don't hand-draw.

**No emoji. No Unicode-as-icon.** Use the line set or the Yandex marks only.
Icon usage is governed by **Правило 73** (one size per group, brand colors
only — red/black/gray/white, no stroke, used sparingly).

---

## INTERFACE KIT

Buttons and controls follow **Правило 75** and the Yandex UI-kit. Values are
extracted from the kit's Figma file, not invented:

- **Pill** shape, flat, **YS Text Regular 14/20** (not Medium). Sizes are the
  kit's pixel heights — **24 / 28 / 36 / 64** (default 36; use ≥36 on slides).
- **Button types:** `primary` (graphite `#2C2C32`) · `secondary` (black 6%) ·
  `stroke` (hairline 12%) · `ghost` · `link` (blue `#0077FF` — UI mockups only,
  the one sanctioned blue) · `accent` (Yandex red — one main CTA per screen).
- **Containers & overlays:** ListItem, ContextMenu, Avatar, Modal (dialog with
  header / body / footer actions) — same kit tokens.
- The kit's full **Figma Variable system** ships as `components/uikit/fig-tokens.css`
  (85 vars across light/dark/pro/night modes), imported by `styles.css`.

---

## INDEX — what's in this folder

**Foundations**
- `styles.css` — root entry (imports only). Link this one file.
- `tokens/colors.css` · `tokens/typography.css` · `tokens/spacing.css` · `tokens/fonts.css`
- `guidelines/*.card.html` — foundation specimen cards (Type, Colors, Spacing, Brand)
- `guidelines/photo-and-3d.md` — image & 3D-icon prompt guidance

**Assets**
- `assets/fonts/` — YS Display Cond (Medium/Bold/Black/Heavy) + YS Text (Light/Regular/Medium/Bold)
- `assets/logos/` — `yandex-logo.svg`, `yandex-mark.svg` (the red «Я»), `psiii-logo.svg`
- `assets/icons/` — `icon-data.js`, `Icon.jsx`, gallery card (218 glyphs)

**Foundations (cont.)**
- `guidelines/rules.md` — the canonical numbered rules (typography, slides,
  composition, tables → Правило 74, icons → Правило 73, buttons & controls →
  Правило 75). Read first.

**Components** (`components/<group>/`)
- `brand/` — `Logo`, `SlideFooter`
- `core/` — `Button` (graphite pill, 6 types, sizes 24/28/36/64), `Tag`, `Badge`
- `uikit/` — `Input`, `TextArea`, `Select`, `Checkbox`, `RadioButton`, `Switcher`,
  `Tabs`, `Tooltip`, `Trobber`, `Divider`, `ListItem`, `ContextMenu`, `Avatar`,
  `Modal` (+ `fig-tokens.css`)
- `slides/` — `SlideFrame`, `SlideHeader`, `StatNumber`, `ColorSwatch`,
  `QuoteBubble` (фирменный спич-бабл для цитат/отзывов — Правило 81)

**UI kit** (`ui_kits/`)
- `slides/` — branded cover linking to the PPTX template.

**Templates** (`templates/`)
- `deck/presentation-psiii.pptx` — the original PowerPoint template, **unchanged**;
  the base for all decks (build directly in the PPTX, preserving fonts/grid/colors).

**Skill**
- `SKILL.md` — Agent-Skill manifest for downloading into Claude Code.

---

## CAVEATS
- The presentation **template is `Slides_CD.pptx`**, included unchanged as
  `templates/deck/presentation-psiii.pptx` — the base for all decks. Slides can be
  filled programmatically (PPTX = zip of XML); live HTML can't rasterize PPTX
  pages, so the file itself is the source of truth (export to PDF/PNG if image
  previews are needed).
- **3D icons & branded photography** are AI-generated raster art in the source —
  reproduced via documented prompts, not bundled as assets.
