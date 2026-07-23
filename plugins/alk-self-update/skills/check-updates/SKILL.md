---
name: check-updates
description: Проверяет новые коммиты в маркетплейсе alk-axapta (Haif84/alk-axapta-marketplace). Dual-runtime — Claude Code (CronCreate/PushNotification + claude plugin update) и Cursor без Claude CLI (список коммитов + Customize/Reload / Team Marketplace Auto Refresh, без cron). Триггеры — «проверь обновления alk», «check updates», «/check-updates», а также фоновый запуск из CronCreate по маркеру ФОНОВАЯ_ПРОВЕРКА_ALK (только Claude).
---

# check-updates

Проверяет, есть ли новые коммиты в `Haif84/alk-axapta-marketplace`, и **уведомляет** о них.
Файлы плагина сам не трогает (кроме файла состояния вне кэша).

## Детект среды (в начале)

Определи runtime **до** шагов уведомления/cron:

1. **Claude runtime** — если доступен инструмент `CronCreate` **или** в PATH находится
   команда `claude` (или `claude.exe` внутри VS Code extension
   `*\anthropic.claude-code-*\resources\native-binary\`).
2. Иначе — **Cursor runtime** (нет Claude CLI / нет CronCreate).

| | Claude runtime | Cursor runtime |
|--|----------------|----------------|
| Фон (маркер `ФОНОВАЯ_ПРОВЕРКА_ALK`) | `PushNotification` | кратко в чат **или** молчать, если нельзя пуш |
| Интерактив: как обновить | `claude plugin marketplace update` + `claude plugin update …@alk-axapta` | Customize → обновить плагин → Reload Window; админу — Refresh / Auto Refresh Team Marketplace |
| CronCreate (шаг 5) | да (session-only) | **не вызывать** |

## Когда вызывать

1. **По запросу** — `/check-updates` или «проверь обновления alk».
2. **Из CronCreate** (только Claude) — промпт с маркером `ФОНОВАЯ_ПРОВЕРКА_ALK` → тихий фон.

## Файл состояния

`$env:USERPROFILE\.claude\alk-update-state.json` — **вне** кэша плагинов.

```json
{
  "last_check":     "2026-06-25T09:37:00.0000000Z",
  "last_known_sha": "abc123...",
  "pending_sha":    null,
  "cron_scheduled": true
}
```

- `last_check` — ISO UTC
- `last_known_sha` — известный пользователю SHA
- `pending_sha` — SHA, о котором уже уведомляли, но ещё не обновились
- `cron_scheduled` — имел ли смысл cron (в Cursor всегда можно писать `false`)

## Алгоритм

### Шаг 1. Читаем состояние

```powershell
$statePath = "$env:USERPROFILE\.claude\alk-update-state.json"
$state = if (Test-Path $statePath) { Get-Content $statePath -Raw | ConvertFrom-Json } else { $null }
```

Если файла нет — seed `last_known_sha`:

```powershell
# Claude cache
$ipPath = "$env:USERPROFILE\.claude\plugins\installed_plugins.json"
if (Test-Path $ipPath) {
    $ip = Get-Content $ipPath -Raw | ConvertFrom-Json
    # Взять gitCommitSha любого плагина *@alk-axapta
}
# Cursor: если installed_plugins.json нет — оставить last_known_sha пустым;
# первое сравнение с remote всё равно покажет «есть коммиты» только при расхождении
# после того как SHA один раз сохранён.
```

### Шаг 2. Удалённый SHA

```powershell
$remoteSha = (git ls-remote https://github.com/Haif84/alk-axapta-marketplace HEAD).Split("`t")[0]
```

Нет `git`/сети — интерактив: сообщить; фон: молчать. Обновить только `last_check` → шаг 5
(в Cursor шаг 5 — no-op).

### Шаг 3. Сравнение

**Нет изменений** (`$remoteSha` == `last_known_sha`):
- Обновить `last_check`
- Интерактив: «маркетплейс alk-axapta актуален»
- Фон: молчать
- → шаг 5

**Есть изменения** — список коммитов через `gh`, если доступен:

```powershell
$commits = gh api "repos/Haif84/alk-axapta-marketplace/commits?sha=master&per_page=20" | ConvertFrom-Json
$newCommits = @()
foreach ($c in $commits) {
    if ($c.sha -eq $state.last_known_sha) { break }
    $newCommits += "$($c.commit.author.date.Substring(0,10))  $($c.commit.message.Split("`n")[0])"
}
```

Иначе — только короткий `$remoteSha`.

### Шаг 4. Уведомление

#### Фон (`ФОНОВАЯ_ПРОВЕРКА_ALK`)

- **Claude:** `PushNotification`:
  `"alk-axapta: доступно обновление ($($newCommits.Count) коммитов). Спросите ассистента про /check-updates."`
- **Cursor:** если есть аналог push — использовать; иначе одна короткая строка в ответ
  агента **или** молчать (не спамить). Не запускать обновление.
- Сохранить `pending_sha = $remoteSha`, обновить `last_check`. Выйти.

#### Интерактив

Показать список новых коммитов. Если `pending_sha` == `$remoteSha` — добавить
«(вы уже видели это уведомление)».

**Claude runtime — как применить:**

```powershell
claude plugin marketplace update alk-axapta
$ip = Get-Content "$env:USERPROFILE\.claude\plugins\installed_plugins.json" -Raw | ConvertFrom-Json
$ip.plugins.PSObject.Properties.Name |
    Where-Object { $_ -like "*@alk-axapta" } |
    ForEach-Object { claude plugin update $_ }
```

Спросить согласие; при согласии выполнить; затем Reload Window.
Короткое имя без `@alk-axapta` → `Plugin "X" not found`.

**Cursor runtime — как применить (без `claude plugin`):**

1. Разработчик: **Customize** → обновить/переустановить `alk-axapta-tools` /
   `alk-self-update` → **Developer: Reload Window**
2. Админ team marketplace: Dashboard → Plugins → **Refresh** или дождаться
   **Auto Refresh** после push в GitHub
3. Не предлагать `git pull` в кэш и не предлагать установить Claude CLI «только ради update»

После рестарта по просьбе пользователя сверить версии с ожидаемым SHA.

### Шаг 5. CronCreate (только Claude runtime)

Если runtime = Cursor — **пропустить** этот шаг (`cron_scheduled = false` в состоянии).

Если Claude и (`cron_scheduled` не true **или** ручной `/check-updates`):

Случайная минута `M` ∈ [31..35] один раз на машину (сохранить в state при желании).

`CronCreate`:
```
schedule = "<M> 8-22/2 * * *"
durable  = true   # API требует; реально session-only
prompt   = "ФОНОВАЯ_ПРОВЕРКА_ALK: проверь обновления маркетплейса alk-axapta.
            Тихий фон: нет обновлений — молчи. Есть — PushNotification, pending_sha.
            Не спрашивай и не обновляй сам."
```

Пример `M=33`: 8:33, 10:33, …, 22:33.

**Важно:** `durable: true` не даёт персистентности — job session-only, максимум 7 дней
или до закрытия сессии. После рестарта следующий `/check-updates` поставит cron снова.

### Шаг 6. Сохранить состояние

```powershell
@{
    last_check      = [DateTime]::UtcNow.ToString("o")
    last_known_sha  = $remoteSha    # или прежнее, если нет сети
    pending_sha     = $pendingSha
    cron_scheduled  = $cronScheduled  # true только если CronCreate реально вызван
} | ConvertTo-Json | Set-Content -Encoding UTF8 $statePath
```

## Примечание

Никакого ручного копирования файлов в кэш плагинов. Источник истины — GitHub
`Haif84/alk-axapta-marketplace` + официальные механизмы IDE (Claude plugin CLI или
Cursor Team Marketplace / Customize).
