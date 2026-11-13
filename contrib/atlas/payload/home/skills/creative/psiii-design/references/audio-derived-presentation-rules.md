# Audio-derived deck-generation rules

Source: 2026-07-29 Zoom discussion about agent-generated presentations. These are general deck-generation rules that complement the ПСиИИ-specific gates.

## Core contract

- Deliver an editable PowerPoint file, not just a visually nice artifact. HTML alone is insufficient for the mass scenario because non-technical users cannot edit it normally.
- Build from a canonical `.pptx` template. Duplicate the template, remove irrelevant demo/section slides, and fill the copy.
- Do not recreate the template from scratch and do not imitate it with free-floating boxes. That is how agents produce decks that look close but break editability, grid, fonts, and theme.
- Use the template’s layouts and placeholder objects for slide chrome, especially titles and footers.
- Titles must land in the native title placeholder. If titles jump, sit at a different x/y, use a different font/weight/size, or appear on the side, the builder probably bypassed placeholders.
- Do not recolor slides or backgrounds unless the chosen canonical layout requires it. Random blue/colored backgrounds are a template-contract violation.

## MVP quality bar

A minimally acceptable deck builder must:

1. Create a copy of the canonical template.
2. Select existing template layouts for each slide.
3. Put titles into the correct placeholders.
4. Preserve template colors, fonts, title positions, and footer/chrome formatting.
5. Remove unused sections from the copied template.
6. Keep title sizing consistent by default. The discussion used 56pt as a practical default; shrink only when a specific title does not fit.
7. Apply typography rules: Russian guillemets (`«…»`), punctuation normalization, no arbitrary terminal periods where style forbids them.
8. Produce native, editable PowerPoint charts with attached Excel data instead of drawing bars from rectangles.
9. Produce editable, styled tables instead of arbitrary line/shape assemblies.
10. Use whitespace deliberately: neither cram everything into one area nor smear content across the canvas.
11. Distinguish stat numbers, subtitles, body text, and key takeaways; highlight key information by style rules, not by random bold/color.
12. Save with a predictable name and version suffix (`v1`, `v2`, …) when iterating.

## Training pattern for agents

- Teach narrowly: one rule cluster at a time.
- Test after each cluster before adding the next one.
- Keep knowledge structured instead of trusting the agent to group it usefully:
  - `SKILL.md` / core: the high-level generation algorithm and hard gates.
  - `references/`: good examples, session-derived lessons, analyzed decks.
  - `guidelines` / `style`: typography, grid, charts, tables, composition.
- Use example decks built in the same template as positive references. Have the agent analyze cards, tables, charts, and element placement from those examples.
- Use a slidebook/guidebook as part of the generation contract, not as optional inspiration.

## Validation checklist

Before delivery, check:

- The source template is the canonical one.
- The output is editable `.pptx`.
- The output preserves template size, theme, fonts, colors, layouts, and guides.
- Every title is in a native title placeholder.
- No slide has an arbitrary background or recoloring.
- Placeholder chrome is inherited from the layout; only body content is freely composed.
- Unused template sections are gone.
- Charts are native PowerPoint chart objects with editable data.
- Tables are editable and match the table style rules.
- Text uses the required typography and line spacing.
- Composition has enough whitespace and consistent alignment.
- The file name is predictable and versioned if there were iterations.

## Pitfall

A deck can pass a superficial visual check and still be product-grade garbage if it is made from free-floating rectangles: titles are not placeholders, charts are fake, tables are not editable, and the next human edit destroys the layout. Treat editability and native PowerPoint structure as first-class quality gates, not polish.
