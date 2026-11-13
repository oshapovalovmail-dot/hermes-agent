---
name: powerpoint
description: Create, read, edit .pptx decks, slides, notes, templates.
license: Proprietary. LICENSE.txt has complete terms
platforms:
- linux
- macos
- windows
metadata:
  hermes:
    visibility: global
    aliases: []
---

# Powerpoint Skill

## When to use

Use this skill any time a .pptx file is involved in any way — as input, output, or both. This includes: creating slide decks, pitch decks, or presentations; reading, parsing, or extracting text from any .pptx file (even if the extracted content will be used elsewhere, like in an email or summary); editing, modifying, or updating existing presentations; combining or splitting slide files; working with templates, layouts, speaker notes, or comments. Trigger whenever the user mentions "deck," "slides," "presentation," or references a .pptx filename, regardless of what they plan to do with the content afterward. If a .pptx file needs to be opened, created, or touched, use this skill.

## Quick Reference

| Task | Guide |
|------|-------|
| Read/analyze content | `python -m markitdown presentation.pptx` |
| Edit or create from template | Read [editing.md](editing.md) |
| Create from scratch (Node) | Read [pptxgenjs.md](pptxgenjs.md) |
| Create from scratch (Python, no Node) | Read [references/python-pptx.md](references/python-pptx.md) |

**Picking a builder.** Default to `pptxgenjs` only if Node is already in play. Inside Hermes / Claude Code / Codex environments where Node is not installed and you don't want to drag it in, OR when the agent runtime is *not* Codex (so the `Presentations` skill's artifact-tool JSX path is unavailable), use `python-pptx`. It's pure-Python, works in any throwaway venv, and the dependency story is one `pip install python-pptx Pillow` line. See [references/python-pptx.md](references/python-pptx.md) for a working dark-theme recipe, Cyrillic-safe typography, and QA fallback when LibreOffice is missing.

**Related installable skill.** For headless model-backed decks, especially pitch decks / IC memos / finance decks where every number must trace to a workbook cell, prefer the official optional `pptx-author` skill (`official/finance/pptx-author`). If the user asks for the best skill to create `.pptx` presentations and install it into Hermes, install `pptx-author`, verify `~/.hermes/skills/finance/pptx-author/SKILL.md`, then load it with `skill_view(name='pptx-author')`. Keep using this broader `powerpoint` skill for general PPTX editing, templates, speaker notes, media, and visual QA.

---

## Reading Content

```bash
# Text extraction
python -m markitdown presentation.pptx

# Visual overview
python scripts/thumbnail.py presentation.pptx

# Raw XML
python scripts/office/unpack.py presentation.pptx unpacked/
```

### Fallback: direct OpenXML text extraction

If `markitdown` is unavailable or installing it would be a pointless detour, extract text directly from the PPTX zip. PPTX files are zip archives; slide text lives under `ppt/slides/slideN.xml`, notes under `ppt/notesSlides/notesSlideN.xml`. This is enough for dossier/context ingestion where visual QA is not required.

Use a short Python ZipFile + ElementTree extractor that reads `a:t`/text nodes and records slides with no extractable text. Resolve display order through `ppt/presentation.xml` (`p:sldIdLst`) and `ppt/_rels/presentation.xml.rels`: numeric `slideN.xml` filenames are creation order, not necessarily display order after insertion or reordering. Use the resolved order for per-page PDF text checks too; otherwise a correct reordered deck produces false missing-text findings. Do not claim visual interpretation from this path: it extracts text only, not layout, images, charts, or SmartArt semantics.

---

## Editing Workflow

**Read [editing.md](editing.md) for full details.**

1. Analyze template with `thumbnail.py`
2. Unpack → manipulate slides → edit content → clean → pack

---

## Creating from Scratch

**Read [pptxgenjs.md](pptxgenjs.md) for full details.**

Use when no template or reference presentation is available.

---

## Design Ideas

**Don't create boring slides.** Plain bullets on a white background won't impress anyone. Consider ideas from this list for each slide.

### Before Starting

- **Pick a bold, content-informed color palette**: The palette should feel designed for THIS topic. If swapping your colors into a completely different presentation would still "work," you haven't made specific enough choices.
- **Dominance over equality**: One color should dominate (60-70% visual weight), with 1-2 supporting tones and one sharp accent. Never give all colors equal weight.
- **Dark/light contrast**: Dark backgrounds for title + conclusion slides, light for content ("sandwich" structure). Or commit to dark throughout for a premium feel.
- **Commit to a visual motif**: Pick ONE distinctive element and repeat it — rounded image frames, icons in colored circles, thick single-side borders. Carry it across every slide.

### Color Palettes

Choose colors that match your topic — don't default to generic blue. Use these palettes as inspiration:

| Theme | Primary | Secondary | Accent |
|-------|---------|-----------|--------|
| **Midnight Executive** | `1E2761` (navy) | `CADCFC` (ice blue) | `FFFFFF` (white) |
| **Forest & Moss** | `2C5F2D` (forest) | `97BC62` (moss) | `F5F5F5` (cream) |
| **Coral Energy** | `F96167` (coral) | `F9E795` (gold) | `2F3C7E` (navy) |
| **Warm Terracotta** | `B85042` (terracotta) | `E7E8D1` (sand) | `A7BEAE` (sage) |
| **Ocean Gradient** | `065A82` (deep blue) | `1C7293` (teal) | `21295C` (midnight) |
| **Charcoal Minimal** | `36454F` (charcoal) | `F2F2F2` (off-white) | `212121` (black) |
| **Teal Trust** | `028090` (teal) | `00A896` (seafoam) | `02C39A` (mint) |
| **Berry & Cream** | `6D2E46` (berry) | `A26769` (dusty rose) | `ECE2D0` (cream) |
| **Sage Calm** | `84B59F` (sage) | `69A297` (eucalyptus) | `50808E` (slate) |
| **Cherry Bold** | `990011` (cherry) | `FCF6F5` (off-white) | `2F3C7E` (navy) |

### For Each Slide

**Every slide needs a visual element** — image, chart, icon, or shape. Text-only slides are forgettable.

**Layout options:**
- Two-column (text left, illustration on right)
- Icon + text rows (icon in colored circle, bold header, description below)
- 2x2 or 2x3 grid (image on one side, grid of content blocks on other)
- Half-bleed image (full left or right side) with content overlay

**Data display:**
- Large stat callouts (big numbers 60-72pt with small labels below)
- Comparison columns (before/after, pros/cons, side-by-side options)
- Timeline or process flow (numbered steps, arrows)

**Visual polish:**
- Icons in small colored circles next to section headers
- Italic accent text for key stats or taglines

### Typography

**Choose an interesting font pairing** — don't default to Arial. Pick a header font with personality and pair it with a clean body font.

| Header Font | Body Font |
|-------------|-----------|
| Georgia | Calibri |
| Arial Black | Arial |
| Calibri | Calibri Light |
| Cambria | Calibri |
| Trebuchet MS | Calibri |
| Impact | Arial |
| Palatino | Garamond |
| Consolas | Calibri |

| Element | Size |
|---------|------|
| Slide title | 36-44pt bold |
| Section header | 20-24pt bold |
| Body text | 14-16pt |
| Captions | 10-12pt muted |

### Spacing

- 0.5" minimum margins
- 0.3-0.5" between content blocks
- Leave breathing room—don't fill every inch

### Avoid (Common Mistakes)

- **Don't repeat the same layout** — vary columns, cards, and callouts across slides
- **Don't center body text** — left-align paragraphs and lists; center only titles
- **Don't skimp on size contrast** — titles need 36pt+ to stand out from 14-16pt body
- **Don't default to blue** — pick colors that reflect the specific topic
- **Don't mix spacing randomly** — choose 0.3" or 0.5" gaps and use consistently
- **Don't style one slide and leave the rest plain** — commit fully or keep it simple throughout
- **Don't create text-only slides** — add images, icons, charts, or visual elements; avoid plain title + bullets
- **Don't forget text box padding** — when aligning lines or shapes with text edges, set `margin: 0` on the text box or offset the shape to account for padding
- **Don't use low-contrast elements** — icons AND text need strong contrast against the background; avoid light text on light backgrounds or dark text on dark backgrounds
- **NEVER use accent lines under titles** — these are a hallmark of AI-generated slides; use whitespace or background color instead

---

## QA (Required)

**Assume there are problems. Your job is to find them.**

Your first render is almost never correct. Approach QA as a bug hunt, not a confirmation step. If you found zero issues on first inspection, you weren't looking hard enough.

### Content QA

```bash
python -m markitdown output.pptx
```

Check for missing content, typos, wrong order.

### OOXML semantic integrity after template surgery

When reusing an animated template, deleting shapes through `python-pptx` private XML APIs is not enough. `python-pptx` can preserve slide-level `p:timing` / `p:bldLst` trees whose `p:spTgt/@spid` references point to deleted shapes or collide with newly created shape IDs. The ZIP, relationships, `Presentation(path)`, and marker/layout checks can all pass while PowerPoint opens the deck only after repair.

For every slide after wholesale shape deletion:

1. either rebuild the slide without inherited animation metadata;
2. or remove stale `p:timing` and related build metadata before saving;
3. validate every timing/build `spid` against live `p:cNvPr/@id` values;
4. open/export with a real Office renderer when compatibility matters.

Do not claim PowerPoint compatibility from ZIP validity, `python-pptx` reopen, or geometric overlap checks alone.

### DrawingML singleton effects and native PowerPoint acceptance

`shape.shadow.inherit = False` already creates `a:effectLst` in `p:spPr`. Appending another `OxmlElement('a:effectLst')` produces invalid DrawingML even when both nodes are empty. Use the existing effect list, or an idempotent find/create operation; set the theme `a:effectRef` index to zero separately if needed. Inspect **all** package parts for repeated singleton nodes and validate PresentationML with the available `pml.xsd` (including imports). For repair, preserve the original; remove duplicate empty effect lists only after checking they are genuinely empty, and refuse to discard nonempty effects without semantic reconciliation. Fix the generator as well as the artifact.

LibreOffice can export an invalid PPTX to a clean-looking PDF while Microsoft PowerPoint asks to Repair it. Visual PNG QA and ZIP/relationship checks therefore do not close a reported corrupted-file defect. Reproduce the original prompt in native PowerPoint, isolate the XML correction on a control copy, then open the exact final artifact, close it and reopen without Repair. Preserve slide text, notes, relationships and unaffected renders; do not claim a successful Microsoft PowerPoint test from a LibreOffice round trip.

### Connector arrowhead visibility

A connector ending exactly at a filled destination card can have its small arrowhead visually merge into that card or be obscured by its paint order. Check arrowheads themselves, not just the presence of connecting lines. For converging inputs, leave a small visible gap before the destination, use legible triangle head dimensions and adequate line width, and verify **every** head in both the PDF raster and native PowerPoint. Preserve the graph semantics and node labels. When widening a process-label column, move and narrow its explanatory column as a unit before reducing font size; confirm the requested label is one rendered line in native Office, not merely free of explicit newline characters.

**When using templates, check for leftover placeholder text:**

```bash
python -m markitdown output.pptx | grep -iE "xxxx|lorem|ipsum|this.*(page|slide).*layout"
```

If grep returns results, fix them before declaring success.

### Visual QA

**⚠️ USE SUBAGENTS** — even for 2-3 slides. You've been staring at the code and will see what you expect, not what's there. Subagents have fresh eyes.

Convert slides to images (see [Converting to Images](#converting-to-images)), then use this prompt:

```
Visually inspect these slides. Assume there are issues — find them.

Look for:
- Overlapping elements (text through shapes, lines through words, stacked elements)
- Text overflow or cut off at edges/box boundaries
- Decorative lines positioned for single-line text but title wrapped to two lines
- Source citations or footers colliding with content above
- Elements too close (< 0.3" gaps) or cards/sections nearly touching
- Uneven gaps (large empty area in one place, cramped in another)
- Insufficient margin from slide edges (< 0.5")
- Columns or similar elements not aligned consistently
- Low-contrast text (e.g., light gray text on cream-colored background)
- Low-contrast icons (e.g., dark icons on dark backgrounds without a contrasting circle)
- Text boxes too narrow causing excessive wrapping
- Leftover placeholder content

For each slide, list issues or areas of concern, even if minor.

Read and analyze these images:
1. /path/to/slide-01.jpg (Expected: [brief description])
2. /path/to/slide-02.jpg (Expected: [brief description])

Report ALL issues found, including minor ones.
```

### Verification Loop

1. Generate slides → Convert to images → Inspect
2. **List issues found** (if none found, look again more critically)
3. Fix issues
4. **Re-verify affected slides** — one fix often creates another problem
5. Repeat until a full pass reveals no new issues

**Do not declare success until you've completed at least one fix-and-verify cycle.**

---

## Converting to Images

Convert presentations to individual slide images for visual inspection:

```bash
python scripts/office/soffice.py --headless --convert-to pdf output.pptx
pdftoppm -jpeg -r 150 output.pdf slide
```

This creates `slide-01.jpg`, `slide-02.jpg`, etc.

To re-render specific slides after fixes:

```bash
pdftoppm -jpeg -r 150 -f N -l N output.pdf slide-fixed
```

**No LibreOffice installed (common on fresh macOS / sandboxed envs)?** Do NOT block the task. Two fallbacks, in order of preference:

1. **macOS Quick Look thumbnail** — built into the OS, no install:
   ```bash
   qlmanage -t -s 1600 -o /tmp/qa/ output.pptx
   ```
   Produces a single PNG of slide 1 (`output.pptx.png`). Enough for cover sanity-check (layout collapse, font fallback, kerning). NOT enough for multi-slide QA — for that, ask the user to install `brew install --cask libreoffice` once, or render via Keynote and screenshot.
2. **Ship and let user verify** — for non-critical decks, attach the PPTX (`MEDIA:/abs/path/file.pptx` on Telegram) with an honest disclaimer that only the cover was thumbnail-verified, and offer to iterate on specific slides the user flags. Better than silently sitting on a build because you can't render everything.

---

## Dependencies

- `pip install "markitdown[pptx]"` - text extraction
- `pip install Pillow` - thumbnail grids
- `npm install -g pptxgenjs` - creating from scratch
- LibreOffice (`soffice`) - PDF conversion (auto-configured for sandboxed environments via `scripts/office/soffice.py`)
- Poppler (`pdftoppm`) - PDF to images
