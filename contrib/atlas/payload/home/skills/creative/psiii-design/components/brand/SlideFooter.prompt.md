The standard ПСиИИ slide footer — a 15px, 50%-opacity line pinned in the bottom safe area: business-group label left, brandbook year or page number right.

```jsx
<SlideFooter />                                   /* default brandbook footer */
<SlideFooter right="07" />                         /* page number on a deck slide */
<SlideFooter label="Поисковые сервисы и ИИ" right="" />
```

Pair with `SlideHeader` (top) and place inside a `SlideFrame`. Use on content slides, not on full-bleed title slides.
