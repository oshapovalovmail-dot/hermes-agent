Brand marks for Яндекс · Поисковые сервисы и ИИ — round «Я» mark, Yandex wordmark, and the ПСиИИ wordmark; recolorable for dark or photo backgrounds.

```jsx
<Logo kind="yandex" height={48} />
<Logo kind="mark" height={40} />
<Logo kind="psiii" height={56} />
<Logo kind="mark" tone="dark" height={40} />   /* small ink corner mark */
<Logo kind="psiii" tone="light" height={48} /> /* on a dark slide */
```

- `kind`: `"mark"` (round red «Я»), `"yandex"` (wordmark + red «Я»), `"psiii"` (ПСиИИ wordmark).
- `tone`: `"brand"` (default, original colors), `"dark"` (solid ink #1F1F20), `"light"` (solid white).
- Size with `height` **or** `width` — the other is derived from the aspect ratio.
- The brandbook places the small `tone="dark"` mark in the top-right safe area and the Yandex/ПСиИИ wordmark in the top-left header.
