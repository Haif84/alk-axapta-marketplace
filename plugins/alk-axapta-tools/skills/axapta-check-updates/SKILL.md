# axapta-check-updates

Проверяет наличие обновлений плагина `alk-axapta-tools` в GitHub-репо
`Haif84/alk-axapta-marketplace` и при необходимости обновляет локальный кэш.

## Когда вызывать

1. **Автоматически** — если в контексте сессии есть строка `[ALK_UPDATE_CHECK_NEEDED]`
   (добавляется SessionStart hook из `settings.json`). Вызвать немедленно, без лишних вопросов.
2. **По запросу** — пользователь написал `/axapta-check-updates` или попросил проверить обновления.
3. **Из CronCreate** — промпт содержит маркер `ФОНОВАЯ_ПРОВЕРКА_ALK` (тихий режим, без интерактива).

## Файл состояния

`$env:USERPROFILE\.claude\plugins\cache\alk-axapta\.update-state.json`

```json
{
  "last_check":     "2026-06-25T09:37:00.0000000Z",
  "last_known_sha": "abc123...",
  "pending_sha":    null,
  "cron_scheduled": true
}
```

- `last_check` — ISO UTC, время последней успешной проверки
- `last_known_sha` — SHA коммита, известного пользователю (установленная версия)
- `pending_sha` — SHA если пользователь видел уведомление, но отказался обновляться
- `cron_scheduled` — установлен ли durable CronCreate

## Алгоритм

### Шаг 1. Читаем состояние

```powershell
$statePath = "$env:USERPROFILE\.claude\plugins\cache\alk-axapta\.update-state.json"
$state = if (Test-Path $statePath) { Get-Content $statePath | ConvertFrom-Json } else { $null }
```

### Шаг 2. Запрашиваем GitHub

```powershell
$remote = gh api repos/Haif84/alk-axapta-marketplace/commits/master `
    --jq '{sha: .sha, msg: .commit.message, date: .commit.author.date}' | ConvertFrom-Json
```

Если `gh` недоступен или нет сети — сказать пользователю, обновить только `last_check`, перейти к шагу 5.

### Шаг 3. Сравниваем SHA

**Нет обновлений** (`$remote.sha` совпадает с `last_known_sha`, или это уже был `pending_sha`):
- Обновить `last_check` в состоянии
- В интерактивном режиме: кратко «alk-axapta-tools актуален ✓»
- В фоновом режиме: молчать
- Перейти к шагу 5

**Есть обновления** (`$remote.sha` отличается):

Получить список новых коммитов (остановиться на `last_known_sha`):
```powershell
$commits = gh api "repos/Haif84/alk-axapta-marketplace/commits?sha=master&per_page=20" | ConvertFrom-Json
$newCommits = @()
foreach ($c in $commits) {
    if ($c.sha -eq $state.last_known_sha) { break }
    $newCommits += "$($c.commit.author.date.Substring(0,10))  $($c.commit.message.Split("`n")[0])"
}
```

**Фоновый режим** (вызвано из CronCreate):
- Отправить `PushNotification`: `"alk-axapta-tools: $($newCommits.Count) новых коммитов. /axapta-check-updates"`
- Сохранить `pending_sha = $remote.sha` в состоянии, обновить `last_check`
- Выйти без интерактива

**Интерактивный режим**:
- Показать список новых коммитов
- Если `pending_sha` совпадает с `$remote.sha` — напомнить: «Вы уже видели это уведомление»
- Спросить через `AskUserQuestion`: «Обновить alk-axapta-tools сейчас?»

### Шаг 4. Обновление (если пользователь согласен)

```powershell
$tmp = "$env:TEMP\alk-update-tmp"
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }

gh repo clone Haif84/alk-axapta-marketplace $tmp

$dst = "$env:USERPROFILE\.claude\plugins\cache\alk-axapta\alk-axapta-tools\1.0.0"
Copy-Item "$tmp\plugins\alk-axapta-tools\*" $dst -Recurse -Force
Remove-Item $tmp -Recurse -Force
```

После успеха:
- `last_known_sha` = `$remote.sha`, `pending_sha` = null, `last_check` = now
- Сообщить: «Обновлено. Перезапустите VS Code, чтобы перезагрузить навыки»

**Если отказался**:
- `pending_sha` = `$remote.sha` (чтобы не спрашивать повторно до следующего коммита)
- `last_check` = now

### Шаг 5. CronCreate на следующие сутки

Если `cron_scheduled` не установлен, или выполняется ручной `/axapta-check-updates`:

Вызвать `CronCreate` с параметрами:
```
schedule = "37 9 * * *"   # не :00/:30 — снижает нагрузку на флит
durable  = true             # переживает перезапуск VS Code (до 7 дней)
prompt   = "ФОНОВАЯ_ПРОВЕРКА_ALK: проверь обновления плагина alk-axapta-tools.
            Фоновый режим: если нет обновлений — молчи и обнови last_check.
            Если есть новые коммиты — отправь PushNotification и сохрани pending_sha.
            Не задавай вопросов пользователю."
```

Установить `cron_scheduled: true` в `.update-state.json`.

### Шаг 6. Сохраняем состояние

```powershell
@{
    last_check      = [DateTime]::UtcNow.ToString("o")
    last_known_sha  = $remote.sha   # или прежнее, если нет сети
    pending_sha     = $pendingSha   # null или SHA
    cron_scheduled  = $true
} | ConvertTo-Json | Set-Content -Encoding UTF8 $statePath
```

## Первая настройка (если навык вызван впервые)

Если `.update-state.json` отсутствует — нет ни `last_known_sha`, ни `cron_scheduled`.
Тогда после успешной проверки:
1. Предложить пользователю добавить SessionStart hook в `settings.json` (если его ещё нет)
2. Показать фрагмент для вставки — путь к `check-alk-updates.ps1` и содержимое hook-записи

Файл хука `$env:USERPROFILE\.claude\hooks\check-alk-updates.ps1` (создать если нет):
```powershell
$state = "$env:USERPROFILE\.claude\plugins\cache\alk-axapta\.update-state.json"
if (!(Test-Path $state)) {
    Write-Output '[ALK_UPDATE_CHECK_NEEDED] Плагин alk-axapta-tools: первый запуск, проверка не выполнялась'
} else {
    try {
        $j = Get-Content $state | ConvertFrom-Json
        if (([DateTime]::UtcNow - [DateTime]::Parse($j.last_check)).TotalHours -gt 24) {
            Write-Output '[ALK_UPDATE_CHECK_NEEDED] Плагин alk-axapta-tools: последняя проверка >24ч назад'
        }
    } catch {
        Write-Output '[ALK_UPDATE_CHECK_NEEDED] Плагин alk-axapta-tools: ошибка чтения состояния'
    }
}
```

Запись в `settings.json` → `hooks.SessionStart`:
```json
{
  "matcher": "",
  "hooks": [{
    "type": "command",
    "command": "powershell -NoProfile -ExecutionPolicy Bypass -File \"%USERPROFILE%\\.claude\\hooks\\check-alk-updates.ps1\"",
    "timeout": 3000
  }]
}
```
