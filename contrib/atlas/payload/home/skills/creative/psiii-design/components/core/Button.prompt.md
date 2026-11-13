The ПСиИИ interface button — pill-shaped, flat, YS Text Medium. Use `accent` (Yandex red) sparingly; `primary` ink is the default call to action.

```jsx
<Button>Продолжить</Button>
<Button variant="accent">Создать</Button>
<Button variant="secondary">Отмена</Button>
<Button variant="ghost" iconLeft={<Icon name="search" size={18} />}>Найти</Button>
<Button size="l">Большая кнопка</Button>
```

- `variant`: `primary` (ink) · `accent` (red) · `secondary` (gray) · `ghost`.
- `size`: `s` 36 · `m` 48 · `l` 56 px tall.
- `iconLeft` / `iconRight` accept an `<Icon />`. Press darkens slightly; disabled dims to 40%.
