# check-updates

Проверяет, есть ли новые коммиты в маркетплейсе `Haif84/alk-axapta-marketplace`, и **уведомляет**
о них. Сами файлы плагинов **не трогает** — обновление выполняет нативный `autoUpdate` Claude Code
при следующем старте VS Code (или вручную через `/plugin marketplace update alk-axapta` +
`/reload-plugins`).

Этот скилл нужен только для долго открытых сессий, когда VS Code не перезапускается сутками и
нативная проверка на старте не срабатывает.

## Когда вызывать

1. **По запросу** — пользователь написал `/check-updates` или попросил проверить обновления.
2. **Из CronCreate** — промпт содержит маркер `ФОНОВАЯ_ПРОВЕРКА_ALK` → тихий фоновый режим,
   без вопросов пользователю.

## Файл состояния

`$env:USERPROFILE\.claude\alk-update-state.json` — **вне** кэша плагинов (кэш затирается при
обновлении).

```json
{
  "last_check":     "2026-06-25T09:37:00.0000000Z",
  "last_known_sha": "abc123...",
  "pending_sha":    null,
  "cron_scheduled": true
}
```

- `last_check` — ISO UTC, время последней проверки
- `last_known_sha` — SHA коммита, известного пользователю (текущая установленная версия)
- `pending_sha` — SHA, если пользователь уже был уведомлён, но ещё не обновился
- `cron_scheduled` — установлен ли durable CronCreate

## Алгоритм

### Шаг 1. Читаем состояние

```powershell
$statePath = "$env:USERPROFILE\.claude\alk-update-state.json"
$state = if (Test-Path $statePath) { Get-Content $statePath -Raw | ConvertFrom-Json } else { $null }
```

Если файла нет — seed `last_known_sha` из установленной версии:

```powershell
$ip = Get-Content "$env:USERPROFILE\.claude\plugins\installed_plugins.json" -Raw | ConvertFrom-Json
# Взять gitCommitSha любого alk-плагина из маркетплейса 'alk-axapta'
```

### Шаг 2. Запрашиваем удалённый SHA (без авторизации — репо публичный)

```powershell
$remoteSha = (git ls-remote https://github.com/Haif84/alk-axapta-marketplace HEAD).Split("`t")[0]
```

Если `git` недоступен или нет сети — сообщить пользователю (в фоне молчать), обновить только
`last_check`, перейти к шагу 5.

### Шаг 3. Сравниваем SHA

**Нет изменений** (`$remoteSha` == `last_known_sha`):
- Обновить `last_check`
- Интерактив: кратко «маркетплейс alk-axapta актуален ✓»
- Фон: молчать
- Перейти к шагу 5

**Есть изменения** — получить список новых коммитов (если `gh` доступен):

```powershell
$commits = gh api "repos/Haif84/alk-axapta-marketplace/commits?sha=master&per_page=20" | ConvertFrom-Json
$newCommits = @()
foreach ($c in $commits) {
    if ($c.sha -eq $state.last_known_sha) { break }
    $newCommits += "$($c.commit.author.date.Substring(0,10))  $($c.commit.message.Split("`n")[0])"
}
```

Если `gh` недоступен — показать только короткий `$remoteSha`.

### Шаг 4. Уведомление

**Фоновый режим** (вызвано из CronCreate, маркер `ФОНОВАЯ_ПРОВЕРКА_ALK`):
- Отправить `PushNotification`: `"alk-axapta: доступно обновление ($($newCommits.Count) коммитов). Перезапустите VS Code или /plugin marketplace update alk-axapta"`
- Сохранить `pending_sha = $remoteSha`, обновить `last_check`
- Выйти без интерактива

**Интерактивный режим**:
- Показать список новых коммитов
- Пояснить: «Обновление подтянется автоматически при следующем старте VS Code (native autoUpdate).
  Чтобы обновить **сейчас** — выполните `/plugin marketplace update alk-axapta`, затем `/reload-plugins`.»
- Если `pending_sha` == `$remoteSha` — добавить «(вы уже видели это уведомление)»
- **Никакого ручного копирования в кэш** — обновление делает штатный механизм Claude Code.

### Шаг 5. CronCreate на следующие сутки

Если `cron_scheduled` не установлен, или выполняется ручной `/check-updates`:

Вызвать `CronCreate`:
```
schedule = "37 9 * * *"   # не :00/:30 — снижает нагрузку на флит
durable  = true            # переживает перезапуск VS Code (до 7 дней)
prompt   = "ФОНОВАЯ_ПРОВЕРКА_ALK: проверь обновления маркетплейса alk-axapta.
            Тихий фоновый режим: если нет обновлений — молчи, обнови last_check.
            Если есть новые коммиты — отправь PushNotification, сохрани pending_sha.
            Не задавай вопросов пользователю и не запускай обновление сам."
```

Установить `cron_scheduled: true`.

### Шаг 6. Сохраняем состояние

```powershell
@{
    last_check      = [DateTime]::UtcNow.ToString("o")
    last_known_sha  = $remoteSha    # или прежнее, если нет сети
    pending_sha     = $pendingSha   # null или SHA
    cron_scheduled  = $true
} | ConvertTo-Json | Set-Content -Encoding UTF8 $statePath
```

## Примечание

Установленная версия обновляется штатно: при включённом `autoUpdate` (его прописывает
`bootstrap.ps1` в `extraKnownMarketplaces`) Claude Code обновляет плагины при старте. Этот скилл
лишь сообщает о доступном обновлении в долгих сессиях — он не подменяет файлы плагинов вручную.
