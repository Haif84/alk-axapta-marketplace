# ALK Axapta Tools — магазин скиллов Claude Code

Claude Code plugin marketplace с инструментами для работы с проектами
Microsoft Dynamics AX 2012 (ALK).

## Состав

| Плагин | Назначение |
|--------|------------|
| `alk-axapta-tools`        | Скиллы Axapta + инструментарий XPOTools (см. ниже). |
| `alk-hooks-plans2project` | Hook: после `ExitPlanMode` перекладывает планы из `~/.claude/plans/` в `<cwd>/plans/`. |
| `alk-self-update`         | Дневной cron-уведомитель о новых версиях (для долго открытых сессий). |

Скиллы `alk-axapta-tools`:

| Скилл | Назначение |
|-------|------------|
| `axapta-mod-comments`   | Комментарии-маркеры модификаций в стиле ALK (X++, формы, таблицы). |
| `axapta-project-export` | Сборка финального `.xpo`-бандла задачи для передачи заказчику. |
| `axapta-project-manage` | Organize/flatten/sync/cleanup структуры папки `XPO/` задачи. |

XPOTools (Python-скрипты `build-shared-project`, `validate-xpo`, `organize-xpo` и др.)
бандлируются внутри плагина — отдельная установка PATH не требуется.

---

## Установка (участник команды)

### 1. Bootstrap — один раз на компьютере

Клонировать репо и запустить:

```powershell
powershell -ExecutionPolicy Bypass -File .\install\bootstrap.ps1 -UserNick <ваш_ник>
# опционально (для sync-xpo с боевой выгрузкой):
powershell -ExecutionPolicy Bypass -File .\install\bootstrap.ps1 -UserNick akaz -AotProd "E:\Axapta\AOT-Prod"
```

Bootstrap:
- записывает user-level ENV-переменные (`ALK_USER_NICK`, `ALK_AOT_PROD`, `ALK_PROJECT_PREFIX`) —
  они переживают любые обновления плагина;
- устанавливает hook `move-plan.ps1` (PostToolUse: ExitPlanMode);
- **регистрирует магазин и включает `autoUpdate`** в `~/.claude/settings.json`
  (`extraKnownMarketplaces.alk-axapta`). Отдельный `/plugin marketplace add` не нужен.

### 2. Установить нужные плагины

```
/plugin install alk-axapta-tools@alk-axapta
/plugin install alk-hooks-plans2project@alk-axapta
/plugin install alk-self-update@alk-axapta
```

### 3. Перезапустить Claude Code

Скиллы доступны сразу:

```
/alk-axapta-tools:axapta-mod-comments
/alk-axapta-tools:axapta-project-export
/alk-axapta-tools:axapta-project-manage
/alk-self-update:check-updates
```

---

## Обновление

**Автоматически.** Благодаря `autoUpdate` Claude Code при каждом старте VS Code обновляет
маркетплейс и установленные плагины. Если что-то обновилось — появится подсказка выполнить
`/reload-plugins` (без перезапуска).

**Вручную (сразу):**

```
/plugin marketplace update alk-axapta
/reload-plugins
```

**Долгие сессии.** Если VS Code не перезапускается сутками, плагин `alk-self-update` раз в день
проверяет репо и присылает уведомление о новой версии. Запустить проверку вручную:
`/alk-self-update:check-updates`.

---

## Для мейнтейнера

### Выкатить обновление

1. Правки в `plugins/<plugin>/skills/` или `.../scripts/`.
2. Увеличить `"version"` в `plugins/<plugin>/.claude-plugin/plugin.json`
   **и** в соответствующей записи `.claude-plugin/marketplace.json`.
3. `git commit` + `git push` в `master`.
4. У команды обновление прилетит на следующем старте VS Code (autoUpdate).

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
│   │   ├── skills/                   # axapta-mod-comments, -project-export, -project-manage
│   │   └── scripts/XPOTools/
│   ├── alk-hooks-plans2project/
│   │   ├── .claude-plugin/plugin.json
│   │   └── scripts/hooks/move-plan.ps1
│   └── alk-self-update/
│       ├── .claude-plugin/plugin.json
│       └── skills/check-updates/SKILL.md
├── install/
│   └── bootstrap.ps1
└── README.md
```
