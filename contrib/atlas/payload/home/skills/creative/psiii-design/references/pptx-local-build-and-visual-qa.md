# Local Node build + visual QA pattern for branded PPTX decks

Use this when building a ПСиИИ deck locally/headlessly rather than through browser `run_script`.

## Pattern

1. Build directly from `templates/business-pptx/source.pptx` using the WYSIWYG path:
   - evaluate `finalize-pptx.js`, `build-pptx.js`, and `build-deck.js` in the same JS scope;
   - call `buildBrandDeck({ JSZip, templateBytes, slides, assetsBase, title })`;
   - write both artifacts: final `.pptx` and HTML preview.

2. Gate before delivery:
   - `assertBrandPptx({ JSZip, bytes })`
   - `assertDesignDiscipline({ JSZip, bytes })`
   - hard fail if either returns `ok:false`.

3. Run full visual QA after gates. The XML gates catch brand invariants, not renderer artifacts:
   - render **every slide**, not only the cover, at reviewable resolution;
   - use the canonical target renderer (PowerPoint/Quick Look when available) and at least one independent headless path such as LibreOffice→PDF→Poppler;
   - inspect each raster for cropped text, overlaps, wrong background, missing/phantom logos, section/stat treatment, grid, contrast, and typography;
   - compare renderers for font substitution and geometry drift. A deck that looks correct in Quick Look but becomes serif or reflows in LibreOffice is not cross-renderer WYSIWYG;
   - save a contact sheet plus per-slide evidence and bind the verdict to the exact PPTX SHA-256.

Any blocker/high visual defect must override green XML/brand/design manifests. If the automated gates remain green for a visible failure, treat that as a gate-coverage defect and add a regression check before publishing.

## Node notes

Minimal local script shape:

```js
const fs = require('fs');
const path = require('path');
const JSZip = require('jszip');
const ds = '/opt/atlas/skills/creative/psiii-design';
function load(p) { return fs.readFileSync(p, 'utf8'); }

eval(load(path.join(ds, 'templates/business-pptx/finalize-pptx.js')));
eval(load(path.join(ds, 'templates/business-pptx/build-pptx.js')));
eval(load(path.join(ds, 'templates/business-pptx/build-deck.js')));

const { pptx, html } = await buildBrandDeck({
  JSZip,
  templateBytes: fs.readFileSync(path.join(ds, 'templates/business-pptx/source.pptx')),
  slides,
  assetsBase: ds,
  title: 'Deck title',
});
const bytes = new Uint8Array(await pptx.arrayBuffer());
const brand = await assertBrandPptx({ JSZip, bytes });
const discipline = await assertDesignDiscipline({ JSZip, bytes });
if (!brand.ok || !discipline.ok) throw new Error('PPTX gate failed');
```

`build-deck.js` references `buildBrandPptx` as a free symbol, so keep the three `eval(...)` calls in the same scope. Splitting them into isolated modules is a pointless way to create ghosts.

## Cover/footer metadata pitfall

The native title/final layouts have separate bottom placeholders for `name` and `role`. They are visually close. If both strings are long, Quick Look/PowerPoint can render them as overlapping lines even when `assertBrandPptx` and `assertDesignDiscipline` pass. Keep `name` short and put only one compact positioning/role line into `role`; move long framing copy into a thesis/content slide instead of forcing it into the cover footer. Visual QA must explicitly check these bottom metadata lines for overlap.

## Logo/rendering pitfall

If a logo area renders as an empty outlined square or otherwise looks wrong in Quick Look/PowerPoint:

- do not trust `assertBrandPptx` alone — this is a visual renderer issue outside the invariant set;
- check whether the source layout already contains a placeholder/picture at the logo coordinates and whether the generated slide adds another picture on top;
- prefer replacing/removing the layout's existing logo picture rather than blindly stacking another one;
- if SVG embedding produces a blank square in the renderer, rasterize the mark to PNG and target the relationship to the PNG media;
- rerun both gates and the visual thumbnail check after the fix.

### Safe OOXML rewrite for layout SVGs

The PSIII title/final layouts may encode the mark as an SVG extension rather than a normal image reference:

```xml
<a:blip>
  <a:extLst>
    <a:ext>
      <asvg:svgBlip r:embed="rId5"/>
    </a:ext>
  </a:extLst>
</a:blip>
```

Some renderers show only an empty square even though both brand/design gates pass. The narrow compatibility rewrite is:

1. Resolve `rId5` through the owning layout's `_rels/slideLayoutN.xml.rels`.
2. Convert the referenced SVG bytes to PNG (for example with `sharp(svg).png().toBuffer()`).
3. Add the PNG under `ppt/media/` and point that relationship at the `.png` target.
4. Replace **only the exact non-self-closing `<a:blip>...<asvg:svgBlip r:embed="rId5"/>...</a:blip>` block** with `<a:blip r:embed="rId5"/>`.
5. Ensure `[Content_Types].xml` contains the PNG default, then run full OOXML integrity validation, both PSIII gates, and Quick Look/PowerPoint rendering.

Do **not** use a broad expression such as `<a:blip[^>]*>[\s\S]*?</a:blip>` across an entire layout. Layouts also contain self-closing `<a:blip r:embed="..."/>` nodes; a broad match can start at one of those and consume unrelated XML through the next closing tag, producing malformed layouts (for example an opening/closing mismatch near an OLE object). Match the SVG extension block by relationship id, or use an XML parser.

This is not a license to hand-edit random slide geometry. It is a narrow last-mile fix for a visible export artifact after the canonical build path already passed.