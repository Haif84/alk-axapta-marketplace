# ALK Axapta Tools — магазин скиллов (Claude Code + Cursor)

Plugin marketplace с инструментами для работы с проектами
Microsoft Dynamics AX 2012 (ALK). Один репозиторий обслуживает:

- **Claude Code** — манифест `.claude-plugin/marketplace.json` (все плагины, включая hooks)
- **Cursor** (Team Marketplace, без Claude CLI) — манифест `.cursor-plugin/marketplace.json`
  (только `alk-axapta-tools` + `alk-self-update`)

Клонировать репозиторий и копировать кэш плагинов **не нужно**.

## Состав

| Плагин | Claude Code | Cursor Team Marketplace | Назначение |
| ------ | ----------- | ----------------------- | ---------- |
| `alk-axapta-tools` | да | да | Скиллы Axapta + XPOTools |
| `alk-self-update` | да | да | Проверка обновлений (dual-runtime) |
| `alk-hooks-plans2project` | да | нет | Hook: `ExitPlanMode` → `<cwd>/plans/` |
| `alk-hooks-claude2telegram` | да | нет | Hooks Telegram Allow/Deny (Claude-only) |

Скиллы `alk-axapta-tools`:

| Скилл | Назначение |
| ----- | ---------- |
| `setup` | Разовая настройка ENV (ник, AOT-Prod, префикс) |
| `axapta-mod-comments` | Маркеры модификаций ALK (X++, формы, таблицы) |
| `axapta-project-export` | Сборка финального `.xpo`-бандла |
| `axapta-project-manage` | Organize/flatten/sync/cleanup папки `XPO/` |

XPOTools бандлируется внутри плагина — отдельная установка PATH не нужна.
Предусловие на машине: **Python ≥ 3.9** и доступ к боевой выгрузке AOT-Prod.

---

## Установка A — Claude Code

### 1. Добавить магазин

```
/plugin marketplace add Haif84/alk-axapta-marketplace
```

### 2. Установить плагины

```
/plugin install alk-axapta-tools@alk-axapta
/plugin install alk-hooks-plans2project@alk-axapta
/plugin install alk-hooks-claude2telegram@alk-axapta
/plugin install alk-self-update@alk-axapta
```

### 3. Перезапустить Claude Code / VS Code

После рестарта:

- Hook `move-plan` (`alk-hooks-plans2project`) активен сам.
- Хуки `alk-hooks-claude2telegram` без файла секретов молча ничего не делают —
  см. `plugins/alk-hooks-claude2telegram/README.md`.
- Скиллы:

```
/alk-axapta-tools:setup
/alk-axapta-tools:axapta-mod-comments
/alk-axapta-tools:axapta-project-export
/alk-axapta-tools:axapta-project-manage
/alk-self-update:check-updates
```

### 4. Разовая настройка ENV

```
/alk-axapta-tools:setup
```

Скилл запишет `AX_USER_NICK`, `AX_AOT_PATH`, `AX_PROJECT_ID`,
`AX_OBJECT_PREFIX` **или** `AX_OBJECT_SUFFIX` (ровно один). Без них остальные
скиллы откажутся работать (preflight). После настройки — новая сессия терминала
или Reload Window. Проверка: `$env:AX_USER_NICK`.

---

## Установка B — Cursor only (без Claude CLI)

### 1. Админ (Teams / Enterprise)

1. [Dashboard → Plugins](https://cursor.com/dashboard) → Team Marketplaces → **Import from Repo**
2. URL: `https://github.com/Haif84/alk-axapta-marketplace`
3. Включить **Enable Auto Refresh** (нужен Cursor GitHub App на репозитории)
4. Режим установки: `alk-axapta-tools` — **Default On** или **Required**;
   `alk-self-update` — Default On по желанию

Hooks-плагины в Cursor-каталоге **не перечислены** — их ставить не нужно.

### 2. Участник команды

1. **Customize** в сайдбаре Cursor → плагины из team marketplace → установить при необходимости
2. Reload Window
3. `/setup` (или `/alk-axapta-tools:setup`) — свой ник и путь к AOT-Prod
4. Python ≥ 3.9 в PATH

Клон репо и ручное копирование в `~/.claude/plugins/cache` **не требуются**.

---

## Обновление

### 1. Cursor Team Marketplace (без Claude CLI)

- Админ: **Auto Refresh** подтягивает индекс после push в отслеживаемую ветку
  (не чаще раза в 10 минут); при необходимости — кнопка **Refresh**
- Разработчик: обновить/переустановить плагин в **Customize**, затем
  **Developer: Reload Window**
- Не делать `git pull` вручную в кэш плагинов

### 2. Claude Code CLI / VS Code extension

В отдельном CLI:

```
/plugin marketplace update alk-axapta
/reload-plugins
```

В VS Code extension слэш-команды часто недоступны — из терминала:

```powershell
claude plugin marketplace update alk-axapta
$ip = Get-Content "$env:USERPROFILE\.claude\plugins\installed_plugins.json" -Raw | ConvertFrom-Json
$ip.plugins.PSObject.Properties.Name |
    Where-Object { $_ -like "*@alk-axapta" } |
    ForEach-Object { claude plugin update $_ }
```

Затем Reload Window.

Если `claude` не в PATH — бинарник внутри расширения VS Code
(`*\anthropic.claude-code-*\resources\native-binary\claude.exe`), искать через
`Get-ChildItem -Recurse -Filter claude.exe`.

Опционально: `/plugin` → Marketplaces → `alk-axapta` → **Enable auto-update**.
В extension даже с auto-update рестарт не гарантирует обновление — надёжный путь CLI выше.

### 3. Проверка (`/check-updates`)

```
/alk-self-update:check-updates
```

Dual-runtime:

- **Claude Code** — может поставить session cron и предложить `claude plugin update`
- **Cursor без Claude CLI** — покажет новые коммиты и напомнит про Customize / Auto Refresh
  (без CronCreate и без `claude plugin …`)

---

## Для мейнтейнера

### Выкатить обновление

1. Правки в `plugins/<plugin>/skills/`, `.../scripts/` или `.../hooks/`.
2. Увеличить `"version"` в:
   - `plugins/<plugin>/.claude-plugin/plugin.json`
   - `plugins/<plugin>/.cursor-plugin/plugin.json` (если плагин в Cursor-каталоге)
   - записи в `.claude-plugin/marketplace.json` и `.cursor-plugin/marketplace.json` (`metadata.version`)
3. `git commit` + `git push` в `master`.
4. Команда: Claude — `claude plugin update …@alk-axapta`; Cursor — Auto Refresh / Customize Reload.

### Синхронизация XPOTools

Источник: `~/.claude/scripts/XPOTools/` (dev-машина мейнтейнера).
Копировать без `.git/`, `__pycache__/`, `config.local.json`:

```powershell
$src = "$env:USERPROFILE\.claude\scripts\XPOTools"
$dst = "plugins\alk-axapta-tools\scripts\XPOTools"
robocopy $src $dst /MIR /XD ".git" "__pycache__" /XF "config.local.json" "*.pyc"
```

### Структура репозитория

```
alk-axapta-marketplace/
├── .claude-plugin/
│   └── marketplace.json              # Claude: все плагины
├── .cursor-plugin/
│   └── marketplace.json              # Cursor: tools + self-update
├── plugins/
│   ├── alk-axapta-tools/
│   │   ├── .claude-plugin/plugin.json
│   │   ├── .cursor-plugin/plugin.json
│   │   ├── skills/
│   │   └── scripts/
│   │       ├── setup-env.ps1
│   │       └── XPOTools/
│   ├── alk-hooks-plans2project/      # Claude-only
│   ├── alk-hooks-claude2telegram/    # Claude-only
│   └── alk-self-update/
│       ├── .claude-plugin/plugin.json
│       ├── .cursor-plugin/plugin.json
│       └── skills/check-updates/SKILL.md
└── README.md
```
