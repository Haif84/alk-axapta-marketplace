# XPOTools

Общий инструментарий для сборки/проверки/разбора xpo-файлов
Microsoft Dynamics AX 2012 (X++).

## Состав

| Команда | Что делает |
|---------|------------|
| `build-shared-project` | Собирает финальный `SharedProject_*.xpo` (AOT Project + тела всех его объектов) из папки `XPO/*.xpo`. |
| `build-resource-xpo` | Собирает AOT `Resource` `.xpo` из бинарника (xlsx и др.) с корректным BINARY-wrapper (`FF FF FF`). |
| `validate-xpo` | Проверяет xpo-файлы: BOM+CRLF, балансировка блоков, mojibake, наличие маркеров модификаций, уникальность имён объектов, формат блока `INDICES` (без обёрток `INDEX`/`ENDINDEX`), предел длины имени объекта (40). Флаг `--project-code` перекрывает `AX_PROJECT_ID` для проверки маркеров. |
| `split-shared-project` | Обратная операция к `build-shared-project`: нарезает бандл обратно на отдельные `<Type>_<Name>.xpo`. |
| `organize-xpo` | Раскладывает плоские `xpo/*.xpo` по AOT-структуре (`Classes/`, `Data Dictionary/Tables/`, …) и обратно (flatten). |
| `sync-xpo` | Сверяет состав задачи с боевой выгрузкой AOT-Prod. |
| `cleanup-xpo` | Чистит пустые подпапки и старые сборки в `_release/`. |
| `fix-mojibake` | Чинит файлы с двойной перекодировкой CP1251↔UTF-8. |

Внутренние модули — в [Modules/](Modules/), обёртки командной строки — в [bin/](bin/).

## Установка

Через плагин `alk-axapta-tools` (основной путь) — конфигурация задаётся ENV-переменными
через скилл `/alk-axapta-tools:setup` (см. `../setup-env.ps1`), PATH не требуется.
Корень плагина: `$env:CLAUDE_PLUGIN_ROOT`, иначе новейшая папка в
`%USERPROFILE%\.claude\plugins\cache\alk-axapta\alk-axapta-tools\*`, иначе поиск
`alk-axapta-tools` под `%USERPROFILE%\.cursor\plugins\` (см. скилл `setup`
§«Resolve plugin root»). Команды: `"$pluginRoot\scripts\XPOTools\..."`.

Standalone-клон (вне плагина):

```powershell
git clone <repo-url> "$env:USERPROFILE\.claude\scripts\XPOTools"
cd "$env:USERPROFILE\.claude\scripts\XPOTools"
Copy-Item config.example.json config.local.json
notepad config.local.json   # заполни AX_USER_NICK и т.п.
```

Автоматического добавления `XPOTools/bin` в PATH сейчас нет (ранее это делал `setup.ps1`,
удалён как неиспользуемый и оставлявший ложное впечатление, что PATH настраивается сам —
известное открытое ограничение). Пока не восстановлено — вызывай команды через полный путь
или добавь `bin/` в `$env:PATH` вручную.

## Обновление

```powershell
cd "$env:USERPROFILE\.claude\scripts\XPOTools"
.\update.ps1
```

`update.ps1` делает `git pull --ff-only` и предупреждает, если `config.example.json` получил новые ключи, не отражённые в `config.local.json`.

## Конфигурация

Источники значений по убыванию приоритета:

1. `.axapta.json` в папке проекта (ищется вверх от текущей директории) — перекрывает
   всё остальное; нужен репозиториям, чья модификация ведётся не под глобальным кодом
   проекта. Задаёт только перекрываемые ключи; пустая строка значима
   (`"AX_OBJECT_PREFIX": ""` гасит унаследованный из ENV префикс). Аффикс — в мемберной
   форме (`"_cdt"`, `"alk_"`). См. скилл `setup` §«Конфиг уровня проекта».
2. Переменные окружения `AX_PROJECT_ID`, `AX_USER_NICK`, `AX_AOT_PATH`, `AX_OBJECT_PREFIX`,
   `AX_OBJECT_SUFFIX`.
3. `config.local.json` (gitignored).
4. `config.example.json` (под git, плейсхолдеры).

Обязательны `AX_PROJECT_ID`, `AX_USER_NICK` и ровно один из
`AX_OBJECT_PREFIX`/`AX_OBJECT_SUFFIX`; `AX_AOT_PATH` опционален — нужен только
`sync-xpo`, который сам сообщает об отсутствии пути;
`Modules/config.py` вызванный напрямую (`python Modules/config.py`) проверяет это и
возвращает ненулевой exit code при неполной конфигурации — используется как preflight-гейт
в скиллах плагина.

В коде нет ALK-специфичных литералов — всё через [Modules/config.py](Modules/config.py).

## Требования

- Python ≥ 3.9
- PowerShell 5.1+ (для wrapper'ов в `bin/`) или cmd.exe
- Git (для `update.ps1`)

## Примеры

```powershell
# Сборка финального бандла (шаблон имени: <ProjectId>_<ModCode>_<UserNick>)
build-shared-project --root .\XPO --project-name ALK_DEVAX12_DAX_012345_akaz --dry-run
build-shared-project --root .\XPO --project-name ALK_DEVAX12_DAX_012345_akaz --yes

# Валидация
validate-xpo .\XPO --strict
# ...с кодом проекта, отличным от глобальной ENV (см. --project-code)
validate-xpo .\XPO --strict --project-code CIT000

# Разбор бандла обратно
split-shared-project .\XPO\_release\SharedProject_*.xpo --out .\XPO

# Починка кодировки
fix-mojibake .\XPO --dry-run
fix-mojibake .\XPO
```

## Структура

```
XPOTools/
├── build-shared-project.py     ← главный сборщик
├── Modules/                    ← вспомогательные модули
│   ├── xpo_types.py            ← каталог UTILTYPE/NODETYPE
│   ├── validate_xpo.py
│   ├── split_shared_project.py
│   ├── fix_mojibake.py
│   └── config.py
├── bin/                        ← .ps1/.cmd-обёртки в PATH
├── tests/                      ← smoke-тесты
├── config.example.json         ← шаблон конфига (под git)
├── config.local.json           ← локальные значения (gitignored)
├── update.ps1
└── .gitignore
```
