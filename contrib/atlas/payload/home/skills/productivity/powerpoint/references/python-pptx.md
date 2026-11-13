# Creating PPTX from scratch with python-pptx

Use when Node / `pptxgenjs` is not available, or when the agent runtime is **not** Codex (so the official `Presentations` skill's artifact-tool JSX path is out of reach). `python-pptx` is pure-Python, ships native shapes/text/tables, and produces editable PPTX that opens cleanly in Keynote and PowerPoint.

## Setup (one-off, throwaway venv)

macOS / Apple-managed Pythons reject `pip install` with PEP 668. Use a throwaway venv built off homebrew Python — fast, predictable, no fight with the OS:

```bash
python3 -m venv /tmp/pptx-venv
/tmp/pptx-venv/bin/pip install --quiet python-pptx Pillow
/tmp/pptx-venv/bin/python -c "import pptx, PIL; print(pptx.__version__, PIL.__version__)"
```

`Pillow` is optional (only needed if you embed raster images). Skip it for vector-only decks.

## When to pick `python-pptx` over alternatives

| Want… | Use |
|-------|-----|
| Codex artifact-tool JSX with built-in QA loop | The `Presentations` skill (Codex-only) |
| Edit a user-supplied template, preserve master slides | `editing.md` (unpack/repack) |
| Build a deck from scratch in a Node environment | `pptxgenjs.md` |
| Build from scratch, no Node, no Codex runtime | **this file** |
| Quick markdown → deck for a meeting note | `markitdown` reverse / a one-shot script |

## Minimum viable recipe (16:9, dark theme, Cyrillic-safe)

The pattern that works on Hermes/Telegram delivery and survives Keynote/PowerPoint open:

```python
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

# Palette — commit to a 3-color system, see SKILL.md "Design Ideas"
INK    = RGBColor(0x0E, 0x12, 0x1B)  # background
PANEL  = RGBColor(0x15, 0x1B, 0x28)  # panels / cards
LINE   = RGBColor(0x2A, 0x33, 0x46)  # hairlines
TEXT   = RGBColor(0xE6, 0xEA, 0xF2)
MUTED  = RGBColor(0x9A, 0xA4, 0xB8)
ACCENT = RGBColor(0xFF, 0xDB, 0x4D)  # one sharp accent

prs = Presentation()
prs.slide_width  = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]

def fill(shape, rgb):
    shape.fill.solid()
    shape.fill.fore_color.rgb = rgb
    shape.line.fill.background()

def add_rect(slide, x, y, w, h, rgb=None, line=None, line_w=0.75):
    shp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE,
                                  Inches(x), Inches(y), Inches(w), Inches(h))
    if rgb is not None:
        fill(shp, rgb)
    else:
        shp.fill.background()
    if line is not None:
        shp.line.color.rgb = line
        shp.line.width = Pt(line_w)
    else:
        shp.line.fill.background()
    shp.shadow.inherit = False
    return shp

def add_text(slide, x, y, w, h, text, size=14, color=TEXT, bold=False,
             font="Helvetica Neue", align=PP_ALIGN.LEFT,
             anchor=MSO_ANCHOR.TOP, spacing=1.1):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.margin_left = tf.margin_right = Inches(0)
    tf.margin_top = tf.margin_bottom = Inches(0)
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    for i, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        r = p.add_run()
        r.text = line
        r.font.name = font
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = color
    return tb
```

These four helpers (`fill`, `add_rect`, `add_text`, plus a tiny `kicker`/`title` of your taste) are enough to build the entire deck. Resist the urge to wrap python-pptx's API in heavier abstractions — every slide is hand-laid in inches.

## Gotchas verified in production

- **Zero text-box padding by default is wrong.** python-pptx ships with non-trivial `margin_left/right/top/bottom` on textboxes. If you place a textbox at `x=0.7` and a shape edge at `x=0.7`, the text starts ~0.1" inside. Always zero the margins explicitly (`tf.margin_left = Inches(0)` etc.) when you align text to shapes.
- **`shp.shadow.inherit = False`** kills the default subtle drop-shadow on every shape. Without it, dark themes pick up muddy halos that look like a bug.
- **Cyrillic fonts.** Specify `font.name = "Helvetica Neue"` (macOS) or `"Inter"` / `"Segoe UI"` (cross-platform). Without an explicit name, PowerPoint on Windows falls back to Calibri and the Cyrillic kerning goes weird. The font name is metadata — the actual glyphs come from the viewer's system.
- **Slide layout index 6 = blank.** Always start from `prs.slide_layouts[6]` and lay shapes manually. The other layouts come with theme placeholders that fight you.
- **One accent color, used sparingly.** Do not paint every kicker, title, and divider in the accent. Use it as the spotlight (one per slide), let `PANEL` + hairline `LINE` do the structural work.
- **Footer / page-number convention.** A 0.01"-tall rectangle at `y = H - 0.45` as the divider plus left-aligned section name and right-aligned `page / total` reads cleanly and survives thumbnail QA.
- **Inches, not EMU.** Use `Inches(...)`/`Pt(...)` everywhere. Hand-computing EMU is a footgun (`914400 EMU = 1 inch`).
- **No native chart styling beyond what the API gives you.** If you need a precise bar/line chart with direct labels, build it from rectangles + lines yourself — `chart.yAxis.majorGridlines` and friends can throw `toProto` errors on export. Authored shapes are uglier API but rock-solid.

## Native time-series chart checks

For an existing editable deck, `chart.replace_data(CategoryChartData(...))` preserves the chart object while extending its series. Reopen the saved PPTX and compare every series value and category count against the canonical daily data; verify an exact continuous date grid rather than silently filling absent dates. When a slide already has its own chart heading, explicitly set `chart.has_title = False`: LibreOffice can otherwise display the single series name as an extra chart title and misalign adjacent plots. A `tickLblSkip` OOXML setting may be ignored by the renderer, so judge actual rendered date-label density rather than the requested interval.

When retaining old slides and only updating page totals, compare final rasters with the previously accepted rasters. A pixel-difference bounding box confined to the page-number region verifies content preservation; inspect every changed graph at full resolution separately.

## Native PowerPoint PDF export on macOS

When PowerPoint is installed, a task-owned presentation can be opened and exported without `activate`. Use an exact presentation name, never `presentation 1` when unrelated decks may be open. In the verified AppleScript route, use `save targetDeck in (POSIX file pdfPath) as save as PDF`, then verify the actual output file and page count. Passing a bare POSIX path string returned success without producing the expected PDF; a successful AppleScript return is not an export receipt. Close only the task-owned deck with `saving no`, reopen the exact PPTX and verify its slide count. Re-render final QA images from the actual delivered native PDF. Native `open`/slide-count readback does not establish that every rendered text object is unclipped.

## QA without LibreOffice

Render the cover thumbnail with macOS's built-in Quick Look:

```bash
qlmanage -t -s 1600 -o /tmp/qa/ output.pptx
# produces /tmp/qa/output.pptx.png
```

Then pipe that PNG to vision (`vision_analyze` / equivalent) and ask for layout collapses, font fallback, text overflow. This only covers slide 1 — for full deck QA install LibreOffice (`brew install --cask libreoffice`) or render in Keynote and screenshot. Honest disclosure to the user when only the cover was verified beats silent over-promising.

## Validation checklist before shipping

```python
from pptx import Presentation
p = Presentation("output.pptx")
print("slides:", len(p.slides))
print("size:", p.slide_width, p.slide_height)        # expect 12191695 6858000 for 13.333x7.5"
for i, s in enumerate(p.slides, 1):
    print(f"  slide {i}: {len(s.shapes)} shapes")
```

Sanity floor: cover slide ~5–15 shapes, content slides 20–60. If a slide has <3 shapes, you forgot the background. If it has >100, you're probably building a card grid that the contact-sheet test will reject — refactor toward fewer, larger proof objects (see SKILL.md "Design Ideas").

## Delivery on Hermes/Telegram

Once the PPTX is written, ship it natively by including `MEDIA:/absolute/path/file.pptx` in the reply. The Telegram gateway delivers it as a file attachment. PPTX has no inline preview on Telegram — accept that and prefix the message with a one-paragraph summary of what's inside so the user knows what they're opening.
