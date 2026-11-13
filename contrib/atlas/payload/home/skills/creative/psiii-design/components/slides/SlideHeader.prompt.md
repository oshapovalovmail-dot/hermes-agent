The top safe-area bar of a content slide — a left label and the small dark Yandex «Я» corner mark, positioned in the 20px margin.

```jsx
<SlideFrame inset={false}>
  <SlideHeader left="Иконки" />
  {/* … slide content … */}
  <div style={{ position: "absolute", left: 20, right: 20, bottom: 20 }}>
    <SlideFooter right="07" />
  </div>
</SlideFrame>
```

- `left`: the header label (section name). `mark={false}` hides the corner mark.
- Designed to sit absolutely inside a `SlideFrame` with `inset={false}`.
