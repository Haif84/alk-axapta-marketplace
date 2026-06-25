# ALK Axapta Tools — приватный магазин скиллов Claude Code

Приватный Claude Code plugin marketplace с инструментами для работы с проектами
Microsoft Dynamics AX 2012 (ALK).

## Состав

Один плагин `alk-axapta-tools` включает три скилла и инструментарий XPOTools:

| Скилл | Назначение |
|-------|------------|
| `axapta-mod-comments`   | Комментарии-маркеры модификаций в стиле ALK (X++, формы, таблицы). |
| `axapta-project-export` | Сборка финального `.xpo`-бандла задачи для передачи заказчику. |
| `axapta-project-manage` | Organize/flatten/sync/cleanup структуры папки `XPO/` задачи. |

XPOTools (Python-скрипты `build-shared-project`, `validate-xpo`, `organize-xpo` и др.)
бандлируются внутри плагина — отдельная установка PATH не требуется.

---

## Установка (участник команды)

### 1. Подключить магазин

```
/plugin marketplace add <OWNER>/alk-axapta-marketplace
```

Замените `<OWNER>` на GitHub-логин или org. Требует git-аутентификации
(gh auth login / SSH-ключ / HTTPS-токен с правом read на private repo).

### 2. Установить плагин

```
/plugin install alk-axapta-tools@alk-axapta
```

### 3. Bootstrap — один раз на компьютере

Клонировать репо (или использовать уже скачанную копию) и запустить:

```powershell
powershell -ExecutionPolicy Bypass -File .\install\bootstrap.ps1 -UserNick <ваш_ник>
# опционально:
powershell -ExecutionPolicy Bypass -File .\install\bootstrap.ps1 -UserNick akaz -AotProd "E:\Axapta\AOT-Prod"
```

Bootstrap записывает user-level ENV-переменные (`ALK_USER_NICK`, `ALK_AOT_PROD`,
`ALK_PROJECT_PREFIX`). Они переживают любые обновления плагина.

### 4. Перезапустить Claude Code

Скиллы доступны сразу:

```
/alk-axapta-tools:axapta-mod-comments
/alk-axapta-tools:axapta-project-export
/alk-axapta-tools:axapta-project-manage
```

---

## Обновление

```
/plugin marketplace update
/plugin update alk-axapta-tools@alk-axapta
```

---

## Доступ новому участнику

GitHub → Settings → Collaborators & teams → Add people (уровень Read достаточен).
Участник повторяет шаги 1–4 выше.

---

## Для мейнтейнера

### Выкатить обновление

1. Правки в `plugins/alk-axapta-tools/skills/` или `.../scripts/XPOTools/`.
2. Увеличить `"version"` в `plugins/alk-axapta-tools/.claude-plugin/plugin.json`.
3. `git commit` + `git push`.
4. Команда: `/plugin marketplace update` → `/plugin update alk-axapta-tools@alk-axapta`.

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
│   └── marketplace.json          # каталог магазина (name=alk-axapta)
├── plugins/
│   └── alk-axapta-tools/
│       ├── .claude-plugin/
│       │   └── plugin.json
│       ├── skills/
│       │   ├── axapta-mod-comments/SKILL.md
│       │   ├── axapta-project-export/SKILL.md
│       │   └── axapta-project-manage/SKILL.md
│       └── scripts/
│           └── XPOTools/
├── install/
│   └── bootstrap.ps1
└── README.md
```
