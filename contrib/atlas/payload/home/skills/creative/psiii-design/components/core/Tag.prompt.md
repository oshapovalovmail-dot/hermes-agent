A small pill label / chip — slide metadata, filters, category labels. Flat, YS Text Medium, 32px tall.

```jsx
<Tag>Поиск</Tag>
<Tag tone="accent">Новое</Tag>
<Tag tone="dark" iconLeft={<Icon name="sparks" size={16} />}>ИИ</Tag>
<Tag tone="outline" radius={0}>Примечание</Tag>
```

- `tone`: `neutral` · `dark` · `accent` · `outline`.
- `radius={0}` makes a hard-edged label instead of a pill.
