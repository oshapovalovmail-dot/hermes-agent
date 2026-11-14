# Приёмка dialogue/self/Arcanum repair: переносимый payload

## Статус и границы

**Переносимый payload и целевые offline-регрессии: PASS. Проверка операторской
установки: PARTIAL. Публикация нового состояния ещё не подтверждена.**

В операторской установке отдельно проверены настоящие вызовы модели и доставка
ответов в исходную приватную тему. После уточнения команды модель использовала
transport username, разрешила Staff-профиль и подтвердила членство сотрудника,
не запрашивая повторно рабочий логин владельца. Ограниченный ответ по Tracker
прошёл независимую проверку содержимого, авторства и дат; точное чтение PR через
alias также прошло, метаданные совпали с доставленным ответом.

Полнота недельной PR/review-активности не установлена: фильтрованный поиск вернул
`UPSTREAM_ERROR`, и ответ явно сохранил это ограничение вместо утверждения об
отказе ACL. Live-тему создал бот; owner service-only ветка покрыта SDK-регрессиями,
но этим созданием не проверена. Полная сервисная матрица и многопользовательский
пилот остаются отдельными незавершёнными проверками. Это свидетельство конкретной
установки, а не гарантия запуска на новом хосте или полного исследования.

Полные приватные свидетельства и независимое заключение сохранены родителем вне
публичного дистрибутива. Переносимый source-only этап не менял production и не
использовал credentials; последующую установку и live-проверки выполнял родитель.
Native-core patch, исходники payload и общие manifests фиксируются отдельно.

## Перенесённый контракт

- `payload/home/plugins/qyp_guard/__init__.py`: точные reviewed bytes. `qyp_role`
  захватывает исходный Binding перед авторизацией и повторно проверяет binding object,
  профиль, непустую session и полный principal. Только canonical username исходного
  проверенного DM; в группе `null`. Это бизнес-метаданные, а не Staff login/полномочия.
- `work_services_manifest.json`: только точный селектор
  `search_by.telegram_accounts.value_lower`, lowercase ASCII 1..32 со строгим концом.
  Закрытые schemas, прежние селекторы и маршрутизация сохранены.
- `work_services_backend.py`: только MANIFEST_SHA256 пересчитан по публичному manifest.
  В sidecar пересчитаны только work_services sha256/catalog_sha256 по PUBLIC bytes.
  `/usr/bin/false`, `/nonexistent`, пустые ARC_ROOTS/GITHUB_REPOS остаются
  deny-default operator bindings. Tracker, extensions, paging и dependency pins сохранены.
- `sidecar.py`: только две reviewed функции `parse_pr`/`ReadService.pr_read` плюс
  указанная pin-chain. Два точных HTTPS review aliases; request и native metadata
  валидируются независимо до сопоставления provider/ID. Никакого исправления URL,
  расширения namespace или обхода whole-patch ACL.
- `templates/SOUL.md`: единственный canonical SOUL source проекта совпал с frozen
  baseline и заменён byte-identically reviewed кандидатом. Старые privacy/security
  абзацы сохранены; добавлены self/team resolution и исследование работы по источникам.

## Доказательства

`qualification/dialogue_repair/public-evidence/green-receipt.json` и три `green-*.log`
в том же каталоге содержат публикационные копии свидетельств. Пути хоста заменены
переносимыми обозначениями; команды в этих копиях — рецепты с параметрами, а не
дословные исходные argv. Полные исходные GREEN/RED receipts и логи сохранены
родителем вне публикуемого проекта без изменения байтов. Хэши логов в публичных
receipts относятся к публичным копиям; исходные хэши указаны отдельно.

Наборы проверок:

| Набор | Методов | Exit |
|---|---:|---:|
| Real Service/AdmissionGate/validators, synthetic Staff/bot | 23 | 0 |
| Actual public sidecar, synthetic operator ACL/native runner | 7 | 0 |
| Public pins/bindings/unchanged seam/SOUL/native fixture | 5 | 0 |

Всего 35 методов. Тесты identity и Arcanum сохраняют классы reviewed leaf tests;
меняется только portable harness. Admission/session — два замороженных source fixture,
не установленный runtime. Identity копирует только четыре нужных plugin-модуля во
временный task-owned каталог и удаляет его; services импортируются прямо из payload.
Arcanum fixture задаёт ACL только в памяти тестового модуля; исходный payload остаётся
с пустыми ACL. Нативные команды не запускаются, runner полностью синтетический.

`red-receipt.json`: causal baseline RED — identity 23 метода, 25 assertion failures;
Arcanum 7 методов, 29 failures/14 ожидаемых PolicyError из непринятого alias;
seam 5 методов, один failure на старом SOUL. Все три exit 1 до переноса исходников.
Предыдущие launcher failures не скрыты: `validation-env-red-*` (нет telegram) и
`production-env-red-*` (нет jsonschema). Ни один environment не устанавливался и не
менялся на диске. Успешный запуск использовал existing validation Python 3.14 и
read-only PYTHONPATH существующего production site-packages для telegram.
Это композиция уже установленных зависимостей, не самодостаточная новая среда.

Повторить из project root с существующим Python, где доступны telegram/jsonschema:

```sh
"$PYTHON" -B qualification/dialogue_repair/run_qualification.py --phase green
# Если пакеты разделены между существующими средами той же Python ABI:
"$PYTHON" -B qualification/dialogue_repair/run_qualification.py --phase green \
  --dependency-path "$EXISTING_DEPENDENCY_SITE"
```

Runner передаёт закрытый allowlist environment, не наследует session identity или
credentials; фактические команды, cwd, exits, hashes тестов/логов находятся в receipts.
`public-baseline.json` — локальное свидетельство только изменённого seam, не новый
общий distribution manifest. Побайтовая обратная проверка backend/sidecar подтверждает,
что за исключением reviewed функций и двух work pins public baseline не изменён.

## Public SHA256

| Путь | SHA256 |
|---|---|
| payload/home/plugins/qyp_guard/__init__.py | 252ab26d426bd9e5894e0b3bb4d95966be078737fa062d53630cef34de7e4dd2 |
| payload/services/atlas-read/work_services_manifest.json | 2217163c4309f855ddeeb7854e9c9770235a33c200285663e779b800e98ef8fb |
| payload/services/atlas-read/work_services_backend.py | 564b42ecdee85fa9f1e2adbf18c7870ae79bbca8f49193ba6e5b0a1b83131990 |
| payload/services/atlas-read/sidecar.py | 979814343c059d3b801ea5506ca18a8d24a6d277fff3978cd192d3c7c2e8805e |
| templates/SOUL.md | a94a372391f4a628dc3cbf5c1dc5f3334f677477884ebe4451298e2888d1ee13 |

## Реестр приёмки и продолжение

- Source/test: PASS, точный публичный seam, 35 offline методов.
- Publication: PENDING, родительская задача; commit/push не выполнялись.
- Disk installation/process activation: не выполнялись этим переносом; отдельные receipts родителя.
- Live behavior: PENDING; source-тесты не являются model acceptance.
- Final delivery этого подзадания: case `publication/payload-result.json`.
- Continuation owner: родительская задача session `20261114_120821_a636ea`;
  фоновых процессов у этого source-переноса нет. Native edge, архивирование и
  финальные distribution manifests остаются вне этого изменения.
