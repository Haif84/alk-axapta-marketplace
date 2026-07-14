# ALK Axapta Tools — магазин скиллов Claude Code

Claude Code plugin marketplace с инструментами для работы с проектами
Microsoft Dynamics AX 2012 (ALK).

## Состав

| Плагин                | Назначение                                                                                                       |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `alk-axapta-tools`        | Скиллы Axapta + инструментарий XPOTools (см. ниже).                                              |
| `alk-hooks-plans2project` | Hook: после`ExitPlanMode` перекладывает планы из `~/.claude/plans/` в `<cwd>/plans/`. Активируется сам при установке. |
| `alk-hooks-claude2telegram` | Hooks: разрешения и уведомления Claude Code через Telegram-бота — Allow/Deny с телефона, `/wait` (таймаут ответа), алиасы машин, темы по проектам, обратная связь Telegram → сессия. Активируется сам при установке, детали — в `plugins/alk-hooks-claude2telegram/README.md`. |
| `alk-self-update`         | Cron-уведомитель о новых версиях каждые 2 часа, 8:30-22:30 (для долго открытых сессий). |

Скиллы `alk-axapta-tools`:

| Скилл                | Назначение                                                                                              |
| ------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `setup`                 | Разовая настройка ENV-переменных (ник, путь к AOT-Prod, префикс).       |
| `axapta-mod-comments`   | Комментарии-маркеры модификаций в стиле ALK (X++, формы, таблицы). |
| `axapta-project-export` | Сборка финального`.xpo`-бандла задачи для передачи заказчику.   |
| `axapta-project-manage` | Organize/flatten/sync/cleanup структуры папки`XPO/` задачи.                                 |

XPOTools (Python-скрипты `build-shared-project`, `validate-xpo`, `organize-xpo` и др.)
бандлируются внутри плагина — отдельная установка PATH не требуется.

---

## Установка (участник команды)

Клонировать репозиторий **не нужно** — всё ставится через нативные команды Claude Code.

### 1. Добавить магазин

```
/plugin marketplace add Haif84/alk-axapta-marketplace
```

### 2. Установить нужные плагины

```
/plugin install alk-axapta-tools@alk-axapta
/plugin install alk-hooks-plans2project@alk-axapta
/plugin install alk-hooks-claude2telegram@alk-axapta
/plugin install alk-self-update@alk-axapta
```

### 3. Перезапустить Claude Code

После рестарта:

- Hook `move-plan` (перекладка планов после `ExitPlanMode`) **уже активен** — он зашит в плагин
  `alk-hooks-plans2project` (`hooks/hooks.json`), править `settings.json` вручную не нужно.
- Хуки `alk-hooks-claude2telegram` тоже активируются сами, но **без файла секретов молча ничего
  не делают** (fail-open) — нужен разовый ручной шаг, см. `plugins/alk-hooks-claude2telegram/
  README.md` (создать `~/.claude/tg-approve.secrets.json`, получить `relay_secret` у владельца
  relay).
- Скиллы доступны сразу:

```
/alk-axapta-tools:setup
/alk-axapta-tools:axapta-mod-comments
/alk-axapta-tools:axapta-project-export
/alk-axapta-tools:axapta-project-manage
/alk-self-update:check-updates
```

### 4. Разовая настройка ENV

Запустите один раз — скилл спросит ник, путь к AOT-Prod, ID проекта и аффикс именования
(prefix ИЛИ suffix — ровно один) и запишет user-level ENV-переменные (`AX_USER_NICK`,
`AX_AOT_PATH`, `AX_PROJECT_ID`, `AX_OBJECT_PREFIX`/`AX_OBJECT_SUFFIX`). Все пять обязательны —
без них остальные скиллы плагина откажутся работать (preflight-гейт). Переживают любые
обновления плагина.

```
/alk-axapta-tools:setup
```

После настройки перезапустите VS Code, чтобы переменные подхватились. Проверка: `$env:AX_USER_NICK`.

---

## Обновление

**Уведомление в открытой сессии (основной механизм).** Плагин `alk-self-update` ставит durable
cron, который каждые 2 часа (8:30–22:30, минута рандомизирована на каждой машине, чтобы не
грузить инфраструктуру одновременными срабатываниями) проверяет репо прямо во время работы —
даже если VS Code не перезапускается сутками — и присылает `PushNotification`, когда есть новая
версия. Включить один раз:

```
/alk-self-update:check-updates
```

(достаточно вызвать однократно — скилл сам поставит cron на регулярную проверку).

**Применить обновление сейчас:**

В отдельном CLI/терминале:

```
/plugin marketplace update alk-axapta
/reload-plugins
```

**В VS Code extension** обе слэш-команды недоступны ("isn't available in this environment") —
используйте CLI-команды через терминал (Bash/PowerShell), затем перезапустите VS Code
(Developer: Reload Window), чтобы обновление применилось:

```powershell
claude plugin marketplace update alk-axapta
claude plugin update alk-axapta-tools@alk-axapta
claude plugin update alk-hooks-plans2project@alk-axapta
claude plugin update alk-hooks-claude2telegram@alk-axapta
claude plugin update alk-self-update@alk-axapta
```

Или разом для всех установленных alk-плагинов, без перечисления по имени:

```powershell
$ip = Get-Content "$env:USERPROFILE\.claude\plugins\installed_plugins.json" -Raw | ConvertFrom-Json
$ip.plugins.PSObject.Properties.Name |
    Where-Object { $_ -like "*@alk-axapta" } |
    ForEach-Object { claude plugin update $_ }
```

**Если `claude` не найден в PATH** (`The term 'claude' is not recognized...`) — типичная ситуация
именно в VS Code extension, где отдельного CLI-инсталлятора не было: сама VS Code уже содержит
рабочий бинарник внутри установленного расширения. Найти и вызвать напрямую:

```powershell
$claudeExe = Get-ChildItem "$env:USERPROFILE\.vscode\extensions" -Filter "claude.exe" -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.DirectoryName -like "*native-binary*" } |
    Select-Object -First 1 -ExpandProperty FullName
& $claudeExe plugin marketplace update alk-axapta
& $claudeExe plugin update alk-hooks-claude2telegram@alk-axapta   # и т.д. по каждому плагину
```

Путь выглядит как `%USERPROFILE%\.vscode\extensions\anthropic.claude-code-<version>-win32-x64\
resources\native-binary\claude.exe` — версия расширения в пути меняется при каждом апдейте VS
Code Marketplace, поэтому искать по шаблону (`Get-ChildItem -Recurse`), а не хардкодить конкретную
версию. Найдено и проверено вживую 2026-07-14.

**Опционально — автообновление на рестарте.** Если хотите, чтобы обновления не только
уведомлялись, но и ставились сами при старте VS Code, включите auto-update для магазина один раз:
`/plugin` → вкладка **Marketplaces** → выбрать `alk-axapta` → **Enable auto-update**. Для
сторонних магазинов автообновление по умолчанию выключено, поэтому этот тумблер — ручной шаг.
В VS Code extension даже с включённым auto-update простой рестарт **не гарантирует** подтягивание
новой версии — надёжный путь именно CLI-команды выше.

---

## Для мейнтейнера

### Выкатить обновление

1. Правки в `plugins/<plugin>/skills/`, `.../scripts/` или `.../hooks/`.
2. Увеличить `"version"` в `plugins/<plugin>/.claude-plugin/plugin.json`
   **и** в соответствующей записи `.claude-plugin/marketplace.json`.
3. `git commit` + `git push` в `master`.
4. Команда получит `PushNotification` от `alk-self-update` (в открытой сессии) либо подхватит
   обновление на старте VS Code, если включён auto-update тумблер. Применяется через
   `/plugin marketplace update alk-axapta` + `/reload-plugins` (отдельный CLI/терминал) или
   `claude plugin marketplace update alk-axapta` + `claude plugin update <plugin>@alk-axapta`
   (VS Code extension, где слэш-команды недоступны).

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
│   └── marketplace.json              # каталог магазина (name=alk-axapta)
├── plugins/
│   ├── alk-axapta-tools/
│   │   ├── .claude-plugin/plugin.json
│   │   ├── skills/                   # setup, axapta-mod-comments, -project-export, -project-manage
│   │   └── scripts/
│   │       ├── setup-env.ps1         # bundled: пишет ENV (вызывается скиллом setup)
│   │       └── XPOTools/
│   ├── alk-hooks-plans2project/
│   │   ├── .claude-plugin/plugin.json
│   │   ├── hooks/hooks.json          # нативная регистрация PostToolUse: ExitPlanMode
│   │   └── scripts/hooks/move-plan.ps1
│   ├── alk-hooks-claude2telegram/
│   │   ├── .claude-plugin/plugin.json
│   │   ├── hooks/hooks.json          # PermissionRequest/Stop/PreToolUse/PostToolUse/UserPromptSubmit
│   │   ├── scripts/hooks/*.ps1       # копия из dev-проекта AK_ClaudeRequestTGNotify, см. его README
│   │   └── README.md                 # установка секретов, темы по проектам, /wait, /length
│   └── alk-self-update/
│       ├── .claude-plugin/plugin.json
│       └── skills/check-updates/SKILL.md
└── README.md
```
