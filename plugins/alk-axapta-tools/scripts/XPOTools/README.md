# XPOTools

Общий инструментарий для сборки/проверки/разбора xpo-файлов
Microsoft Dynamics AX 2012 (X++).

## Состав

| Команда | Что делает |
|---------|------------|
| `build-shared-project` | Собирает финальный `SharedProject_*.xpo` (AOT Project + тела всех его объектов) из папки `XPO/*.xpo`. |
| `validate-xpo` | Проверяет xpo-файлы: BOM+CRLF, балансировка блоков, mojibake, наличие маркеров модификаций, уникальность имён объектов. |
| `split-shared-project` | Обратная операция к `build-shared-project`: нарезает бандл обратно на отдельные `<Type>_<Name>.xpo`. |
| `fix-mojibake` | Чинит файлы с двойной перекодировкой CP1251↔UTF-8. |

Внутренние модули — в [Modules/](Modules/), обёртки командной строки — в [bin/](bin/).

## Установка

```powershell
git clone <repo-url> "$env:USERPROFILE\.claude\scripts\XPOTools"
cd "$env:USERPROFILE\.claude\scripts\XPOTools"
.\setup.ps1
notepad config.local.json   # заполни ALK_USER_NICK и т.п.
```

`setup.ps1` добавляет `XPOTools/bin` в user-level `$env:PATH` (через `HKCU\Environment`, без admin) и создаёт `config.local.json` из `config.example.json`.

После установки — открой новую сессию PowerShell, чтобы PATH подхватился. Команды `build-shared-project --help` и т.д. должны работать без указания полного пути.

## Обновление

```powershell
cd "$env:USERPROFILE\.claude\scripts\XPOTools"
.\update.ps1
```

`update.ps1` делает `git pull --ff-only` и предупреждает, если `config.example.json` получил новые ключи, не отражённые в `config.local.json`.

## Конфигурация

Источники значений по убыванию приоритета:

1. Переменные окружения `ALK_PROJECT_PREFIX`, `ALK_USER_NICK`, `ALK_AOT_PROD`.
2. `config.local.json` (gitignored).
3. `config.example.json` (под git, плейсхолдеры).

В коде нет ALK-специфичных литералов — всё через [Modules/config.py](Modules/config.py).

## Требования

- Python ≥ 3.9
- PowerShell 5.1+ (для wrapper'ов в `bin/`) или cmd.exe
- Git (для `update.ps1`)

## Примеры

```powershell
# Сборка финального бандла
build-shared-project --root .\XPO --project-name ALK_DEVAX12_DAX_012345 --dry-run
build-shared-project --root .\XPO --project-name ALK_DEVAX12_DAX_012345 --yes

# Валидация
validate-xpo .\XPO --strict

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
├── setup.ps1
├── update.ps1
└── .gitignore
```
