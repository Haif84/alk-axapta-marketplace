---
name: economy-setup
description: Установка, проверка, обновление и снятие экономящей конфигурации плагина alk-llm-economy (Claude Code и Cursor). Триггеры — «поставь экономию токенов», «настрой alk-llm-economy», «economy setup», «/economy-setup», «проверь экономию», «после обновления alk-llm-economy», «сними экономию». Хуки плагин подключает сам; скилл доделывает то, что плагин не может: ключи settings.json, правила в CLAUDE.md, агент Explore, junction на скрипты замера.
---

# economy-setup

Что экономит каждая мера и сколько — `docs/savings-report-2026-09-18.md`
плагина; механизм и замер по каждой мере — таблица в
`docs/savings-replication.md`, раздел 1. Здесь только порядок установки.

## Детект среды

1. **Claude runtime** — доступен `CronCreate` или в PATH есть `claude`.
2. Иначе — **Cursor runtime**.

## Claude Code

### Что уже работает без установки

Хуки из `hooks/hooks.json` активны, как только плагин включён: `read-gate`,
`context-budget`, `pause-guard`, `keepalive-gate`, `model-notice`,
`model-switch-guard`, `test-output-filter`, `session-memory`,
`commit-reminder`. Нужен Windows PowerShell 5.1 (`powershell.exe`).

### Шаг 1. Папка плагина в клоне маркетплейса

Glob `~/.claude/plugins/marketplaces/*/plugins/alk-llm-economy/scripts/install.ps1`.
Нужен именно клон маркетплейса, не `~/.claude/plugins/cache/...`: путь кэша
содержит версию, после обновления junction на него осиротеют. Нет клона —
стоп, сказать владельцу.

### Шаг 2. Просмотр (ничего не пишет)

```
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<папка>\scripts\install.ps1"
```

Пересказать владельцу итог по пунктам, не простынёй:

| Строка вывода | Что значит |
|---|---|
| `MISSING junction ~/.claude/scripts`, `docs` | будут созданы; на них ссылаются правила (`node ~/.claude/scripts/session-cost.js` и т. п.) |
| `CONFLICT` | папка уже есть и ведёт не туда — не трогать, решает владелец |
| `NEW`/`DIFF ~/.claude/agents/explore.md` | Explore на Haiku подменит встроенный ($0.08 за вызов против $1.24 у general-purpose) |
| `NEW`/`DIFF ~/.claude/CLAUDE.md` | блок правил между маркерами `alk-llm-economy:begin/end`: экономия и регламент команды ALK (роли, безопасность, автономия); остальной файл не меняется, делается `.bak-<метка>` |
| вывод `merge-settings.js --dry-run` | какие ключи `settings.json` изменятся |
| `DUPLICATE` | хуки комплекта подключены в `settings.json` руками — задвоятся с плагином, предложить убрать эти записи |

Отдельно спросить владельца (это его выбор, не дефолт):

- `model` и `effortLevel` — фрагмент перезаписывает текущие (`claude-opus-5`,
  `high`). Если у владельца другая модель по умолчанию — убрать эти ключи из
  результата слияния или поправить после.
- `skillOverrides` собран по использованию скиллов на машине автора; через две
  недели пересобрать: `node ~/.claude/scripts/skill-usage.js --cost`.
- `statusLine` перезаписывает текущую строку статуса, если она есть.
- Правило первого хода — `CronCreate 13,43 * * * *` с промптом
  `keepalive: ответь точкой`. Без хука `keepalive-gate` оно вредно; хук идёт
  с плагином, поэтому вместе они безопасны.

### Шаг 3. Установка

После согласия — тот же скрипт с `-Apply`. Затем:

```
node ~/.claude/scripts/superpowers-hook-off.js --check
```

Если впрыск `using-superpowers` включён (≈890 токенов в каждом ходу) —
спросить и снять: `node ~/.claude/scripts/superpowers-hook-off.js`. После
каждого обновления `superpowers` он возвращается; хук `session-memory`
напоминает об этом на старте.

### Шаг 4. Проверка

Настройки и `CLAUDE.md` читаются на старте — проверять в **новой** сессии.

| Что | Как | Ожидание |
|---|---|---|
| Хуки | `/hooks` | записи плагина `alk-llm-economy` на шести событиях |
| Схемы сняты | `/context` | нет `Artifact`, `Workflow`, `NotebookEdit`, `ScheduleWakeup` |
| read-gate | попросить прочитать файл >350 строк без диапазона | отказ с оглавлением |
| Автосжатие | сессия до ≈100k | сжатие у 100k, не у 1M |
| Структура платы | через неделю `node ~/.claude/scripts/cost-structure.js --since <дата>` | чтение кэша ≈45–50 %, ходов свыше 100k нет |

Полная таблица — `docs/savings-replication.md`, раздел 3.

### После обновления плагина

Junction ведут в клон маркетплейса — скрипты и docs обновляются сами. Блок
правил в `CLAUDE.md` и `explore.md` — копии: прогнать шаг 2, при `DIFF` — шаг 3.

### Снятие

1. Выключить плагин (хуки уйдут вместе с ним).
2. Удалить блок между маркерами `alk-llm-economy:begin/end` в `~/.claude/CLAUDE.md`.
3. Удалить junction `~/.claude/scripts`, `~/.claude/docs` (`rmdir`, не `rm -r`:
   иначе удалится содержимое клона) и `~/.claude/agents/explore.md`.
4. Ключи `settings.json` — вернуть из `settings.json.bak-<метка>` или убрать руками.

## Cursor

Ставить нечего: с плагином приходят правила `rules/llm-economy.mdc` и
`rules/alk-baseline.mdc` (регламент команды ALK, alwaysApply), хук `read-gate` (`cursor/hooks.json` → `cursor/read-gate.ps1`,
та же логика, что у Claude) и агент `explore` (`cursor/agents/`).

Проверка:

1. Найти папку плагина (Glob `**/alk-llm-economy/cursor/read-gate.ps1` под `~/.cursor`).
2. `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<папка>\cursor\read-gate.test.ps1"` — ожидается `all passed`.
3. В чате попросить прочитать файл >350 строк целиком — отказ с оглавлением.
   Если чтение прошло: Cursor назвал поля инструмента Read иначе, чем ждёт
   обёртка (`file_path`/`target_file`/`path`, `offset`/`limit`/`start_line`/`end_line`) —
   сообщить владельцу с текстом `tool_input` из логов хуков Cursor.

Агент `explore` идёт с `model: inherit`. Дешевле — скопировать его в
`~/.cursor/agents/explore.md` и поставить id быстрой модели.

Что в Cursor не переносится и почему:

| Мера Claude | Почему нет |
|---|---|
| ключи `settings.json` (deny схем, `autoCompactWindow`, `promptCacheTtl`, `bashOutputMaxChars`) | настройки Claude Code; у Cursor своего аналога нет |
| `test-output-filter` | хук Cursor не может заменить вывод shell-команды |
| `context-budget`, `keepalive-gate`, `pause-guard` | считают контекст и TTL кэша по транскрипту Claude; кэшем Cursor управляет сам |
| `model-switch-guard`, `model-notice` | нет события смены модели |
| `session-memory`, скрипты замера | память и транскрипты Claude Code |
