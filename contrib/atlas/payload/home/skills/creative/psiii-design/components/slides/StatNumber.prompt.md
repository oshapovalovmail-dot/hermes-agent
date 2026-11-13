A big display metric with an optional caption — the deck pattern for figures ("24%" + a one/two-line подпись). YS Display Cond Heavy, ultra-tight leading.

```jsx
<StatNumber value="24%" caption="Подпись в одну, две или в несколько строк" />
<StatNumber value="10%" accent size={220} />
<StatNumber value="3,4 млн" caption="активных пользователей" align="center" />
```

- `accent` puts the figure in Yandex red — use for the one number that matters.
- `size` is the figure size in px (slide pixels). Captions use `--text-muted`.
