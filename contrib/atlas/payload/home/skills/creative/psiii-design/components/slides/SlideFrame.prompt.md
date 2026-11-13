The fixed 1920×1080 ПСиИИ slide canvas — gives you the background, the always-on column grid, and the standard content inset. Render it inside a deck stage or a scaled card; it draws at native slide pixels.

```jsx
<SlideFrame grid>
  <h2 className="ps-h1">Длинный заголовок в две или больше строк</h2>
</SlideFrame>

<SlideFrame bg="ink" inset={false}>
  {/* position children freely in the 1920×1080 space */}
</SlideFrame>
```

- `bg`: `white` (default) · `ink` · `maroon` · `accent`.
- `grid` overlays the 12-column + safe-area guides (the brandbook's «сетка»).
- `inset={false}` removes the 40px content padding for full-bleed / absolute layouts.
- Compose with `SlideHeader`, `SlideFooter`, `StatNumber`. Use the `.ps-*` type classes for text.
