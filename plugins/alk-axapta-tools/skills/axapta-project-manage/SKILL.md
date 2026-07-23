---
name: axapta-project-manage
description: Управляет структурой папки `XPO/` задачи в Microsoft Dynamics AX 2012 проектах ALK. Раскладывает плоский `xpo/*.xpo` в AOT-структуру (как в `AOT-Prod\Classes\`, `Data Dictionary\Tables\`, `Menu Items\Display\`, `Security\Privileges\` и т.д.) и обратно; сверяет состав задачи с боевой выгрузкой `AOT-Prod`; чистит пустые подпапки и старые сборки в `_release/`. Используй при триггерах «разложи xpo по AOT», «приведи структуру в порядок», «organize / flatten / sync prod / cleanup releases», «коллизия имён Form/Table», «упорядочь файлы как в AOT-Prod», «xpo лежат плоско». ОБЯЗАТЕЛЬНО применяй ПЕРЕД `axapta-project-export`, если структура «грязная» (много файлов в одном корне), — это упрощает навигацию и diff с боевым кодом. НЕ применяй при правке X++ кода — для маркеров мод-комментариев есть `axapta-mod-comments`.
---

# Axapta Project Manage

В проектах ALK Microsoft Dynamics AX 2012 файлы `*.xpo` в папке задачи (`E:\ZeroCoder\LT_DAX-*\xpo\`) могут лежать двумя способами:

- **Плоский layout** (legacy, промежуточное состояние): `xpo\Class_Foo.xpo`, `xpo\Table_Bar.xpo`, `xpo\MenuItemDisplay_Baz.xpo`. Префикс типа в имени файла. Просто, но при 40+ файлах теряется навигация и пропадает прямая сопоставимость с боевой выгрузкой — перед релизом обязательно приводится к AOT layout через `organize`.
- **AOT layout** (обязательный для финальной структуры, см. [axapta-project-export](../axapta-project-export/SKILL.md) §«Папка XPO/ обязательна»): `xpo\Classes\Foo.xpo`, `xpo\Data Dictionary\Tables\Bar.xpo`, `xpo\Menu Items\Display\Baz.xpo`. Имена и пути совпадают с боевой выгрузкой `E:\ZeroCoder\Axapta\ERP\AOT-Prod\`, поэтому `diff` показывает реальные модификации без шума от различий в layout.

Этот скилл управляет переходом между layout-ами, сверкой с боевым кодом и чисткой служебных артефактов.

## Когда применять

**Проактивно**:
- Пользователь притащил «приехавшие плоско» xpo и просит «приведи в порядок», «разложи как у заказчика», «упорядочь файлы».
- Перед сборкой релиза через `axapta-project-export` структура «грязная» — много файлов разных типов в одном корне, без подпапок. Сначала organize → потом сборка.
- Пользователь спрашивает «что мы тут модифицируем, а что новое?» — это `sync`.
- В `_release/` накопилось 20+ старых сборок — это `cleanup --keep N`.

**По явному запросу** — пользователь зовёт навык напрямую, говорит «organize», «flatten», «sync prod», «cleanup».

**НЕ применять**:
- При правке кода — это `axapta-mod-comments`.
- Если структура уже AOT и пользователь не просил пересборку — `organize` идемпотентен, но запускать его без причины не нужно.
- Упаковка Resource / Excel-шаблоны `XMLExcelReport_RU` — это **`axapta-xpo-helper`** (не organize/flatten).

## Preflight ENV-гейт (ПЕРВЫЙ ШАГ — до любых операций)

См. [setup](../setup/SKILL.md) §«Resolve plugin root» и §«Preflight-конвенция».
Сначала разреши `$pluginRoot`, затем перед `organize`/`flatten`/`sync`/`cleanup`:

```powershell
python "$pluginRoot\scripts\XPOTools\Modules\config.py"
```

Ненулевой exit code → **остановись**, покажи пользователю ошибки из stderr, направь на
`/alk-axapta-tools:setup`. Не продолжай без полной конфигурации.

## Исполнители

Все операции — Python-скрипты в `XPOTools/` (бандлирован в плагин —
`"$pluginRoot\scripts\XPOTools\"`, документация — `"$pluginRoot\scripts\XPOTools\README.md"`).

`bin/` **не** добавляется в PATH автоматически; если короткие команды не находятся —
используй Fallback с полным путём через `$pluginRoot`:

```powershell
organize-xpo organize --root .\xpo [--dry-run | --yes] [--keep-prefix]
organize-xpo flatten  --root .\xpo [--dry-run | --yes] [--out <dir>]
sync-xpo --task-root .\xpo [--prod-root <path>] [--bundle <path>] [--with-content-diff]
cleanup-xpo --root .\xpo [--empty-dirs] [--keep N] [--purge] [--dry-run] [--yes]
validate-xpo .\xpo --strict
```

**Fallback при не настроенном PATH**:
```powershell
python "$pluginRoot\scripts\XPOTools\organize-xpo.py" organize --root .\xpo --dry-run
python "$pluginRoot\scripts\XPOTools\sync-xpo.py" --task-root .\xpo
python "$pluginRoot\scripts\XPOTools\cleanup-xpo.py" --root .\xpo --empty-dirs
```

## Источник маппинга

Маппинг «префикс файла → тип объекта → AOT-подпапка» зафиксирован в `"$pluginRoot\scripts\XPOTools\Modules\xpo_types.py"`:

- `group_path` — слитные имена для PRN-блока SharedProject (`MenuItems`, `DataSets`).
- `dir_path` — имена директорий в FS (с пробелами там, где `AOT-Prod` использует пробелы: `Menu Items`, `Data Sets`, `Service Groups`).
- `file_prefix` — префикс для плоского layout (`Class_`, `Table_`, `EDT_`, …).

Это **единственный** источник истины. При появлении нового типа AOT — расширяй `xpo_types.py` (поля `utiltype`, `nodetype`, `group_path`, `dir_path`, `group_type`, `file_prefix`) и таблицу в `axapta-project-export\SKILL.md` §8 одновременно.

## Операция 1: `organize` — плоский → AOT

Перемещает `xpo\*.xpo` в подпапки по типу, удаляет префикс типа из имени файла.

### Алгоритм

1. **Контекст**. Спроси у пользователя путь к корню (`--root`), если он не очевиден из текущей рабочей директории. По умолчанию — `.\xpo` или `.\XPO`.
2. **Dry-run первым делом**:
   ```powershell
   organize-xpo organize --root .\xpo --dry-run
   ```
   Скрипт читает первые 200 строк каждого `*.xpo` из корня, определяет mnemonic (по префиксу имени и/или по `***Element:` из тела), вычисляет целевой путь по `dir_path` из `xpo_types.py`. Выводит:
   - количество файлов и целевых папок,
   - разбивку по типам (CLS, TAB, FTM_DISPLAY, ...),
   - первые 10 примеров перемещения,
   - список `unknown` (если есть — exit 4),
   - список `collisions` (если есть — exit 4).
3. **Покажи пользователю отчёт** и через `AskUserQuestion` спроси:
   - «Применить?» — да/нет/«добавить вручную ещё файлы».
   - Если в `unknown` есть файлы — пользователь должен либо добавить тип в `xpo_types.py`, либо переименовать файл с правильным префиксом.
4. **Применение**:
   ```powershell
   organize-xpo organize --root .\xpo --yes
   ```
5. **Постпроверка**:
   ```powershell
   validate-xpo .\xpo --strict
   ```
   Должно быть 0 errors. Если warns про маркеры `axapta-mod-comments` — это технический долг, не задача organize.

### Параметры

| Флаг | Назначение |
|------|------------|
| `--root <dir>` | Папка задачи XPO/ (обязательно). |
| `--dry-run` | Печать плана, без перемещений. |
| `--yes` | Не спрашивать интерактивное подтверждение. |
| `--keep-prefix` | Оставить префикс типа в имени файла (legacy fallback). По умолчанию префикс удаляется. |

### Anti-patterns

- **Не запускай `--yes` без предварительного `--dry-run` в той же сессии.** Move-операция массовая, ошибка маппинга → 44 файла в неправильных папках.
- **Не трогай `_release/`.** Скрипт его автоматически пропускает, но не запускай organize в `_release/` напрямую.
- **Не модифицируй содержимое файлов.** Operation = только move, BOM/CRLF не меняются.

## Операция 2: `flatten` — AOT → плоский

Обратная операция к `organize`. Перемещает `xpo\Classes\Foo.xpo` обратно в `xpo\Class_Foo.xpo` (или в указанную `--out` папку).

Используй, когда:
- Нужно передать файлы в инструмент, не умеющий AOT-layout (legacy build-скрипт, не обновлённый под рекурсивный glob).
- Round-trip-проверка корректности маппинга `xpo_types.py`: `organize → flatten` должен дать идентичный набор имён.

### Алгоритм

```powershell
organize-xpo flatten --root .\xpo --dry-run                 # in-place в xpo\
organize-xpo flatten --root .\xpo --out .\xpo-flat --yes    # копия в xpo-flat\
```

Скрипт:
1. Рекурсивно сканирует `--root` (исключая `_release/`).
2. Для каждого файла:
   - Определяет mnemonic по `***Element:` из тела; fallback — по родительской папке через обратный индекс `DIR_PATH_INDEX`.
   - Для `***Element: FTM` подтип определяется ТОЛЬКО по родительской папке (`Menu Items/Display` → `FTM_DISPLAY`), потому что в теле подтип не пишется как `Type #...`.
   - Новое имя = `file_prefix + path.stem + ".xpo"`.
3. Перемещает (`shutil.move`).
4. Если `--out` не задан или равен `--root` — после move удаляет пустые подпапки.

### Anti-patterns

- **Не flatten после правок.** Если ты только что добавил новый объект в AOT-структуру, сначала проверь `validate-xpo .\xpo --strict`, потом flatten. Иначе ошибка type-detection (например, отсутствует `***Element:` в теле) приведёт к потере файла.

## Операция 3: `sync` — сверка с AOT-Prod

Read-only сравнение по `(canonical_mnemonic, object_name)`:

```powershell
sync-xpo --task-root .\xpo
sync-xpo --task-root .\xpo --bundle .\xpo\_release\SharedProject_*.xpo
sync-xpo --task-root .\xpo --with-content-diff
```

Если `--prod-root` не указан — берётся из ENV-переменной `AX_AOT_PATH` (обязательна, задаётся через скилл `/alk-axapta-tools:setup`; без неё и без явного `--prod-root` команда завершится ошибкой).

Если `--bundle` не указан — автоматически берётся самый свежий `SharedProject_*.xpo` из `<task-root>/_release/`.

### Что показывает

- **NEW** — объекты задачи, которых нет в Prod → свежие разработки.
- **MODIFICATIONS** — есть и в задаче, и в Prod с тем же именем → правки боевого кода. **Подсказка**: в этих файлах должен быть маркер `axapta-mod-comments`. Если маркера нет — `validate-xpo --strict` подсветит warning, а сейчас (после sync) — это сигнал «проверь маркер вручную».
- **MISSING IN TASK** — упомянуты в bundle, но нет в исходниках задачи → потерянные файлы. Это потенциальная регрессия (можно восстановить через `split-shared-project --layout aot`).

Exit code: 0 (всё ок), 1 (есть MISSING IN TASK).

### С `--with-content-diff`

Для каждой Modification выводит первые ~50 строк `unified_diff` task vs prod (ограничение по строкам, не подаёт весь файл). Полезно для быстрой проверки «что именно мы поменяли».

## Операция 4: `cleanup` — пустые папки и старые релизы

```powershell
cleanup-xpo --root .\xpo --empty-dirs --dry-run
cleanup-xpo --root .\xpo --empty-dirs --yes
cleanup-xpo --root .\xpo --keep 5 --dry-run
cleanup-xpo --root .\xpo --keep 5 --yes              # → _release\_archive\
cleanup-xpo --root .\xpo --keep 5 --purge --yes      # → физическое удаление
```

### Поведение

- **`--empty-dirs`**: рекурсивно удаляет пустые подпапки внутри `--root`. `_release/` и его потомки исключаются (даже пустой `_release/` сохраняется).
- **`--keep N`**: в `_release/` оставляет N последних `SharedProject_*.xpo` (по mtime). Лишние **перемещаются в `_release/_archive/`** — безопасно. С `--purge` — физическое удаление; в этом случае без `--yes` скрипт дополнительно требует подтверждение через `input`.
- Без флагов — печать «ничего не делаю».

### Anti-patterns

- **`--purge` без `--keep`** не имеет смысла — флаг работает только в паре.
- **Не запускай `cleanup` посреди работы над задачей**, пока ещё неизвестно, какой релиз станет финальным.

## Workflow: типовой сценарий перед сборкой релиза

```powershell
# 1. Привести структуру в порядок
organize-xpo organize --root .\xpo --dry-run
organize-xpo organize --root .\xpo --yes

# 2. Валидация (BOM/CRLF/balance/mojibake/markers/layout-consistency)
validate-xpo .\xpo --strict

# 3. Сверка с боевым (опционально, перед финальным релизом)
sync-xpo --task-root .\xpo --bundle <последняя сборка из _release>

# 4. Чистка старых релизов (опционально)
cleanup-xpo --root .\xpo --keep 5 --dry-run
cleanup-xpo --root .\xpo --keep 5 --yes

# 5. Сборка финального бандла
build-shared-project --root .\xpo --project-name ALK_DEVAX12_<TICKET>_<NICK> --dry-run
build-shared-project --root .\xpo --project-name ALK_DEVAX12_<TICKET>_<NICK> --yes
```

## Подтверждение перед деструктивом

Все операции, кроме `sync` и `cleanup --dry-run`, **деструктивны** (move/delete). Цепочка обязательна:

1. `--dry-run` → вывести отчёт.
2. Через `AskUserQuestion` показать пользователю сводку («N файлов в M папок, K коллизий, L unknown») и спросить «Применить? / Отменить / Изменить?».
3. Только после положительного ответа — `--yes`.

Никогда не запускай `--yes` напрямую без `--dry-run` в той же сессии.

## Эталонные пути

- **Боевая выгрузка (read-only)**: [E:\ZeroCoder\Axapta\ERP\AOT-Prod](file:///E:/ZeroCoder/Axapta/ERP/AOT-Prod) — эталон AOT-структуры. Никогда не модифицируем.
- **Пример типовой задачи (AOT-layout)**: [E:\ZeroCoder\LT_DAX-Verme\xpo](file:///E:/ZeroCoder/LT_DAX-Verme/xpo) — 44 файла, разложены через `organize-xpo`, 10 подпапок.
- **Источник маппинга**: `"$pluginRoot\scripts\XPOTools\Modules\xpo_types.py"`.

## Связи с другими скиллами

- **`axapta-mod-comments`** — проставляет маркеры в коде. Запускается при правке `.xpo`, не пересекается с `axapta-project-manage`.
- **`axapta-project-export`** — финальная сборка бандла. **Обязательно** прогонять `organize-xpo organize` + `validate-xpo --strict` ПЕРЕД сборкой — AOT-раскладка обязательна для финальной структуры (см. [axapta-project-export](../axapta-project-export/SKILL.md) §«Папка XPO/ обязательна»). `build-shared-project` технически соберёт и из плоского layout (рекурсивный glob был добавлен в рамках этой инфраструктуры), но это не заменяет приведение к AOT перед релизом.

## Anti-patterns (общие)

- **Не трогать AOT-Prod.** Это эталон, read-only. Все правки — в папке задачи.
- **Не перемещать файлы между задачами.** Каждая задача — отдельная папка `LT_DAX-*\xpo\`.
- **Не путать `dir_path` (FS) и `group_path` (PRN).** Это разные пространства имён (`Menu Items` vs `MenuItems`). Используй утилиту `dir_path_for(mnemonic)` из `xpo_types.py`.
- **Не править `xpo_types.py` руками без обновления `axapta-project-export\SKILL.md` §8.** Таблица UTILTYPE/NODETYPE/group_path должна синхронизироваться.
- **Не запускать `organize` поверх уже AOT-разложенной структуры без `--dry-run`.** Идемпотентность гарантирована (плоский корень будет пуст → moves=0), но проверка обязательна.
- **Не игнорировать errors `validate-xpo` после organize.** Каждый error означает либо ошибку миграции, либо реальную проблему файла (BOM/CRLF/balance/layout-mismatch).
