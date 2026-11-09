# Отдельная установка Hermes и native memory providers

## 1. Исполняемые команды

`HERMES_HOME` отделяет данные, **но не Python dependencies**. Нужны новый checkout, собственный PM runtime и новая PM-selected Python environment. Все команды ниже выполняются в отдельном Bash-процессе, не в shell активного gateway. Не используйте найденный в старом `PATH` голый `hermes`, `pip` или `uv`.

Ниже — локальный воспроизводимый вариант для текущего проверенного dirty snapshot форка. Исходный checkout и существующие интерпретаторы используются только для чтения; `.provider-sources`, пользовательские данные, веса и secrets не копируются. `ROOT` должен быть **новым**. `BOOT` — уже существующий Python 3.11+ только для запуска native PM, не целевое окружение Hermes. `TOOL_STORE` — проверенный локальный кэш PM; native `stage_tools` проверяет и копирует Python/uv в новый runtime, не переиспользует старую venv.

```bash
bash --noprofile --norc
set -euo pipefail
export SOURCE=/absolute/path/to/verified/hermes-agent
export ROOT="$HOME/.local/share/hermes-memory-agent"
export STACK="$HOME/.local/share/hermes-memory-stack"   # already prepared and checked
export BOOT=/absolute/path/to/bootstrap-python
export TOOL_STORE=/absolute/path/to/verified-pm-tool-store
export MODE=both                       # honcho | openviking | both
case "$MODE" in honcho|openviking|both) ;; *) exit 2 ;; esac
test ! -e "$ROOT"
mkdir -m 700 "$ROOT"
mkdir "$ROOT/os-home" "$ROOT/tmp" "$ROOT/cache"
unset VIRTUAL_ENV PYTHONHOME PYTHONPATH __HERMES_ACTIVATED
unset HERMES_INSTALL_ROOT HERMES_BUNDLED_PLUGINS HERMES_ENABLE_PROJECT_PLUGINS
unset HERMES_PROFILE HERMES_SAFE_MODE HERMES_PM_RUNTIME
export HOME="$ROOT/os-home"
export HERMES_HOME="$STACK/hermes-home"
test -f "$HERMES_HOME/config.yaml"
export HERMES_RUNTIME_DIR="$ROOT/runtime"
export XDG_CACHE_HOME="$ROOT/cache"
export TMPDIR="$ROOT/tmp"
export PYTHONDONTWRITEBYTECODE=1
export REPO="$ROOT/checkout"

git clone --no-hardlinks "$SOURCE" "$REPO"
# Clone transfers the commit, not dirty changes. Apply only tracked changes:
git -C "$SOURCE" diff --binary HEAD > "$ROOT/snapshot.patch"
git -C "$REPO" apply "$ROOT/snapshot.patch"
# Copy only this explicitly reviewed public source subtree:
"$BOOT" - <<'PY'
import os, shutil
from pathlib import Path
source, repo = Path(os.environ['SOURCE']), Path(os.environ['REPO'])
for p in (source/'integrations/memory-stack').rglob('*'):
    if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.env'):
        q = repo/p.relative_to(source)
        q.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, q)
PY
cd "$REPO"
export PYTHONPATH="$REPO"
"$BOOT" - <<'PY'
import os
from pathlib import Path
from pm.build_operations import stage_tools
stage_tools(['python', 'uv'], source_store=Path(os.environ['TOOL_STORE']),
            out=Path(os.environ['HERMES_RUNTIME_DIR']), target='darwin-arm64')
PY
# Fresh base environment via native PM, not raw pip/uv.
"$BOOT" -m pm.build_env --source "$REPO" --out "$ROOT/base-env" \
  --python "$BOOT" --cache "$ROOT/cache/pm" --explicit
export BASE_PY="$ROOT/base-env/bin/python"

case "$MODE" in
  honcho) SELECTED=(honcho) ;;
  openviking) SELECTED=(openviking) ;;
  both) SELECTED=(honcho openviking) ;;
esac
for provider in "${SELECTED[@]}"; do
  test -f "$HERMES_HOME/plugins/$provider/plugin.yaml"
done
# Preserve installer-owned plugin patches and exact backend connections.
# Do not reconstruct plugins or overwrite this generated configuration.
"$BASE_PY" - "${SELECTED[@]}" <<'PY'
import json, os, sys
from pathlib import Path
home = Path(os.environ['HERMES_HOME'])
names = sys.argv[1:]
config = json.loads((home/'config.yaml').read_text())
if config['memory']['providers'] != names:
    raise SystemExit('MODE differs from the prepared backend selection')
import pm
from pm.plugin_inputs import Candidates
pm.sync_venv([], plugins=Candidates([home/'plugins'/n for n in names]), explicit=True)
PY
# sync publishes a NEW generation; BASE_PY does not switch automatically.
export HERMES_ENV="$("$BASE_PY" -c 'from pm.paths import repo_root; from pm.environments import selected_venv; print(selected_venv(repo_root()))')"
export HERMES_BIN="$HERMES_ENV/bin/hermes"
export HERMES_PY="$HERMES_ENV/bin/python"
export PATH="$HERMES_ENV/bin:$PATH"
hash -r
```

Для **опубликованного** snapshot первые clone/diff/copy команды заменяются обычным `git clone https://github.com/oshapovalovmail-dot/hermes-agent.git "$REPO"` и checkout заранее проверенного **полного commit SHA**. Не полагайтесь на upstream NousResearch: ordered `memory.providers` — изменение этого форка. Ни clone текущего HEAD без dirty diff, ни копирование одной папки `integrations/` в старую установку не воспроизводят проверенный snapshot.

PM устанавливает только клиентские зависимости в новое selected environment.
Этот раздел использует **уже подготовленные** `STACK/hermes-home/plugins` и настройки
backend из установщика; не заменяйте их повторной установкой из catalog.
Нужны отдельные checkout, runtime и venv вне `STACK` и вне исходного checkout.
`BOOT` и `TOOL_STORE` — явные prerequisites native PM: существующий bootstrap Python
и проверенный store с Python/uv для `darwin-arm64`. Команды реально упражнялись
на macOS arm64; другие платформы требуют своего target/store и отдельной проверки.
Повторный backend `prepare` на существующий каталог не запускается.

`source ./activate` — другой штатный developer workflow: запускает setup runtime-only, синхронизирует `all` и test environment, создаёт checkout-scoped shell function. Он не нужен поверх приведённого минимального PM build. Здесь явный `HERMES_BIN` важнее активации и защищает от случайного вызова установленного рабочего Hermes.

Не считайте `hermes plugins validate --install-deps` способом изоляции: команда меняет **выбранную установку PM**, а не создаёт её. В этом recipe dependencies уже provisioned через native `pm.sync_venv`; validation ниже — без `--install-deps`.

## 2. Проверка без backend lifecycle

Продолжайте в том же shell с теми же `HERMES_HOME`, `HERMES_RUNTIME_DIR`, `HERMES_BIN` и `HERMES_PY`. Не выполняйте `hermes` без аргументов, `chat`, `gateway`, memory setup, `initialize`, `is_available`, backend API/autostart или service checks.

```bash
test -x "$HERMES_BIN"
test "$(command -v hermes)" = "$HERMES_BIN"
"$HERMES_PY" - <<'PY'
import json, os, sys, shutil, hermes_cli, pm
from hermes_constants import get_hermes_home
assert sys.prefix != sys.base_prefix
assert sys.prefix.startswith(os.environ['ROOT']+'/')
assert sys.base_prefix.startswith(os.environ['HERMES_RUNTIME_DIR']+'/')
assert str(get_hermes_home()) == os.environ['HERMES_HOME']
assert shutil.which('hermes') == os.environ['HERMES_BIN']
assert hermes_cli.__file__.startswith(os.environ['REPO']+'/')
print(json.dumps({'python':sys.executable,'prefix':sys.prefix,
 'base_prefix':sys.base_prefix,'cli':hermes_cli.__file__,
 'pm':pm.__file__,'home':str(get_hermes_home()),
 'HERMES_BIN':os.environ['HERMES_BIN']}, indent=2))
PY
"$HERMES_BIN" --help > "$ROOT/cli-help.log"
"$HERMES_BIN" config path
for provider in "${SELECTED[@]}"; do
  "$HERMES_BIN" plugins validate "$HERMES_HOME/plugins/$provider" --json \
    > "$ROOT/validate-$provider.json"
done
"$HERMES_PY" - "${SELECTED[@]}" <<'PY'
import inspect, json, os, socket, sys
# Guard: factory/schema registration must not access even loopback.
def blocked(*a, **k):
    raise AssertionError('Network forbidden in registration-only probe')
socket.socket.connect = blocked
socket.create_connection = blocked
from plugins.memory import find_provider_dir, load_memory_provider
rows=[]
for name in sys.argv[1:]:
    path=find_provider_dir(name)
    assert path and str(path).startswith(os.environ['HERMES_HOME']+'/plugins/')
    provider=load_memory_provider(name, register_skills=False)
    assert provider is not None
    schema=provider.get_config_schema()
    assert schema
    rows.append({'name':provider.name,'module':inspect.getfile(type(provider)),
                 'schema_keys':[x['key'] for x in schema]})
print(json.dumps({'loaded':rows,'initialize_called':False},indent=2))
PY
```

Регистрация/schema и validation не вызывают backend initialize и не доказывают
capture, recall или derivation. Эту границу проверяют отдельно: законченный ход
новой сессии, затем независимое чтение и завершённая обработка из каждого backend.
Validation предупреждает о private core imports текущих плагинов; verdict `host`
означает совместимость plugin host, а не отдельную установку Python.

Команды native PM build/sync, path/prefix checks и registration probes проверены
в отдельных окружениях без изменения рабочего агента. Основной пример сохраняет
backend-конфигурацию, уже созданную установщиком. После всех backend-проверок
модель/авторизация основного Hermes настраиваются только через `HERMES_BIN` и этот
`HERMES_HOME`; ключи backend-памяти не являются авторизацией модели самого агента.
Рабочий gateway не запускается и не перезапускается этими командами.
