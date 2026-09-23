# Pause guard on two events: UserPromptSubmit catches the first message after a
# long pause and blocks it once; PostToolUse (matcher AskUserQuestion) catches an
# answer to a question that hung for hours and stops the turn the same way.
# Either way the owner sees the price before paying for the turn.
# A pause longer than the hour-long cache TTL means the next request rewrites
# the whole accumulated context (docs/costs.md: 150k on Opus ~$1.50 against
# ~$0.40 for a fresh session). Blocking here costs nothing: the prompt never
# reaches the model. A warning through additionalContext would cost the very
# rewrite it warns about, so this hook blocks instead of talking.
# The block is a single one per pause: the marker holds the timestamp of the
# assistant message it fired on, so a later pause in the same session fires again.
$ErrorActionPreference = 'SilentlyContinue'
. (Join-Path $PSScriptRoot 'lib\ascii-json.ps1')
. (Join-Path $PSScriptRoot 'lib\system-prompt.ps1')

$MinGapMinutes = 55      # cache TTL is 60; warn before it expires, not after
$MinContext = 60000      # below this the rewrite costs under $0.60 — not worth a stop
$CacheTtlMinutes = 60
$PricePerKTok = 0.01     # hourly cache write on Opus, calibrated in docs/costs.md

# Claude Code writes the event as UTF-8; [Console]::In would decode it with the
# console codepage (CP866 here) and mangle Cyrillic in the prompt.
$reader = New-Object System.IO.StreamReader([Console]::OpenStandardInput(), (New-Object System.Text.UTF8Encoding $false))
$raw = $reader.ReadToEnd()
try { $j = $raw | ConvertFrom-Json } catch { exit 0 }
# Два входа с одной ценой: сообщение (UserPromptSubmit) и ответ на висящий вопрос
# (PostToolUse с matcher AskUserQuestion). Второй путь мимо UserPromptSubmit идёт.
# Имя инструмента проверяется здесь, а не только matcher-ом в settings.json:
# расширь matcher случайно — и любой инструмент после простоя останавливал бы ход.
$answer = ($j.hook_event_name -eq 'PostToolUse' -and $j.tool_name -eq 'AskUserQuestion')
if ($j.hook_event_name -eq 'PostToolUse' -and -not $answer) { exit 0 }
# Сабагент работает часами, и его отчёт приходит ровно в «пауза дольше часа».
# Владелец такой промпт не набирал и повторить не может. Ворота до маркера:
# иначе уведомление израсходует маркер и цену паузы владелец не увидит.
if (Test-SystemPrompt $j.prompt) { exit 0 }
$path = $j.transcript_path
if (-not $path -or -not (Test-Path -LiteralPath $path)) { exit 0 }

$ctx = 0; $stamp = $null; $tail = ''
$lines = @(Get-Content -LiteralPath $path -Tail 300 -Encoding utf8)
[array]::Reverse($lines)
foreach ($line in $lines) {
    if ($line -notmatch '"type":"assistant"' -or $line -notmatch '"usage"') { continue }
    # A subagent runs on its own cache prefix: its reply does not refresh the
    # cache of the main conversation, so it is not activity for our purpose.
    if ($line -match '"isSidechain":true') { continue }
    try { $entry = $line | ConvertFrom-Json } catch { continue }
    $u = $entry.message.usage
    if (-not $u) { continue }
    $ctx = [int]$u.input_tokens + [int]$u.cache_creation_input_tokens + [int]$u.cache_read_input_tokens
    $stamp = $entry.timestamp
    $text = @($entry.message.content | Where-Object { $_.type -eq 'text' } | ForEach-Object { $_.text }) -join ' '
    if ($text) { $tail = ($text -replace '\s+', ' ').Trim() }
    break
}
if (-not $stamp -or $ctx -lt $MinContext) { exit 0 }

try { $gap = ([datetime]::UtcNow - [datetime]::Parse($stamp).ToUniversalTime()).TotalMinutes } catch { exit 0 }
if ($gap -lt $MinGapMinutes) { exit 0 }

$marker = Join-Path $env:TEMP ("claude-pause-guard-{0}.flag" -f $j.session_id)
if ((Test-Path -LiteralPath $marker) -and ((Get-Content -LiteralPath $marker -Raw).Trim() -eq $stamp)) { exit 0 }
Set-Content -LiteralPath $marker -Value $stamp -Encoding ascii

$k = [int]($ctx / 1000)
$price = [string]::Format([cultureinfo]::InvariantCulture, '{0:0.00}', $ctx / 1000 * $PricePerKTok)
$mins = [int]$gap
$left = $CacheTtlMinutes - $mins
$expired = ($gap -ge $CacheTtlMinutes)
if ($answer) {
    # Ответ уже сохранён, промпта не было — советовать повторную отправку нечего,
    # а /remember отговаривать: скилл сам стоит дорогого хода по этому же контексту.
    $when = if ($expired) { "Пауза $mins мин, кэш истёк." } else { "Пауза $mins мин, кэш истекает через $left мин." }
    $head = "$when Контекст ${k}k — перезапись ≈`$$price против ≈`$0.40 за новую сессию. Ответ сохранён, ход к модели не ушёл: продолжить здесь — напиши сообщение, и перезапись оплатится; дешевле закрыть сессию и начать новую, состояние записано в .remember, а handoff по этой сессии собирается из транскрипта за ≈`$0.02."
} elseif ($expired) {
    # Сохранение состояния отсюда стоит полной перезаписи контекста, поэтому
    # дешёвый путь называется прямо: выжимку транскрипта делает скрипт, и
    # handoff по закрытой сессии пишет сабагент из новой (docs/scripts.md).
    $head = "Пауза $mins мин, кэш истёк. Контекст ${k}k — перезапись ≈`$$price против ≈`$0.40 за новую сессию. Состояние сессии уже записано в .remember, а handoff по этой сессии собирается из транскрипта за ≈`$0.02 — возвращаться сюда ради него дороже. Продолжить здесь — отправь сообщение ещё раз."
} else {
    $head = "Пауза $mins мин, кэш истекает через $left мин. Контекст ${k}k — после истечения перезапись ≈`$$price против ≈`$0.40 за новую сессию. Продолжаешь — отправляй сейчас же ещё раз, иначе /remember и новая сессия."
}
if ($tail.Length -gt 200) { $tail = '...' + $tail.Substring($tail.Length - 200) }
# The blocked prompt is echoed by the client itself as "Original prompt", so
# the hook does not repeat it.
$msg = $head
if ($tail) { $msg += "`n`nПоследнее в сессии: $tail" }

if ($answer) {
    # PostToolUse блокировать промпт не умеет: остановка хода — это continue=false,
    # и stopReason клиент печатает строкой «hook stopped continuation».
    ConvertTo-AsciiJson @{ continue = $false; stopReason = $msg }
} else {
    ConvertTo-AsciiJson @{ decision = 'block'; reason = $msg }
}
exit 0
