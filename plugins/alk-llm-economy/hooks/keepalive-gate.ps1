# UserPromptSubmit hook: gate on the keepalive ping that the session schedules
# for itself (CronCreate '13,43 * * * *', prompt 'keepalive: ответь точкой',
# docs/decisions/2026-09-18-keepalive-cron.md).
# Кэш живёт 60 минут с последнего запроса, и чтение префикса продлевает срок
# заново: при 100k пинг стоит $0.05 на Opus против $1.00 за перезапись всего
# контекста после часа простоя. Безубыточность — 20 пингов, лимит здесь 6.
# Три исхода на маркерный промпт: блок (ноль токенов — ход к модели не уходит),
# пинг как есть, и последний пинг с additionalContext про handoff. Промпт без
# маркера хук не трогает, только обнуляет счётчик паузы.
$ErrorActionPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot 'lib\ascii-json.ps1')
. (Join-Path $PSScriptRoot 'lib\system-prompt.ps1')

$MinGapMinutes = 25      # cron ходит раз в 30 минут; ответ свежее — продлевать нечего
$MinContext = 60000      # порог pause-guard: ниже перезапись дешевле шести пингов
$MaxPings = 6            # 6 пингов держат кэш 3 часа; дальше цена простоя растёт зря

$reader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), (New-Object System.Text.UTF8Encoding $false))
$raw = $reader.ReadToEnd()
try { $j = $raw | ConvertFrom-Json } catch { exit 0 }
if ($j.hook_event_name -and $j.hook_event_name -ne 'UserPromptSubmit') { exit 0 }

$marker = Join-Path $env:TEMP ("claude-keepalive-{0}.flag" -f $j.session_id)
# Промпт владельца означает, что пауза кончилась: счётчик начинается заново.
# Уведомление сабагента или сообщение соседней сессии идут тем же событием, но
# владельца за клавиатурой не значат — счётчик они не трогают, иначе лимит
# паузы обходился бы сам собой.
if ($j.prompt -notmatch '^\s*keepalive:') {
    if (-not (Test-SystemPrompt $j.prompt)) {
        Remove-Item -LiteralPath $marker -Force -ErrorAction SilentlyContinue
    }
    exit 0
}

function Deny([string]$Reason) {
    ConvertTo-AsciiJson @{ decision = 'block'; reason = $Reason }
    exit 0
}

$path = $j.transcript_path
if (-not $path -or -not (Test-Path -LiteralPath $path)) { Deny 'keepalive: транскрипт не прочитан, продлевать нечего.' }

$ctx = 0; $stamp = $null
$lines = @(Get-Content -LiteralPath $path -Tail 300 -Encoding utf8)
[array]::Reverse($lines)
foreach ($line in $lines) {
    if ($line -notmatch '"type":"assistant"' -or $line -notmatch '"usage"') { continue }
    # Сабагент живёт на своём префиксе кэша: его ответ кэш основной сессии не
    # продлевает, значит и активностью для этого порога не является.
    if ($line -match '"isSidechain":true') { continue }
    try { $entry = $line | ConvertFrom-Json } catch { continue }
    $u = $entry.message.usage
    if (-not $u) { continue }
    $ctx = [int]$u.input_tokens + [int]$u.cache_creation_input_tokens + [int]$u.cache_read_input_tokens
    $stamp = $entry.timestamp
    break
}
if (-not $stamp) { Deny 'keepalive: в транскрипте нет ответа модели, продлевать нечего.' }

$k = [int]($ctx / 1000)
$min = [int]($MinContext / 1000)
if ($ctx -lt $MinContext) { Deny "keepalive: контекст ${k}k меньше ${min}k — перезапись дешевле пинга." }

try { $gap = ([datetime]::UtcNow - [datetime]::Parse($stamp).ToUniversalTime()).TotalMinutes } catch { exit 0 }
if ($gap -lt $MinGapMinutes) { Deny ("keepalive: последний ответ {0} мин назад, кэш продлён без пинга." -f [int]$gap) }

# Маркер держит две строки: счётчик пингов и отметку хода, на котором пауза
# началась. Без второй строки длину паузы пришлось бы считать по промежутку до
# прошлого пинга — а это всегда 30 минут, сколько бы владельца ни не было.
$count = 0; $since = $stamp
if (Test-Path -LiteralPath $marker) {
    $saved = @(Get-Content -LiteralPath $marker -Encoding ascii)
    if ($saved.Count -ge 1) { $count = [int]$saved[0] }
    if ($saved.Count -ge 2 -and $saved[1]) { $since = $saved[1] }
}
if ($count -ge $MaxPings) { Deny "keepalive: $MaxPings пингов в этой паузе исчерпаны, кэш дальше не продлеваем." }

$count++
Set-Content -LiteralPath $marker -Value @("$count", $since) -Encoding ascii
if ($count -lt $MaxPings) { exit 0 }

# Последний пинг: ход к модели всё равно оплачен чтением кэша, и пишет handoff
# та самая сессия, которая всё видела, — внешний сабагент по транскрипту дешевле,
# но хуже. Замер session-cost.js и rename остаются за /remember владельца.
try { $away = [int]([datetime]::UtcNow - [datetime]::Parse($since).ToUniversalTime()).TotalMinutes } catch { $away = [int]$gap }
$msg = "keepalive: пауза $away мин, владелец не вернулся, и это последний пинг — дальше кэш не продлевается. Вместо точки запиши handoff в .remember/remember.md по шаблону: State (сделано, коммиты, дерево), Next (нумерованные шаги), Context (решения владельца, файлы и строки, что не делать). Ничего не коммить и не запускать, только записать файл и ответить одной строкой."
ConvertTo-AsciiJson @{ hookSpecificOutput = @{ hookEventName = 'UserPromptSubmit'; additionalContext = $msg } }
exit 0
