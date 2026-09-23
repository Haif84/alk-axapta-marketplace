# alk-llm-economy — экономия токенов в Claude Code и Cursor

Комплект мер, измеренных на Claude Code за 2026-09-12…18: что экономит
каждая и сколько — `docs/savings-report-2026-09-18.md`, механизм и замер по
мерам — `docs/savings-replication.md`, раздел 1. Главное: каждый ход платит
за весь накопленный контекст, поэтому меры бьют по базе хода, росту
контекста, сохранности кэша и потолку контекста.

## Claude Code

| Что | Как ставится |
|---|---|
| Хуки `hooks/*.ps1`: `read-gate`, `context-budget`, `pause-guard`, `keepalive-gate`, `model-notice`, `model-switch-guard`, `test-output-filter`, `session-memory`, `commit-reminder` | сами, через `hooks/hooks.json`, как только плагин включён |
| Ключи `settings.json` (`claude/settings.fragment.json`): deny схем, `autoCompactWindow`, `promptCacheTtl`, `bashOutputMaxChars`, `skillOverrides`, строка статуса | `/alk-llm-economy:economy-setup` |
| Правила в `~/.claude/CLAUDE.md` (`claude/CLAUDE.economy.md`, блок между маркерами) | то же |
| Агент Explore на Haiku (`claude/agents/explore.md` → `~/.claude/agents/`) | то же |
| Скрипты замера `scripts/*.js` и `docs/` → junction `~/.claude/scripts`, `~/.claude/docs` | то же |

Установщик — `scripts/install.ps1`: без `-Apply` только показывает, что
изменит. Предусловия: Windows, PowerShell 5.1, Node 20+, git.

## Cursor

С плагином приходят правило `rules/llm-economy.mdc` (alwaysApply), хук
`read-gate` (`cursor/hooks.json` → `cursor/read-gate.ps1` — обёртка над тем
же `hooks/read-gate.ps1`) и агент `explore` (`cursor/agents/`). Остальные меры
завязаны на настройки, транскрипты и кэш Claude Code; таблица «что не
переносится» — в `skills/economy-setup/SKILL.md`.

Имена полей инструмента Read в Cursor документация не фиксирует; обёртка
принимает несколько вариантов, на живом Cursor не проверена.

## Тесты

```
node --test scripts/
powershell.exe -NoProfile -ExecutionPolicy Bypass -File hooks\read-gate.test.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File cursor\read-gate.test.ps1
```

Тесты хуков — по файлу на хук (`hooks\*.test.ps1`), каждый той же строкой.

## Откуда

Перенос комплекта `ClaudeCodeEconomy/export` (сборка 2026-09-18, коммит
ClaudeOps `3a337c7`). Отличия от комплекта: хуки подключает плагин, а не
`settings.json`; `statusline.ps1` лежит в `scripts/`; из глобального
`CLAUDE.md` взят только раздел правил экономии, журнал замеров —
`~/.claude/llm-costs.md` вместо `docs/costs.md` ClaudeOps; не перенесён
`log-commands.ps1` (не подключался, путь зашит под автора).
`.ps1` хранятся в UTF-8 с BOM — иначе PowerShell 5.1 портит кириллицу.
