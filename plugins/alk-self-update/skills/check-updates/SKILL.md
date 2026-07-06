---
name: check-updates
description: Проверяет, есть ли новые коммиты в маркетплейсе alk-axapta (Haif84/alk-axapta-marketplace). В фоне (cron) только уведомляет через PushNotification, файлы не трогает. В интерактивном режиме показывает CLI-команды для применения обновления (claude plugin marketplace update / claude plugin update) и с согласия пользователя может их выполнить — актуально для VS Code extension, где /plugin и /reload-plugins недоступны. Ставит durable cron на фоновую проверку каждые 2 часа (8:30-22:30, минута рандомизирована 31-35 на каждой машине — не грузит инфраструктуру одновременными срабатываниями). Триггеры — «проверь обновления alk», «check updates», «/check-updates», а также фоновый запуск из CronCreate по маркеру ФОНОВАЯ_ПРОВЕРКА_ALK.
---

# check-updates

Проверяет, есть ли новые коммиты в маркетплейсе `Haif84/alk-axapta-marketplace`, и **уведомляет**
о них.

Этот скилл нужен только для долго открытых сессий, когда VS Code не перезапускается сутками и
нативная проверка на старте не срабатывает.

**Важно про среду VS Code extension**: в native VS Code extension (в отличие от отдельного
CLI/терминала) слэш-команды `/plugin marketplace update` и `/reload-plugins` **недоступны**
("isn't available in this environment"), и простой рестарт VS Code (Developer: Reload Window)
сам по себе **не гарантирует** подтягивание новой версии, даже при включённом auto-update
тумблере — проверено 03.07.2026. Рабочий путь — CLI-команды `claude plugin marketplace update` /
`claude plugin update <plugin>@<marketplace>` из обычного терминала (см. Шаг 4).

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
- Отправить `PushNotification`: `"alk-axapta: доступно обновление ($($newCommits.Count) коммитов). Спросите ассистента про /check-updates, чтобы обновить."`
- Сохранить `pending_sha = $remoteSha`, обновить `last_check`
- **Не выполнять** `claude plugin update` в фоне — обновление плагина мид-сессии без ведома
  пользователя может незаметно поменять поведение других скиллов; CLI-команды применяются
  только в интерактивном режиме и только с согласия пользователя (см. ниже)
- Выйти без интерактива

**Интерактивный режим**:
- Показать список новых коммитов.
- Показать команды, которыми обновление применяется **прямо сейчас** (работают и в VS Code
  extension, и в CLI — в отличие от `/plugin`/`/reload-plugins`, см. примечание выше):
  ```powershell
  claude plugin marketplace update alk-axapta
  $ip = Get-Content "$env:USERPROFILE\.claude\plugins\installed_plugins.json" -Raw | ConvertFrom-Json
  $ip.plugins.PSObject.Properties.Name |
      Where-Object { $_ -like "*@alk-axapta" } |
      ForEach-Object { claude plugin update $_ }
  ```
  (обновляет разом все установленные плагины из этого маркетплейса — не только
  `alk-axapta-tools`; короткое имя без `@alk-axapta` вернёт `Plugin "X" not found`).
- **Спросить пользователя**, выполнить ли эти команды сейчас (через Bash/PowerShell). Если
  согласен — выполнить, затем явно сказать: «Restart to apply changes» — команда сама об этом
  сообщит, нужен рестарт VS Code (Developer: Reload Window), чтобы применилось.
- После рестарта, если пользователь попросит проверить — сверить `installed_plugins.json`
  (`version`/`gitCommitSha`) с ожидаемым значением из Шага 2.
- Если `pending_sha` == `$remoteSha` — добавить «(вы уже видели это уведомление)».

### Шаг 5. CronCreate на регулярную проверку (каждые 2 часа, 8:30-22:30)

Если `cron_scheduled` не установлен, или выполняется ручной `/check-updates`:

**Выбери случайную минуту от 31 до 35 включительно** (один раз на этой машине — не на каждое
срабатывание; cron не поддерживает секундную точность и «случайно каждый раз», поэтому джиттер
делается через фиксацию случайной минуты при первой настройке). Это разводит момент фактического
срабатывания между разными машинами команды на несколько минут, чтобы не грузить инфраструктуру
одновременными запросами ровно в :30.

Вызвать `CronCreate`:
```
schedule = "<M> 8-22/2 * * *"  # <M> — случайное 31-35, выбранное один раз для этой машины;
                                 # 8-22/2 = 8,10,12,14,16,18,20,22 — каждые 2 часа с 8:30 до 22:30,
                                 # не ночью
durable  = true                 # переживает перезапуск VS Code (до 7 дней)
prompt   = "ФОНОВАЯ_ПРОВЕРКА_ALK: проверь обновления маркетплейса alk-axapta.
            Тихий фоновый режим: если нет обновлений — молчи, обнови last_check.
            Если есть новые коммиты — отправь PushNotification, сохрани pending_sha.
            Не задавай вопросов пользователю и не запускай обновление сам."
```

Пример при выпавшем `M=33`: `schedule = "33 8-22/2 * * *"` → срабатывает в 8:33, 10:33, 12:33, ...,
22:33 каждый день.

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

В отдельном CLI/терминале обновление штатно применяется через `/plugin marketplace update
alk-axapta` + `/reload-plugins`, либо подтягивается само при старте, если для магазина включён
auto-update тумблер. В **VS Code extension** обе слэш-команды недоступны и рестарт сам по себе
не гарантирует обновление — используйте CLI-команды из Шага 4 (`claude plugin marketplace
update` / `claude plugin update <plugin>@<marketplace>`) через Bash/PowerShell с согласия
пользователя, затем попросите перезапустить VS Code. Никакого ручного копирования файлов в
кэш — только официальные CLI-команды `claude plugin ...`.
