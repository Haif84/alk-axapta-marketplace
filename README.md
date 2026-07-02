# ALK Axapta Tools — магазин скиллов Claude Code

Claude Code plugin marketplace с инструментами для работы с проектами
Microsoft Dynamics AX 2012 (ALK).

## Состав

| Плагин                | Назначение                                                                                                       |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `alk-axapta-tools`        | Скиллы Axapta + инструментарий XPOTools (см. ниже).                                              |
| `alk-hooks-plans2project` | Hook: после`ExitPlanMode` перекладывает планы из `~/.claude/plans/` в `<cwd>/plans/`. Активируется сам при установке. |
| `alk-self-update`         | Дневной cron-уведомитель о новых версиях (для долго открытых сессий). |

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
/plugin install alk-self-update@alk-axapta
```

### 3. Перезапустить Claude Code

После рестарта:

- Hook `move-plan` (перекладка планов после `ExitPlanMode`) **уже активен** — он зашит в плагин
  `alk-hooks-plans2project` (`hooks/hooks.json`), править `settings.json` вручную не нужно.
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
cron, который раз в день проверяет репо прямо во время работы — даже если VS Code не
перезапускается сутками — и присылает `PushNotification`, когда есть новая версия. Включить один
раз:

```
/alk-self-update:check-updates
```

(достаточно вызвать однократно — скилл сам поставит ежедневный cron).

**Применить обновление сейчас:**

```
/plugin marketplace update alk-axapta
/reload-plugins
```

**Опционально — автообновление на рестарте.** Если хотите, чтобы обновления не только
уведомлялись, но и ставились сами при старте VS Code, включите auto-update для магазина один раз:
`/plugin` → вкладка **Marketplaces** → выбрать `alk-axapta` → **Enable auto-update**. Для
сторонних магазинов автообновление по умолчанию выключено, поэтому этот тумблер — ручной шаг.

---

## Для мейнтейнера

### Выкатить обновление

1. Правки в `plugins/<plugin>/skills/`, `.../scripts/` или `.../hooks/`.
2. Увеличить `"version"` в `plugins/<plugin>/.claude-plugin/plugin.json`
   **и** в соответствующей записи `.claude-plugin/marketplace.json`.
3. `git commit` + `git push` в `master`.
4. Команда получит `PushNotification` от `alk-self-update` (в открытой сессии) либо подхватит
   обновление на старте VS Code, если включён auto-update тумблер. Применяется через
   `/plugin marketplace update alk-axapta` + `/reload-plugins`.

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
│   └── alk-self-update/
│       ├── .claude-plugin/plugin.json
│       └── skills/check-updates/SKILL.md
└── README.md
```
